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

# ---------- reading aloud: what is SENT to the voice (the shown text is unchanged) ----------

ACRONYMS = {
    "TMS": "te eme ese",
    "B2B": "be tu be",
    "B2C": "be tu ce",
    "CRM": "ce erre eme",
    "ERP": "e erre pe",
    "GPS": "ge pe ese",
    "API": "a pe i",
    "SMS": "ese eme ese",
    "PDF": "pe de efe",
    "QR": "cu erre",
}
# Colombian mobile: 300 123 4567 -> "300, 123, 45, 67" (optional +57 / 57 prefix).
PHONE = re.compile(r"(?<![\d])(?:(\+?57)[\s-]?)?(3\d{2})[\s.-]?(\d{3})[\s.-]?(\d{2})[\s.-]?(\d{2})(?![\d])")
URL = re.compile(r"^(?:https?://)?(?:www\.)?([\w-]+(?:\.[\w-]+)*\.(?:com|co|net|org|io))(?:/\S*)?$", re.IGNORECASE)
_EDGE_PUNCT = re.compile(r"^([^\w+%]*)(.*?)([^\w%]*)$", re.DOTALL)

def _phone_spoken(m: re.Match) -> str:
    prefix = "más cincuenta y siete, " if m.group(1) else ""
    return f"{prefix}{m.group(2)}, {m.group(3)}, {m.group(4)}, {m.group(5)}"

def _token_spoken(token: str) -> str:
    """Spoken form of one whitespace-free token, keeping its edge punctuation."""
    lead, core, trail = _EDGE_PUNCT.match(token).groups()
    if not core:
        return token
    if core in ACRONYMS:
        spoken = ACRONYMS[core]
    elif core == "%":
        spoken = "por ciento"
    elif core.endswith("%") and core[:-1].replace(",", "").replace(".", "").isdigit():
        spoken = f"{core[:-1]} por ciento"
    elif (m := URL.match(core)):
        spoken = m.group(1).replace(".", " punto ")
    else:
        return token
    return f"{lead}{spoken}{trail}"

def _units(text: str) -> list[tuple[list[str], str]]:
    """Splits `text` into (original words, spoken text) units, in order. A phone number spans
    several original words; every other unit is one word."""
    units: list[tuple[list[str], str]] = []
    pos = 0
    def plain(chunk: str):
        for token in chunk.split():
            units.append(([token], _token_spoken(token)))
    for m in PHONE.finditer(text):
        plain(text[pos:m.start()])
        trail = re.match(r"[^\w\s]*", text[m.end():]).group(0)  # "." or ")" stuck to the number
        units.append((m.group(0).split(), _phone_spoken(m) + trail))
        pos = m.end() + len(trail)
    plain(text[pos:])
    return units

def speakable(text: str) -> str:
    """Text as it should be read aloud: acronyms spelled out, web addresses and phone numbers
    pronounceable, "%" as "por ciento". Only for the voice engine, never for the screen."""
    return " ".join(spoken for _, spoken in _units(text))

def _spoken_count(spoken: str) -> int:
    return len(re.findall(r"\S*\w\S*", spoken))

def _original_count(words: list[str]) -> int:
    return sum(1 for w in words if re.search(r"\w", w))

def realign_words(text: str, words: list[dict]) -> list[dict]:
    """The voice returns timings for the SPOKEN words ("te eme ese"). Map them back to the
    words of the shown `text` ("TMS") so the karaoke captions stay in step: each unit's time
    span is split evenly between its original words. If the counts don't match (the engine
    tokenised differently), timings are estimated over the shown words."""
    units = _units(text)
    if all(spoken == " ".join(orig) for orig, spoken in units):
        return words
    if sum(_spoken_count(spoken) for _, spoken in units) != len(words):
        end = words[-1]["start"] + words[-1]["duration"] if words else 0
        return _estimate_words(text, end + 0.15) if end else words
    out, i = [], 0
    for orig, spoken in units:
        n, shown = _spoken_count(spoken), [w for w in orig if re.search(r"\w", w)]
        chunk, i = words[i:i + n], i + n
        if not chunk or not shown:
            continue
        start, end = chunk[0]["start"], chunk[-1]["start"] + chunk[-1]["duration"]
        step = (end - start) / len(shown)
        for k, w in enumerate(shown):
            clean = re.sub(r"^[^\w]+|[^\w]+$", "", w)
            out.append({"text": clean, "start": round(start + k * step, 3), "duration": round(step, 3)})
    return out

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
            audio, words = await (_azure if name == "azure" else _edge)(speakable(text), voice, rate)
            words = realign_words(text, words)
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
