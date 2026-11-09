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
# Phrases Whisper is known to invent on silence or noise: dropped whatever the audio length.
HALLUCINATIONS = re.compile(r"subt[ií]tulos|amara\.org|suscr[ií]bete|gracias por ver", re.IGNORECASE)
# Text that is ONLY a web address ("celuweb.com", "www.x.com/y"): a typical invention. A real
# question that merely mentions a site ("¿es celuweb.com?") has more words and is kept.
URL_ONLY = re.compile(
    r"^\s*(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|co|net|org|io|info|es|mx|app|dev)(?:/\S*)?\s*[.!?¿¡]*\s*$",
    re.IGNORECASE,
)
# Short closings Whisper also invents on silence. A visitor can really say "gracias", so these
# are dropped only when the clip is very short or Whisper itself was unsure.
SILENCE_PHRASES = re.compile(
    r"^[\s¿¡]*(gracias|muchas gracias|hasta la pr[oó]xima|hasta luego|nos vemos|chao|chau|adi[oó]s|"
    r"y eso es todo|eso es todo|mm+|hmm+|um)[\s.,!?]*$",
    re.IGNORECASE,
)
SHORT_CLIP_SECONDS = 0.8
LOW_LOGPROB = -1.0   # Whisper's own "I'm not sure" threshold
NO_SPEECH_DROP = 0.7  # segment almost surely silence
NO_SPEECH_DOUBT = 0.4  # ...or doubtful and also low-confidence


def keep_segment(no_speech_prob: float, avg_logprob: float | None) -> bool:
    if no_speech_prob >= NO_SPEECH_DROP:
        return False
    return not (no_speech_prob >= NO_SPEECH_DOUBT and avg_logprob is not None and avg_logprob < LOW_LOGPROB)


def is_hallucination(text: str, duration: float = 0.0, logprob: float | None = None) -> bool:
    """True if `text` is probably something Whisper made up on silence or noise."""
    if HALLUCINATIONS.search(text) or URL_ONLY.match(text):
        return True
    words = len(text.split())
    if words <= 4 and SILENCE_PHRASES.match(text):
        too_short = 0 < duration < SHORT_CLIP_SECONDS
        unsure = logprob is not None and logprob < LOW_LOGPROB
        return too_short or unsure
    return False

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

def _transcribe_local(audio: bytes) -> tuple[str, float, float | None]:
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
    kept = [s for s in segments if keep_segment(s.no_speech_prob, s.avg_logprob)]
    text = " ".join(s.text.strip() for s in kept).strip()
    return text, info.duration, _mean([s.avg_logprob for s in kept])

def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None

# ---------- Groq cloud ----------

# One connection pool for the whole process: avoids a TCP+TLS handshake on every turn.
_groq = httpx.Client(timeout=30)

def _transcribe_groq(audio: bytes, content_type: str) -> tuple[str, float, float | None]:
    extension = "ogg" if "ogg" in content_type else "mp4" if "mp4" in content_type else "wav" if "wav" in content_type else "webm"
    response = _groq.post(
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
    )
    if response.status_code == 429:
        raise STTUnavailable("Groq: límite gratuito alcanzado por ahora")
    response.raise_for_status()
    data = response.json()
    segments = data.get("segments") or []
    # Drop segments Whisper itself flags as probably silence or very unsure.
    kept = [s for s in segments if keep_segment(s.get("no_speech_prob", 0), s.get("avg_logprob"))]
    text = " ".join(s["text"].strip() for s in kept) if segments else data.get("text", "")
    return text.strip(), float(data.get("duration") or 0), _mean([s["avg_logprob"] for s in kept if "avg_logprob" in s])

def transcribe(audio: bytes, content_type: str = "audio/webm") -> dict:
    provider = settings.effective_stt
    if provider not in ("groq", "whisper"):
        raise STTUnavailable("El servidor no transcribe (STT_PROVIDER=browser)")
    started = time.perf_counter()
    try:
        if provider == "groq":
            text, duration, logprob = _transcribe_groq(audio, content_type)
        else:
            text, duration, logprob = _transcribe_local(audio)
    except STTUnavailable:
        raise
    except Exception as exc:  # network errors, undecodable audio, model errors...
        raise STTUnavailable(str(exc)) from exc
    if is_hallucination(text, duration, logprob):
        text = ""
    # No transcript in the log: it is the visitor's personal data.
    logger.info("STT[%s] %.2fs for %.1fs of audio: %d chars", provider, time.perf_counter() - started, duration, len(text))
    return {"text": correct_terms(text), "duration": round(duration, 2)}
