"""Scripted conversational turns (greetings, thanks, goodbye...).

These replies are about Osky itself, never about company data, so they are
fixed texts. Anything substantive still goes to the company sources.
"""
import random
import re

from backend.app.core.config import settings
from backend.app.services.nl_parser import normalize

GREETING = r"(hola|holi|buenas|buenos dias|buenas tardes|buenas noches|hey|que mas|quiubo|saludos)"
# A greeting at the start of a real question ("hola, ¿qué es TMS?") is stripped.
LEADING_GREETING = re.compile(rf"^{GREETING}( osk[iy])?\b\s*")

def _replies() -> dict[str, list[str]]:
    name, company = settings.agent_name, settings.company_name
    return {
        "greeting": [
            f"¡Hola! Qué gusto saludarte. ¿Qué te gustaría saber de {company}?",
            f"¡Hola! Aquí estoy. Pregúntame lo que quieras sobre las soluciones de {company}.",
        ],
        "how_are_you": [
            f"¡Muy bien, gracias por preguntar! Listo para contarte sobre {company}. ¿Qué quieres saber?",
        ],
        "identity": [
            f"Soy {name}, el asistente virtual de {company}. Respondo con la información oficial de la empresa: "
            "sus soluciones, quiénes somos y cómo contactarnos.",
        ],
        "creator": [
            f"Me creó el equipo de desarrollo de {company}, con Juan Felipe Orjuela.",
        ],
        "help": [
            f"Puedo contarte sobre las soluciones de {company}, como TMS, Pricing, Chat Bot o Fuerza de Ventas, "
            "sobre nuestra misión y visión, o darte los datos de contacto. ¿Por dónde empezamos?",
        ],
        "thanks": [
            "¡Con gusto! ¿Quieres saber algo más?",
            "¡A ti! Si tienes otra pregunta, aquí estoy.",
        ],
        "goodbye": [
            "¡Fue un gusto hablar contigo! Hasta pronto.",
            f"¡Hasta luego! Cuando quieras, aquí estaré para hablar de {company}.",
        ],
    }

PATTERNS = [
    ("goodbye", r"^(adios|chao|chau|hasta luego|hasta pronto|nos vemos|bye|eso es todo|eso seria todo|terminar|salir)\b"),
    ("thanks", r"^(muchas gracias|mil gracias|gracias|perfecto|listo|vale|ok|okey|genial|excelente|muy bien)( gracias)?( osk[iy])?$"),
    ("how_are_you", r"^(como estas|como vas|como te va|que tal|como andas)( osk[iy])?$"),
    ("identity", r"^(quien eres|que eres|como te llamas|cual es tu nombre|tu quien eres|presentate)( osk[iy])?$"),
    ("creator", r"\bquien(es)? te (creo|crearon|hizo|hicieron|desarrollo|desarrollaron|programo|programaron|diseno|disenaron)\b"
                r"|\btu(s)? (creador|creadores|desarrollador|desarrolladores|programador|programadores)\b"),
    ("help", r"^(que puedes hacer|en que me (puedes )?ayudar|que sabes|ayuda|que te puedo preguntar|que me puedes decir)( osk[iy])?$"),
    ("greeting", rf"^{GREETING}( osk[iy])?$"),
]

def strip_greeting(question: str) -> str:
    """'Hola Osky, ¿qué es TMS?' -> 'qué es TMS?' (keeps the original text otherwise)."""
    q = normalize(question)
    match = LEADING_GREETING.match(q)
    if match and q[match.end():].strip():
        words_to_drop = len(match.group(0).split())
        return " ".join(question.split()[words_to_drop:]).lstrip(",.¡! ")
    return question

def match_smalltalk(question: str) -> dict | None:
    q = normalize(question)
    for intent, pattern in PATTERNS:
        if re.search(pattern, q):
            return {"intent": intent, "answer": random.choice(_replies()[intent])}
    return None
