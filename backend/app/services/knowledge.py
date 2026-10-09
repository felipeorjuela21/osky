"""Retrieval over the company website content (knowledge_chunks).

Answers are extracts of the stored text, never generated, and always carry
their source URL. If nothing relevant is found the agent says so.
"""
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from backend.app.core.db import knowledge_chunks
from backend.app.services.nl_parser import normalize

STOPWORDS = set(
    """a al algo algun alguna algunas alguno algunos ante antes asi aun cada como con contra cual cuales cuando
    de del desde donde dos e el ella ellas ellos en entre era es esa esas ese eso esos esta estan estas este esto
    estos fue fueron ha hace hacen han hasta hay la las le les lo los mas me mi mis mucho muy nada ni no nos nosotros
    o os otra otro para pero poco por porque puede pueden puedo que quien se segun ser si sin sobre son su sus tambien
    tan te tiene tienen todo todos tu tus un una unas uno unos usted ustedes y ya yo
    que cual cuales cuanto cuanta cuantos cuantas como para sirve hacen
    oski dime dame cuentame explicame quiero saber informacion favor hola ofrece ofrecen tienes""".split()
)

# Expands everyday words to the vocabulary the website uses.
SYNONYMS = {
    "celuweb": ["somos"],
    "mision": ["mision", "mison"],
    "vision": ["vision", "vison"],
    "telefono": ["mesa", "ayuda", "57", "contacto"],
    "celular": ["mesa", "ayuda", "57", "contacto"],
    "llamar": ["mesa", "ayuda", "57", "contacto"],
    "contactar": ["contacto", "email", "mesa", "ayuda"],
    "correo": ["email", "contacto"],
    "email": ["contacto"],
    "direccion": ["direccion", "armenia"],
    "ubicado": ["direccion", "armenia"],
    "ubicada": ["direccion", "armenia"],
    "oficina": ["direccion", "armenia"],
    "servicio": ["solucion"],
    "producto": ["solucion"],
    "precio": ["pricing"],
    "whatsapp": ["chat", "bot"],
    "transporte": ["tms"],
    "logistica": ["tms"],
    "pago": ["link", "recaudo"],
    "cobro": ["link", "recaudo"],
    "tendero": ["b2b"],
    "pedido": ["b2b", "televenta"],
    "tecnico": ["field", "service"],
    "vendedor": ["fuerza", "venta"],
    "mercaderista": ["mercadeo"],
    "gps": ["mapa"],
    "ruta": ["mapa", "tms"],
    "privacidad": ["dato", "personal", "politica"],
}

# Everyday words visitors use that may not appear on the website, so typos in them get fixed too.
EXTRA_VOCABULARY = set(
    """asesor asesores comercial comerciales cotizar cotizacion precio precios costo cuesta contratar comprar demo
    whatsapp chatbot empleados empleado trabajadores colaboradores personal equipo vendedores controlar control
    seguimiento supervisar monitorear pedidos entregas distribucion transporte vehiculos camiones logistica
    cobrar cobros recaudo cartera pagos competencia mercado tenderos tienda clientes tecnicos mantenimiento
    ubicacion necesito necesitamos quiero queremos busco buscamos empresa soluciones solucion servicios
    contacto telefono correo direccion mision vision interesa interesado informacion conocer tienen ofrecen
    funciona sirve ayuda ayudar celuweb""".split()
)

MIN_SCORE = 1.5
# Official pages outrank blog posts when both mention the same thing.
KIND_WEIGHT = {"dato": 1.5, "documento": 1.3, "servicio": 1.3, "contacto": 1.3, "empresa": 1.2, "politica": 1.0, "articulo": 0.8}

# Official facts provided by CeluWeb that are not on the website (editable, no restart needed).
FACTS_PATH = Path("config/company_facts.json")
FACT_SOURCE = "Dato oficial de CeluWeb"

# Company documents dropped in this folder (PDF, Word .docx, .txt, .md) become sources.
DOCS_DIR = Path("conocimiento")
DOC_TYPES = {".pdf", ".docx", ".txt", ".md"}
DOC_CHUNK_CHARS = 700
MAX_ANSWER_CHARS = 420

def stem(word: str) -> str:
    if word.endswith("ciones"):
        return word[:-6] + "cion"
    if word.endswith("es") and len(word) > 5 and word[-3] in "lrnd":
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word

def typo_distance(a: str, b: str, limit: int) -> int:
    """Edits (insert, delete, change, swap two letters) to turn a into b; stops early past limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], prev2[j - 2] + 1)
        if min(row) > limit:
            return limit + 1
        prev2, prev = prev, row
    return prev[-1]

def tokenize(text: str) -> list[str]:
    return [stem(w) for w in normalize(text).split() if w not in STOPWORDS and len(w) > 1]

def expand(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    for t in tokens:
        expanded += SYNONYMS.get(t, [])
    return expanded

@dataclass
class Chunk:
    id: int
    title: str
    kind: str
    source_url: str
    content: str
    keywords: str = ""  # searchable but never spoken

class KnowledgeIndex:
    """BM25 index held in memory; rebuilt when the table changes."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.docs = [Counter(tokenize(c.title) * 3 + tokenize(c.content) + tokenize(c.keywords) * 2) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if chunks else 0
        df = Counter(t for d in self.docs for t in d)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        # Words the agent knows, to fix typos ("presios" -> "precios", "pricin" -> "pricing").
        self.frequency = Counter(w for c in chunks for w in normalize(f"{c.title} {c.content} {c.keywords}").split())
        self.vocabulary = {w for w in set(self.frequency) | EXTRA_VOCABULARY | STOPWORDS if w.isalpha()}
        self._by_length: dict[int, list[str]] = {}
        for w in self.vocabulary:
            self._by_length.setdefault(len(w), []).append(w)
        self._fixes: dict[str, str] = {}

    def correct(self, text: str) -> str:
        """Fuzzy spelling: each unknown word becomes the closest known one, if it is 1-2 typos away."""
        fixed = []
        for word in normalize(text).split():
            if len(word) < 5 or word in self.vocabulary or not word.isalpha():
                fixed.append(word)
                continue
            if word not in self._fixes:
                limit = 1 if len(word) < 7 else 2
                best: tuple | None = None
                for size in range(len(word) - limit, len(word) + limit + 1):
                    for candidate in self._by_length.get(size, []):
                        d = typo_distance(word, candidate, limit)
                        if d <= limit:
                            # Fewer typos first; then words visitors use; then the most common on the site.
                            rank = (d, candidate not in EXTRA_VOCABULARY, -self.frequency[candidate])
                            if best is None or rank < best[0]:
                                best = (rank, candidate)
                self._fixes[word] = best[1] if best else word
            fixed.append(self._fixes[word])
        return " ".join(fixed)

    def search(self, question: str, k: int = 3) -> list[tuple[float, Chunk]]:
        terms = expand(tokenize(question))
        scored = []
        for chunk, doc, length in zip(self.chunks, self.docs, self.lengths):
            score = 0.0
            for t in set(terms):
                tf = doc.get(t, 0)
                if tf:
                    score += self.idf[t] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / self.avg_len))
            if score > 0:
                scored.append((score * KIND_WEIGHT.get(chunk.kind, 1.0), chunk))
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:k]

_cache: dict = {"key": None, "index": None}

def load_facts() -> list[Chunk]:
    try:
        data = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        Chunk(-(i + 1), f.get("title", FACT_SOURCE), "dato", "", f["content"], " ".join(f.get("keywords", [])))
        for i, f in enumerate(data.get("facts", []))
        if f.get("content")
    ]

def _document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        import zipfile
        from xml.etree import ElementTree

        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(path) as docx:
            root = ElementTree.fromstring(docx.read("word/document.xml"))
        return "\n".join("".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p"))
    return ""

def _split(text: str) -> list[str]:
    parts, current = [], ""
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n|\n", text)):
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) > DOC_CHUNK_CHARS:
            parts.append(current)
            current = ""
        current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    return parts

def _docs_signature() -> tuple:
    if not DOCS_DIR.exists():
        return ()
    return tuple(sorted((f.name, f.stat().st_mtime) for f in DOCS_DIR.rglob("*") if f.suffix.lower() in DOC_TYPES))

def load_documents() -> list[Chunk]:
    chunks: list[Chunk] = []
    if not DOCS_DIR.exists():
        return chunks
    for path in sorted(DOCS_DIR.rglob("*")):
        if path.suffix.lower() not in DOC_TYPES or path.name.lower().startswith("leeme"):
            continue
        try:
            text = _document_text(path)
        except Exception:  # unreadable file: skip it, keep the rest
            continue
        title = re.sub(r"[_-]+", " ", path.stem).strip()
        for part in _split(text):
            chunks.append(Chunk(-(100000 + len(chunks)), title, "documento", "", part))
    return chunks

def get_index(engine: Engine) -> KnowledgeIndex:
    facts_mtime = FACTS_PATH.stat().st_mtime if FACTS_PATH.exists() else 0
    with engine.connect() as conn:
        key = (*conn.execute(select(func.count(), func.max(knowledge_chunks.c.id))).one(), facts_mtime, _docs_signature())
        if _cache["key"] != key:
            rows = conn.execute(select(knowledge_chunks)).all()
            chunks = [Chunk(r.id, r.title, r.kind, r.source_url, r.content) for r in rows]
            _cache.update(key=key, index=KnowledgeIndex(chunks + load_facts() + load_documents()))
    return _cache["index"]

def _is_short(line: str) -> bool:
    return len(line) <= 60 and not line.rstrip().endswith((".", ":", ";", "?", "!"))

def join_for_speech(lines: list[str]) -> str:
    """Joins page lines so they read naturally aloud without changing words:
    'Misión' + paragraph -> 'Misión: ...'; bullet lines -> 'a, b, c.'"""
    # A short line followed by a lowercase continuation is a sentence fragment, not a bullet.
    short_flags = [
        _is_short(line) and not (i + 1 < len(lines) and lines[i + 1][:1].islower())
        for i, line in enumerate(lines)
    ]
    text = ""
    for i, line in enumerate(lines):
        if i == 0:
            text = line
            continue
        prev_short, short = short_flags[i - 1], short_flags[i]
        if line[:1].islower():
            sep = " "  # same sentence split by inline formatting on the page
        elif prev_short and short:
            sep = ", "
        elif prev_short:
            sep = ": " if i == 1 else ". "
        else:
            sep = " "
        text += sep + line
    if lines and _is_short(lines[-1]):
        text += "."
    return text

def best_extract(question: str, content: str) -> str:
    """Returns the most relevant consecutive lines of a chunk (words unchanged)."""
    terms = set(expand(tokenize(question)))
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if not lines:
        return ""
    scores = [len(terms & set(tokenize(l))) for l in lines]
    start = max(range(len(lines)), key=lambda i: scores[i])
    # Short headings ("Misión", "TMS") read better together with what follows.
    if start > 0 and not _is_short(lines[start]) and _is_short(lines[start - 1]):
        start -= 1
    selected: list[str] = []
    for line in lines[start:]:
        if selected and len(" ".join(selected)) + len(line) > MAX_ANSWER_CHARS:
            break
        selected.append(line)
    extract = join_for_speech(selected)
    if len(extract) > MAX_ANSWER_CHARS + 60:
        cut = extract[:MAX_ANSWER_CHARS]
        extract = cut[: cut.rfind(".") + 1] or cut.rsplit(" ", 1)[0] + "…"
    return extract

VOICE_CHARS = 210

def split_for_voice(text: str) -> tuple[str, str]:
    """Spoken answers keep the essentials (first sentences); the rest is offered on request."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    short: list[str] = []
    for sentence in sentences:
        if short and len(" ".join(short)) + len(sentence) > VOICE_CHARS:
            break
        short.append(sentence)
    return " ".join(short), " ".join(sentences[len(short):])

def answer_from_knowledge(engine: Engine, question: str) -> dict | None:
    index = get_index(engine)
    results = [r for r in index.search(question) if r[0] >= MIN_SCORE]
    if not results:
        return None
    score, top = results[0]
    extract = best_extract(question, top.content)
    # Name the service when the extract doesn't ("TMS: Es una solución...").
    lead = f"{top.title}: " if top.kind == "servicio" and normalize(top.title) not in normalize(extract) else ""
    return {
        "answer": f"{lead}{extract}",
        "sources": [
            {"title": c.title, "url": c.source_url, "kind": c.kind, "score": round(s, 2)} for s, c in results
        ],
        # Full text of the best matches, for the natural-answer writer (llm.py).
        "context": [{"title": c.title, "content": c.content[:1500]} for _, c in results[:3]],
    }

def knowledge_stats(engine: Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            select(knowledge_chunks.c.kind, func.count(), func.count(func.distinct(knowledge_chunks.c.source_url)))
            .group_by(knowledge_chunks.c.kind)
        ).all()
        last = conn.execute(select(func.max(knowledge_chunks.c.fetched_at))).scalar_one()
    return {
        "by_kind": {kind: {"chunks": chunks, "sources": sources} for kind, chunks, sources in rows},
        "last_ingest": last.isoformat() if last else None,
    }
