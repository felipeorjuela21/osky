"""Neural text-to-speech with word timings (for captions and gestures).

Providers (TTS_PROVIDER):
- "azure": official Azure Speech REST API. The free F0 tier includes 500k
  characters/month. Needs AZURE_SPEECH_KEY + AZURE_SPEECH_REGION.
- "edge": Microsoft Edge read-aloud service through `edge-tts`: free and no key,
  but unofficial (no SLA). Also the automatic fallback if Azure fails.
Both use the same neural voices (e.g. es-CO-GonzaloNeural).
"""
import base64
import hashlib
import re
from collections import OrderedDict
from xml.sax.saxutils import escape

import edge_tts
import httpx

from backend.app.core.config import settings

CACHE_SIZE = 128
_cache: OrderedDict[str, dict] = OrderedDict()
_voices: list[dict] = []

AZURE_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
AZURE_BITRATE = 48_000  # bits per second of the format above (used to know the duration)

class TTSUnavailable(RuntimeError):
    pass

def _estimate_words(text: str, seconds: float) -> list[dict]:
    """Azure's REST API returns no word timings: spread the words over the audio length,
    proportionally to their length (punctuation adds a short pause)."""
    tokens = re.findall(r"\S+", text)
    weights = [len(re.sub(r"[^\w]", "", t)) + 1 + (2 if re.search(r"[.,;:!?]$", t) else 0) for t in tokens]
    total = sum(weights) or 1
    lead, usable = 0.05, max(0.1, seconds - 0.15)
    words, t = [], lead
    for token, weight in zip(tokens, weights):
        duration = usable * weight / total
        clean = re.sub(r"^[^\w]+|[^\w]+$", "", token)
        if clean:
            words.append({"text": clean, "start": round(t, 3), "duration": round(duration * 0.85, 3)})
        t += duration
    return words

async def _azure(text: str, voice: str, rate: str) -> tuple[bytes, list[dict]]:
    ssml = (
        f"<speak version='1.0' xml:lang='es-CO'><voice name='{voice}'>"
        f"<prosody rate='{rate}'>{escape(text)}</prosody></voice></speak>"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://{settings.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": AZURE_FORMAT,
                "User-Agent": "oski-celuweb",
            },
            content=ssml.encode("utf-8"),
        )
    if response.status_code != 200:
        raise TTSUnavailable(f"Azure TTS {response.status_code}")
    audio = response.content
    return audio, _estimate_words(text, len(audio) * 8 / AZURE_BITRATE)

async def _edge(text: str, voice: str, rate: str) -> tuple[bytes, list[dict]]:
    audio = bytearray()
    words: list[dict] = []
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            words.append({
                "text": chunk["text"],
                "start": round(chunk["offset"] / 1e7, 3),
                "duration": round(chunk["duration"] / 1e7, 3),
            })
    return bytes(audio), words

async def synthesize(text: str, voice: str | None = None, rate: str | None = None) -> dict:
    """Returns {"audio": base64 mp3, "format": "mp3", "words": [{text, start, duration}]} (seconds)."""
    provider = settings.effective_tts
    if provider not in ("azure", "edge"):
        raise TTSUnavailable("Server TTS disabled (TTS_PROVIDER)")
    voice = voice or settings.tts_voice
    rate = rate or settings.tts_rate
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    audio, words = b"", []
    errors = []
    for name in ([provider, "edge"] if provider == "azure" else [provider]):
        try:
            audio, words = await (_azure if name == "azure" else _edge)(text, voice, rate)
            if audio:
                break
        except Exception as exc:  # network errors, quota, service changes...
            errors.append(f"{name}: {exc}")
    if not audio:
        raise TTSUnavailable("; ".join(errors) or "No audio received")

    result = {"audio": base64.b64encode(audio).decode(), "format": "mp3", "voice": voice, "words": words}
    _cache[key] = result
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result

async def spanish_voices() -> list[dict]:
    global _voices
    if not _voices:
        try:
            voices = await edge_tts.list_voices()
        except Exception as exc:
            raise TTSUnavailable(str(exc)) from exc
        # Osky is a man: only male Spanish voices are offered.
        _voices = [
            {"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
            for v in voices
            if v["Locale"].startswith("es-") and v["Gender"] == "Male"
        ]
    return _voices

async def allowed_voice(voice: str | None) -> str:
    """The requested voice if it is one of Osky's (male) voices, else the default."""
    if not voice or voice == settings.tts_voice:
        return settings.tts_voice
    try:
        names = {v["name"] for v in await spanish_voices()}
    except TTSUnavailable:
        return settings.tts_voice
    return voice if voice in names else settings.tts_voice
