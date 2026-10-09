"""Natural answers grounded ONLY on CeluWeb's own sources (Groq, free tier).

The search engine (knowledge.py) finds the relevant company text; the LLM just
rewrites it as a short, friendly answer. If the call fails, times out, or the
answer contains a number that is not in the sources, Osky falls back to the
literal extract, so it never invents figures.
"""
import logging
import re

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

def _chat(model: str, messages: list[dict]) -> httpx.Response:
    return httpx.post(
        GROQ_CHAT_URL,
        headers=_headers(),
        json={"model": model, "temperature": 0.3, "max_tokens": 220, "messages": messages},
        timeout=8,
    )

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
    status.update(model=model, ok=True, error=None)
    return response.json()["choices"][0]["message"]["content"].strip()

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
- {length}
- Texto plano: sin markdown, sin viñetas, sin emojis."""

LENGTH = {
    "voice": "Responde en máximo 2 frases cortas (unas 40 palabras), porque se va a escuchar en voz alta.",
    "chat": "Responde en máximo 4 frases.",
}

def _numbers(text: str) -> set[str]:
    return {re.sub(r"[.,\s]", "", n) for n in re.findall(r"\d[\d.,\s]*\d|\d", text)}

def natural_answer(question: str, context: list[dict], style: str = "chat", name: str | None = None) -> str | None:
    """Short grounded answer, or None to use the literal extract instead."""
    if settings.effective_llm != "groq" or not context:
        return None
    sources = "\n\n".join(f"[{i + 1}] {c['title']}: {c['content']}" for i, c in enumerate(context))
    system = SYSTEM.format(name=settings.agent_name, company=settings.company_name, length=LENGTH.get(style, LENGTH["chat"]))
    if name:
        system += f"\n- La persona se llama {name}: llámala por su nombre de forma natural al inicio de la respuesta."
    try:
        answer = _complete([
            {"role": "system", "content": system},
            {"role": "user", "content": f"CONTEXTO:\n{sources}\n\nPREGUNTA: {question}"},
        ])
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
