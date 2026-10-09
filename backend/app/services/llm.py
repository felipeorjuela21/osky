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
        response = httpx.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.llm_model,
                "temperature": 0.3,
                "max_tokens": 220,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"CONTEXTO:\n{sources}\n\nPREGUNTA: {question}"},
                ],
            },
            timeout=8,
        )
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # network, quota (429), timeouts...
        logger.warning("LLM unavailable, using extract: %s", exc)
        return None

    # Guard: every number in the answer must exist in the sources.
    invented = _numbers(answer) - _numbers(sources)
    if invented:
        logger.warning("LLM answer had numbers not in sources %s; using extract", invented)
        return None
    return re.sub(r"[*_#`]", "", answer) or None
