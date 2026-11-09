"""Natural answers grounded ONLY on CeluWeb's own sources (Groq, free tier).

The search engine (knowledge.py) finds the relevant company text; the LLM just
rewrites it as a short, friendly answer. If the call fails, times out, or the
answer contains a number that is not in the sources, Osky falls back to the
literal extract, so it never invents figures.

For the voice persona the answer is streamed sentence by sentence
(stream_natural_answer), so Osky starts speaking before the model has finished.
"""
import json
import logging
import re
from collections.abc import Iterator

import httpx

from backend.app.core.config import settings

logger = logging.getLogger("uvicorn.error")

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# Groq retires models now and then: if the configured one is gone, use the first of these that exists.
PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]
NOT_CHAT = re.compile(r"whisper|tts|guard|playai|orpheus|distil|compound", re.I)

# What /health shows: the model in use and the last error (never the key).
status: dict = {"model": None, "ok": None, "error": None}

def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.groq_api_key}"}

def _available_model(exclude: str | None = None) -> str | None:
    """The configured model if Groq still offers it, otherwise the best available one."""
    response = httpx.get(GROQ_MODELS_URL, headers=_headers(), timeout=8)
    response.raise_for_status()
    ids = [m["id"] for m in response.json().get("data", []) if m.get("active", True) and m["id"] != exclude]
    for model in [settings.llm_model, *PREFERRED_MODELS]:
        if model in ids:
            return model
    chat = [i for i in ids if not NOT_CHAT.search(i)]
    return chat[0] if chat else None

def _payload(model: str, messages: list[dict]) -> dict:
    payload = {"model": model, "temperature": 0.3, "max_tokens": 220, "messages": messages}
    # Reasoning models think before answering; that thinking counts as tokens.
    # Keep it short (fast answers) and leave room so the answer is never cut off.
    if "gpt-oss" in model:
        payload.update(reasoning_effort="low", max_tokens=900)
    elif "qwen3" in model:
        payload.update(reasoning_effort="none", max_tokens=600)
    return payload

def _chat(model: str, messages: list[dict]) -> httpx.Response:
    return httpx.post(GROQ_CHAT_URL, headers=_headers(), json=_payload(model, messages), timeout=10)

def _complete(messages: list[dict]) -> str:
    model = status["model"] or settings.llm_model
    response = _chat(model, messages)
    if response.status_code in (400, 404) and "model" in response.text.lower():
        # Model retired or renamed: ask Groq which ones exist and retry once.
        replacement = _available_model(exclude=model)
        if replacement:
            logger.warning("LLM model %s unavailable; switching to %s", model, replacement)
            model = replacement
            response = _chat(model, messages)
    response.raise_for_status()
    choice = response.json()["choices"][0]
    content = (choice["message"].get("content") or "").strip()
    if not content or choice.get("finish_reason") == "length":
        raise ValueError(f"respuesta vacía o cortada (finish_reason={choice.get('finish_reason')})")
    status.update(model=model, ok=True, error=None)
    return content

def _error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    return f"{type(exc).__name__}: {str(exc)[:200]}"

SYSTEM = """Eres {name}, el asistente virtual de {company}. Hablas en español de Colombia, con un tono cálido, cercano y profesional, como un buen asesor.

Reglas estrictas:
- Responde SOLO con la información del CONTEXTO. No uses conocimiento propio.
- Si el CONTEXTO no responde la pregunta, dilo con naturalidad y ofrece comunicar a la persona con un asesor de {company}.
- Nunca inventes cifras, precios, nombres, fechas, clientes ni características.
- No menciones la palabra "contexto" ni que estás leyendo documentos.
- La conversación anterior solo sirve para entender a qué se refiere la persona (por ejemplo "¿y eso cuánto cuesta?"); los datos salen del CONTEXTO.
- Ve directo a la respuesta: no repitas la pregunta ni vuelvas a saludar.
- {length}
- Texto plano: sin markdown, sin viñetas, sin emojis."""

LENGTH = {
    "voice": ("Se va a escuchar en voz alta, como en una llamada: máximo 2 frases cortas (unas 35 palabras), "
              "con palabras sencillas, sin listas largas ni paréntesis. Varía cómo empiezas: no arranques siempre "
              "con \"Claro\". Si viene al caso, cierra con una pregunta corta para seguir la conversación, pero no siempre."),
    "chat": "Responde en máximo 4 frases.",
}

MAX_HISTORY = 3

def _numbers(text: str) -> set[str]:
    return {re.sub(r"[.,\s]", "", n) for n in re.findall(r"\d[\d.,\s]*\d|\d", text)}

def _prompt(question: str, context: list[dict], style: str, history: list[dict] | None) -> tuple[list[dict], str]:
    """Messages for the model, and the sources text (to check the figures of the answer)."""
    sources = "\n\n".join(f"[{i + 1}] {c['title']}: {c['content']}" for i, c in enumerate(context))
    system = SYSTEM.format(name=settings.agent_name, company=settings.company_name, length=LENGTH.get(style, LENGTH["chat"]))
    messages = [{"role": "system", "content": system}]
    for turn in (history or [])[-MAX_HISTORY:]:
        messages += [{"role": "user", "content": turn["q"]}, {"role": "assistant", "content": turn["a"]}]
    messages.append({"role": "user", "content": f"CONTEXTO:\n{sources}\n\nPREGUNTA: {question}"})
    return messages, sources

def natural_answer(question: str, context: list[dict], style: str = "chat",
                   history: list[dict] | None = None) -> str | None:
    """Short grounded answer, or None to use the literal extract instead.

    history: previous turns [{"q": ..., "a": ...}] so follow-ups are understood. The
    visitor's name is never sent to the model: it is added afterwards on our server."""
    if settings.effective_llm != "groq" or not context:
        return None
    messages, sources = _prompt(question, context, style, history)
    try:
        answer = _complete(messages)
    except Exception as exc:  # network, quota (429), timeouts, invalid key...
        status.update(ok=False, error=_error_text(exc))
        logger.warning("LLM unavailable, using extract: %s", status["error"])
        return None

    # Reasoning models may prepend their thinking: keep only the answer.
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()
    # Guard: every number in the answer must exist in the sources.
    invented = _numbers(answer) - _numbers(sources)
    if invented:
        status["error"] = f"respuesta descartada: cifras que no están en las fuentes {sorted(invented)}"
        logger.warning("LLM answer had numbers not in sources %s; using extract", invented)
        return None
    return re.sub(r"[*_#`]", "", answer) or None

# End of a sentence: . ! ? or ... followed by a space (so "1.5" inside a number doesn't split).
SENTENCE_END = re.compile(r"[.!?\u2026]+[\"\u00bb)]*(?=\s)")
MIN_SENTENCE = 18  # shorter pieces are joined with the next one

def _sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences in the buffer, and the unfinished rest."""
    done = []
    while True:
        match = SENTENCE_END.search(buffer, MIN_SENTENCE)
        if not match:
            return done, buffer
        done.append(buffer[:match.end()].strip())
        buffer = buffer[match.end():].lstrip()

def _stream_lines(model: str, messages: list[dict]) -> Iterator[tuple[str, str | None]]:
    """(text delta, finish_reason) from Groq's server-sent events."""
    payload = {**_payload(model, messages), "stream": True}
    timeout = httpx.Timeout(10, read=15)
    with httpx.stream("POST", GROQ_CHAT_URL, headers=_headers(), json=payload, timeout=timeout) as response:
        if response.status_code >= 400:
            response.read()
            response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            choice = (json.loads(data).get("choices") or [{}])[0]
            # Only "content": reasoning models send their thinking in a separate field.
            yield (choice.get("delta") or {}).get("content") or "", choice.get("finish_reason")

def stream_natural_answer(question: str, context: list[dict], style: str = "voice",
                          history: list[dict] | None = None) -> Iterator[str]:
    """Yields the answer one sentence at a time, as the model writes it.

    Same rules as natural_answer: nothing on errors (the caller then uses the literal
    extract), and the answer stops before any sentence with a figure that is not in
    the sources."""
    if settings.effective_llm != "groq" or not context:
        return
    messages, sources = _prompt(question, context, style, history)
    allowed = _numbers(sources)
    model = status["model"] or settings.llm_model
    buffer, thinking, finish = "", False, None

    def checked(sentence: str) -> str | None:
        sentence = re.sub(r"[*_#`]", "", sentence).strip()
        invented = _numbers(sentence) - allowed
        if invented:
            status["error"] = f"respuesta cortada: cifras que no están en las fuentes {sorted(invented)}"
            logger.warning("LLM sentence had numbers not in sources %s; stopping there", invented)
            return None
        return sentence

    for attempt in range(2):
        try:
            for delta, finish in _stream_lines(model, messages):
                buffer += delta
                # Reasoning models may write their thinking between <think> tags: skip it.
                if "<think>" in buffer:
                    thinking = True
                if thinking:
                    if "</think>" not in buffer:
                        continue
                    buffer, thinking = buffer.split("</think>", 1)[1].lstrip(), False
                sentences, buffer = _sentences(buffer)
                for sentence in sentences:
                    ok = checked(sentence)
                    if ok is None:
                        return
                    if ok:
                        yield ok
            break
        except httpx.HTTPStatusError as exc:
            # Model retired or renamed (nothing was said yet): ask Groq which ones exist and retry once.
            if attempt == 0 and exc.response.status_code in (400, 404) and "model" in exc.response.text.lower():
                replacement = _available_model(exclude=model)
                if replacement:
                    logger.warning("LLM model %s unavailable; switching to %s", model, replacement)
                    model = replacement
                    continue
            status.update(ok=False, error=_error_text(exc))
            logger.warning("LLM stream unavailable: %s", status["error"])
            return
        except Exception as exc:  # network, quota (429), timeouts...
            status.update(ok=False, error=_error_text(exc))
            logger.warning("LLM stream interrupted: %s", status["error"])
            return

    tail = buffer.strip()
    if tail and not thinking and finish != "length":  # a cut-off sentence is not said
        ok = checked(tail)
        if ok:
            yield ok
    status.update(model=model, ok=True, error=None)
