"""Recommends CeluWeb solutions for a business need.

"Necesito controlar a mis empleados" or "algo para WhatsApp" do not name a
product, so a plain text search answers poorly. Here each need points to the
solutions that cover it; their descriptions come from celuweb.com (never made up).
"""
import re

from sqlalchemy.engine import Engine

from backend.app.services.knowledge import get_index
from backend.app.services.nl_parser import normalize

# (what the visitor needs, how Osky names it, solutions that cover it, most relevant first)
NEEDS = [
    (r"whats? ?app?|guasap|wasap|wpp|wsp|chat(s|ear)?\b|mensajes? automatic",
     "atender y vender por WhatsApp", ["Chat Bot", "Link de pagos", "B2B"]),
    (r"(control\w*|seguimiento|supervis\w*|monitore\w*|gestion\w*|vigil\w*|rastre\w*|saber donde estan)\b.*\b"
     r"(emplead\w*|personal|equipo|trabajador\w*|colaborador\w*|vendedor\w*|asesor\w*|gente|tecnico\w*|mercaderista\w*)"
     r"|(emplead\w*|personal|trabajador\w*|colaborador\w*)\b.*\b(control\w*|seguimiento|ubicacion|donde estan)"
     r"|control de (emplead\w*|personal|asistencia)|productividad",
     "controlar y hacer seguimiento a tu equipo", ["Supervisores", "Mapas", "Fuerza de Ventas", "Field Service"]),
    (r"(tomar|recibir|gestionar|digitalizar|automatizar|hacer) (los )?pedidos|pedidos|preventa|vender mas|ventas en (la )?calle|ventas en campo|rutero",
     "gestionar pedidos y ventas", ["Fuerza de Ventas", "B2B", "Televenta", "Chat Bot"]),
    (r"entrega\w*|distribu\w*|despacho\w*|transport\w*|flota\w*|vehicul\w*|camion\w*|logistic\w*|domicili\w*",
     "la logística y las entregas", ["TMS", "Entregas", "Mapas"]),
    (r"cobr\w*|recaud\w*|cartera|pagos?\b|deudas?|facturas? pendientes?",
     "cobrar y gestionar la cartera", ["Link de pagos", "Chat Bot", "Televenta"]),
    (r"precios? de (la )?competencia|precios? del mercado|monitore\w* precios?|comparar precios?|variacion\w* de precios?",
     "conocer los precios del mercado", ["Pricing"]),
    (r"punto de venta|exhibicion\w*|gondola\w*|impulsador\w*|mercaderist\w*|merchandising|anaquel\w*",
     "la ejecución en punto de venta", ["Mercadeo", "Supervisores"]),
    (r"orden\w* de (trabajo|servicio)|mantenimiento\w*|instalacion\w*|servicio tecnico|tecnicos?\b|soporte en campo",
     "los servicios técnicos en campo", ["Field Service", "Mapas"]),
    (r"tendero\w*|tienda en linea|e ?commerce|comercio electronico|autogestion|clientes? (pidan|compren) solos?|portal de clientes?",
     "que tus clientes compren solos", ["B2B", "Chat Bot"]),
    (r"\bgps\b|geolocaliz\w*|ubicacion en tiempo real|mapa\w*|georreferenc\w*",
     "ver tu operación en el mapa", ["Mapas", "TMS", "Supervisores"]),
    (r"call ?center|llamadas|venta\w* telefonic\w*|televenta\w*|ventas? remot\w*",
     "vender a distancia", ["Televenta", "Chat Bot"]),
]
_NEEDS = [(re.compile(pattern), label, solutions) for pattern, label, solutions in NEEDS]

MAX_SOLUTIONS = 4
SUMMARY_CHARS = 170

def match_needs(question: str) -> tuple[list[str], list[str], list[str]]:
    """(needs found, solutions for them, the main solution of each need), in order of relevance, without repeats."""
    q = normalize(question)
    labels: list[str] = []
    solutions: list[str] = []
    for pattern, label, options in _NEEDS:
        if pattern.search(q):
            labels.append(label)
            solutions += [s for s in options if s not in solutions]
    main = [options[0] for pattern, _, options in _NEEDS if pattern.search(q)]
    return labels, solutions[:MAX_SOLUTIONS], main

def _summary(content: str, title: str) -> str:
    """First sentence of the solution's page, without repeating its name as a heading."""
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    while lines and (normalize(lines[0]) in {normalize(title), f"la solucion {normalize(title)}"} or len(lines[0]) < 25):
        lines.pop(0)
    text = " ".join(lines)
    sentence = re.split(r"(?<=[.!?])\s+", text)[0] if text else ""
    if len(sentence) > SUMMARY_CHARS:
        cut = sentence[:SUMMARY_CHARS]
        sentence = cut[: cut.rfind(",")] if "," in cut[60:] else cut.rsplit(" ", 1)[0]
        sentence = sentence.rstrip(",;: ") + "…"
    return sentence

def recommend(engine: Engine, question: str, style: str = "chat") -> dict | None:
    """Answer listing the solutions for the visitor's need, or None if no need is recognised."""
    labels, wanted, _ = match_needs(question)
    if not wanted:
        return None
    pages = {}
    for chunk in get_index(engine).chunks:
        if chunk.kind == "servicio" and chunk.title in wanted and chunk.title not in pages:
            pages[chunk.title] = chunk
    found = [s for s in wanted if s in pages]  # only solutions that are really on the website
    if not found:
        return None

    need = " y ".join(labels[:2])
    names = found[0] if len(found) == 1 else ", ".join(found[:-1]) + f" y {found[-1]}"
    details = [f"• {s}: {_summary(pages[s].content, s)}" for s in found]
    one = len(found) == 1
    intro = (f"Para {need}, en CeluWeb {'tenemos' if one else 'te pueden servir estas soluciones'}:")
    close = "¿Quieres que te cuente más o te comunico con un asesor?" if one else \
        "¿De cuál quieres que te cuente más? También te puedo comunicar con un asesor."
    if style == "voice":
        answer = (f"Para {need} te {'sirve' if one else 'sirven'} {names}. "
                  f"{'¿Te cuento cómo funciona?' if one else '¿De cuál quieres que te cuente?'}")
        more = " ".join(f"{s}: {_summary(pages[s].content, s)}" for s in found)
    else:
        answer = "\n".join([intro, *details, close])
        more = ""
    return {
        "answer": answer,
        "more": more,
        "solutions": found,
        "sources": [{"title": s, "url": pages[s].source_url, "kind": "servicio", "score": 0} for s in found],
    }
