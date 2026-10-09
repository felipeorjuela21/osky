"""Hand-off to CeluWeb's sales team over WhatsApp.

Contacts live in config/sales_contacts.json (editable, no restart needed).
Osky never makes up numbers: if there is no active contact, it says so.
"""
import itertools
import json
import re
from pathlib import Path
from urllib.parse import quote

from backend.app.services.nl_parser import normalize

CONTACTS_PATH = Path("config/sales_contacts.json")

# Solutions on celuweb.com, used to route to the right sales rep and to
# personalise the WhatsApp message.
SOLUTIONS = {
    "TMS": ["tms"],
    "Pricing": ["pricing"],
    "Chat Bot": ["chat bot", "chatbot", "bot"],
    "B2B": ["b2b"],
    "Field Service": ["field service"],
    "Televenta": ["televenta"],
    "Supervisores": ["supervisores", "supervisor"],
    "Link de pagos": ["link de pagos", "pagos", "recaudo"],
    "Mapas": ["mapas", "mapa"],
    "Mercadeo": ["mercadeo"],
    "Fuerza de Ventas": ["fuerza de ventas", "fuerza de venta"],
    "Entregas": ["entregas"],
}

# Wanting a person, a quote or prices -> sales. "Fuerza de Ventas" is a product,
# not a request to talk to sales, so it is removed before matching.
SALES_INTENT = re.compile(
    r"\b(asesor\w*|comercial(es)?|vendedor\w*|ventas|cotiz\w*|precio\w*|costo\w*|tarifa\w*|"
    r"cuanto (cuesta|vale|cobran)|demo|demostracion|contratar\w*|adquirir|comprar|"
    r"hablar con (alguien|una persona|un humano|un asesor|ventas)|atencion personalizada|"
    r"me (pueden|puedes) (llamar|contactar|escribir))\b"
)

_cache: dict = {"mtime": None, "data": None}
_rotation: dict[str, itertools.cycle] = {}

def _load() -> dict:
    mtime = CONTACTS_PATH.stat().st_mtime if CONTACTS_PATH.exists() else None
    if _cache["mtime"] != mtime:
        try:
            data = json.loads(CONTACTS_PATH.read_text(encoding="utf-8")) if mtime else {}
        except (OSError, ValueError):
            data = {}
        _cache.update(mtime=mtime, data=data)
        _rotation.clear()
    return _cache["data"] or {}

def active_contacts() -> list[dict]:
    contacts = _load().get("contacts", [])
    return [c for c in contacts if c.get("active", True) and re.fullmatch(r"\d{10,15}", str(c.get("phone", "")))]

# Clear buying signals always mean "connect me with sales".
STRONG_INTENT = re.compile(r"\b(asesor\w*|cotiz\w*|cuanto (cuesta|vale|cobran)|contratar\w*|comprar|demo|hablar con)\b")
# "¿Qué es / cómo funciona Pricing?" is a product question even if it mentions prices.
INFO_QUESTION = re.compile(r"\b(que es|para que|como funciona|que hace|cuentame|explica\w*|que ofrece)\b")

def is_sales_request(question: str) -> bool:
    q = normalize(question).replace("fuerza de ventas", "").replace("fuerza de venta", "")
    if not SALES_INTENT.search(q):
        return False
    if STRONG_INTENT.search(q):
        return True
    return not (detect_solution(question) and INFO_QUESTION.search(q))

def detect_solution(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        q = normalize(text)
        for name, words in SOLUTIONS.items():
            if any(re.search(rf"\b{re.escape(w)}\b", q) for w in words):
                return name
    return None

def _pick(solution: str | None) -> dict | None:
    contacts = active_contacts()
    # "fallback" contacts (the general line) are only used when no advisor is active.
    advisors = [c for c in contacts if not c.get("fallback")]
    contacts = advisors or contacts
    if not contacts:
        return None
    specialists = [c for c in contacts if solution and solution in c.get("solutions", [])]
    generalists = [c for c in contacts if not c.get("solutions")]
    pool = specialists or generalists or contacts
    key = "|".join(c["phone"] for c in pool)
    if key not in _rotation:
        _rotation[key] = itertools.cycle(pool)  # spread conversations across the team
    return next(_rotation[key])

def whatsapp_action(solution: str | None = None) -> dict | None:
    contact = _pick(solution)
    if not contact:
        return None
    interest = f"Me interesa conocer más sobre {solution}." if solution else "Quiero hablar con un asesor comercial."
    template = _load().get("message") or "Hola, vengo de Osky, el asistente virtual de CeluWeb. {interes}"
    text = template.replace("{interes}", interest)
    label = f"Hablar con {contact['name']}" + (f" sobre {solution}" if solution else "")
    return {
        "type": "whatsapp",
        "label": label,
        "url": f"https://wa.me/{contact['phone']}?text={quote(text)}",
        "contact": contact["name"],
        "area": contact.get("area", ""),
    }
