"""Speech-to-text for the user's recorded turn.

Providers (STT_PROVIDER):
- "groq": Whisper large-v3 in Groq's cloud (free tier, no card). Used on the
  free server, which is too small to run Whisper itself.
- "whisper": local faster-whisper on CPU (needs ~1-2 GB RAM; optional install
  from backend/requirements-local.txt).
- "browser": the server does not transcribe; the page uses Chrome/Edge recognition.
"""
import io
import logging
import os
import re
import threading
import time

import httpx

from backend.app.core.config import settings

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

logger = logging.getLogger("uvicorn.error")

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Vocabulary hint so company terms are spelled right ("CeluWeb", not "Celubeb").
PROMPT = (
    "Conversación en español con Osky, el asistente virtual de CeluWeb. Soluciones de CeluWeb: "
    "TMS, Pricing, Chat Bot, B2B, Field Service, Televenta, Supervisores, Link de pagos, Mapas, "
    "Mercadeo, Fuerza de Ventas, Entregas."
)
# Phrases Whisper is known to invent on silence or noise.
HALLUCINATIONS = re.compile(
    r"subt[ií]tulos|amara\.org|suscr[ií]bete|gracias por ver|www\.|\.com$", re.IGNORECASE
)

# Company terms Whisper tends to mishear (acronyms and English names).
CORRECTIONS = [
    # "¿Qué es TMS?" is often heard as "¿Qué esté meces?" ("es" merged into the acronym).
    (r"\b(est[eé]\s?m[eé]\s?(?:s[eé][sr]?|ce[sr]?)|estemes)\b", "es TMS"),
    (r"\b(t\.?\s?m\.?\s?s\.?|t[eé]\s?eme\s?ese|t[eé]\s?m[eé]\s?(?:s[eé][sr]?|ce[sr]?)|t[eé]mes)\b", "TMS"),
    (r"\b(pricy|pricin|pr[aá]is?ing|praising|prisin[g]?|precing)\b", "Pricing"),
    (r"\b(celu\s?[bvw]e[bvw]|celuveb|celubeb|celuvweb|cel[uú]\s?gueb)\b", "CeluWeb"),
    (r"\b(chat\s?bot|chat\s?boot)\b", "Chat Bot"),
    (r"\b(b\s?2\s?b|be\s?tu\s?be|bi\s?tu\s?bi|b\s?to\s?b)\b", "B2B"),
    (r"\b(f[ií]el?d?\s?serv[ií]ce?s?|fil\s?servis)\b", "Field Service"),
    (r"\b(guasap|wasap|whats\s?app)\b", "WhatsApp"),
]

def correct_terms(text: str) -> str:
    for pattern, replacement in CORRECTIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text

class STTUnavailable(RuntimeError):
    pass

# ---------- local faster-whisper ----------

_model = None
_lock = threading.Lock()

def get_model():
    """Loads (once) and warms up the local Whisper model."""
    global _model
    with _lock:
        if _model is None:
            import numpy as np
            from faster_whisper import WhisperModel

            model = WhisperModel(settings.stt_model, device="cpu", compute_type="int8", download_root="data/models")
            # Warm-up: the first transcription is several times slower (VAD + kernels).
            list(model.transcribe(np.zeros(16000, dtype=np.float32), language="es", vad_filter=True)[0])
            _model = model
    return _model

def is_ready() -> bool:
    return settings.effective_stt != "whisper" or _model is not None

def _transcribe_local(audio: bytes) -> tuple[str, float]:
    segments, info = get_model().transcribe(
        io.BytesIO(audio),
        language="es",
        beam_size=1,
        temperature=0.0,  # no retries: faster, and the browser already trims silence
        without_timestamps=True,
        vad_filter=True,
        initial_prompt=PROMPT,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.7).strip()
    return text, info.duration

# ---------- Groq cloud ----------

def _transcribe_groq(audio: bytes, content_type: str) -> tuple[str, float]:
    extension = "ogg" if "ogg" in content_type else "mp4" if "mp4" in content_type else "webm"
    response = httpx.post(
        GROQ_STT_URL,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        data={
            "model": settings.groq_stt_model,
            "language": "es",
            "prompt": PROMPT,
            "response_format": "verbose_json",
            "temperature": "0",
        },
        files={"file": (f"turno.{extension}", audio, content_type or "audio/webm")},
        timeout=30,
    )
    if response.status_code == 429:
        raise STTUnavailable("Groq: límite gratuito alcanzado por ahora")
    response.raise_for_status()
    data = response.json()
    segments = data.get("segments") or []
    # Drop segments Whisper itself flags as probably silence.
    text = " ".join(s["text"].strip() for s in segments if s.get("no_speech_prob", 0) < 0.7) if segments else data.get("text", "")
    return text.strip(), float(data.get("duration") or 0)

def transcribe(audio: bytes, content_type: str = "audio/webm") -> dict:
    provider = settings.effective_stt
    if provider not in ("groq", "whisper"):
        raise STTUnavailable("El servidor no transcribe (STT_PROVIDER=browser)")
    started = time.perf_counter()
    try:
        if provider == "groq":
            text, duration = _transcribe_groq(audio, content_type)
        else:
            text, duration = _transcribe_local(audio)
    except STTUnavailable:
        raise
    except Exception as exc:  # network errors, undecodable audio, model errors...
        raise STTUnavailable(str(exc)) from exc
    if HALLUCINATIONS.search(text):
        text = ""
    logger.info("STT[%s] %.2fs for %.1fs of audio: %r", provider, time.perf_counter() - started, duration, text)
    return {"text": correct_terms(text), "duration": round(duration, 2)}
