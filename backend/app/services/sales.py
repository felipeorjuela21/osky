"""Hand-off to CeluWeb's sales team over WhatsApp.

Contacts live in config/sales_contacts.json (editable, no restart needed).
Osky never makes up numbers: if there is no active contact, it says so.
"""
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

def _load() -> dict:
    mtime = CONTACTS_PATH.stat().st_mtime if CONTACTS_PATH.exists() else None
    if _cache["mtime"] != mtime:
        try:
            data = json.loads(CONTACTS_PATH.read_text(encoding="utf-8")) if mtime else {}
        except (OSError, ValueError):
            data = {}
        _cache.update(mtime=mtime, data=data)
        _turn.clear()
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

def detect_solutions(*texts: str | None) -> list[str]:
    """Every solution mentioned, in order of appearance across the texts."""
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        q = normalize(text)
        hits = []
        for name, words in SOLUTIONS.items():
            positions = [m.start() for w in words for m in re.finditer(rf"\b{re.escape(w)}\b", q)]
            if positions and name not in found:
                hits.append((min(positions), name))
        found += [name for _, name in sorted(hits)]
    return found

def detect_solution(*texts: str | None) -> str | None:
    found = detect_solutions(*texts)
    return found[0] if found else None

MAX_ADVISORS = 3
_turn: dict[str, int] = {}

def _rotate(group: list[dict], turn: int) -> list[dict]:
    return group[turn % len(group):] + group[: turn % len(group)] if group else group

def _advisors(solutions: list[str]) -> list[dict]:
    """Up to 3 advisors: specialists in what the visitor wants first, then the rest.
    The order rotates so new conversations are spread across the team."""
    contacts = active_contacts()
    # "fallback" contacts (the general line) are only used when no advisor is active.
    advisors = [c for c in contacts if not c.get("fallback")] or contacts
    if not advisors:
        return []
    specialists = [c for c in advisors if set(solutions) & set(c.get("solutions", []))]
    others = [c for c in advisors if c not in specialists]
    key = "|".join(c["phone"] for c in advisors)
    turn = _turn.get(key, 0)
    _turn[key] = turn + 1
    return (_rotate(specialists, turn) + _rotate(others, turn))[:MAX_ADVISORS]

def whatsapp_message(solutions: list[str], name: str | None = None, questions: list[str] | None = None) -> str:
    """Message the visitor sends, with what they talked about with Osky."""
    lines = [f"Hola{', soy ' + name if name else ''}. Vengo de Osky, el asistente virtual de CeluWeb."]
    lines.append(f"Me interesa: {', '.join(solutions)}." if solutions else "Quiero hablar con un asesor comercial.")
    asked = [q.strip()[:120] for q in (questions or []) if q.strip()][-3:]
    if asked:
        lines.append("Le pregunté a Osky: " + " / ".join(f"“{q}”" for q in asked))
    return "\n".join(lines)

def whatsapp_action(solution: str | list[str] | None = None, name: str | None = None,
                    questions: list[str] | None = None) -> dict | None:
    """WhatsApp button: opens a picker with up to 3 advisors; each link carries the conversation context."""
    from backend.app.services.needs import match_needs

    solutions = [solution] if isinstance(solution, str) else list(solution or [])
    # Plus what the visitor asked about: products by name, and the main one for each need ("control de empleados").
    mentioned = detect_solutions(*(questions or []))
    for question in questions or []:
        mentioned += match_needs(question)[2]
    for s in mentioned:
        if s not in solutions:
            solutions.append(s)
    solutions = solutions[:4]
    advisors = _advisors(solutions)
    if not advisors:
        return None
    text = quote(whatsapp_message(solutions, name, questions))
    options = [
        {
            "name": c["name"],
            "area": c.get("area", ""),
            "photo": c.get("photo", ""),
            "solutions": c.get("solutions", []),
            "url": f"https://wa.me/{c['phone']}?text={text}",
        }
        for c in advisors
    ]
    first = options[0]
    about = f" sobre {solutions[0]}" if solutions else ""
    label = f"Hablar con un asesor{about}" if len(options) > 1 else f"Hablar con {first['name']}{about}"
    return {
        "type": "whatsapp",
        "label": label,
        "url": first["url"],
        "contact": first["name"],
        "area": first["area"],
        "advisors": options,
    }
