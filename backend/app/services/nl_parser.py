"""Rule based Spanish question -> Query AST parser.

No generative AI here: the parser only maps words to datasets, fields and
values that exist in the Data Dictionary or in the database itself. If it
cannot build a valid query it raises NotUnderstood instead of guessing.
"""
import calendar
import re
import unicodedata
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.app.core.data_dictionary import DATA_DICTIONARY
from backend.app.core.db import TABLES
from backend.app.services.query_engine import Filter, QueryAST

class NotUnderstood(ValueError):
    pass

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTH_NAMES = {v: k for k, v in MONTHS.items() if k != "setiembre"}

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None

def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase != "" and re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None

KnownValues = dict[tuple[str, str], list[str]]

def load_known_values(engine: Engine) -> KnownValues:
    """Distinct values of fields flagged with match_values, plus customer names/ids."""
    known: KnownValues = {}
    with engine.connect() as conn:
        for dataset, spec in DATA_DICTIONARY.items():
            for field, fspec in spec["fields"].items():
                if fspec.get("match_values"):
                    column = TABLES[dataset].c[field]
                    values = conn.execute(select(column).distinct().where(column.is_not(None))).scalars()
                    known[(dataset, field)] = [str(v) for v in values]
        customers = TABLES["customers"]
        known[("customers", "_name_to_id")] = [
            f"{r.name}\x00{r.id}" for r in conn.execute(select(customers.c.name, customers.c.id))
        ]
    return known

def _detect_operation(q: str) -> str | None:
    if _has(r"\b(promedio|media|en promedio|promedia\w*)\b", q):
        return "avg"
    if _has(r"\b(maxim\w*|mayor|mas alta|mas grande|mas cara)\b", q):
        return "max"
    if _has(r"\b(minim\w*|menor|mas baja|mas pequena|mas barata)\b", q):
        return "min"
    if _has(r"\b(cuant[oa]s|numero de|cantidad de|cuenta\w*|contar)\b", q):
        return "count"
    if _has(r"\b(cuant[oa]|total\w*|suma\w*|sumar|monto|factur\w*|ingres\w*)\b", q):
        return "sum"
    if _has(r"\b(lista\w*|listar|muestra\w*|mostrar|cuales|quien\w*|dame|ver|hay)\b", q):
        return "list"
    return None

def _detect_dataset(q: str, operation: str | None) -> str | None:
    if operation in {"sum", "avg", "max", "min"}:
        return "sales"
    if _has(r"\b(vent\w*|vend\w*|factur\w*|ingres\w*)\b", q):
        return "sales"
    if _has(r"\b(client\w*|empresas?)\b", q):
        return "customers"
    return None

def _match_values(q: str, dataset: str, known: KnownValues) -> list[Filter]:
    filters: list[Filter] = []
    spec = DATA_DICTIONARY[dataset]
    for field, fspec in spec["fields"].items():
        for canonical, words in fspec.get("value_synonyms", {}).items():
            if any(_contains_phrase(q, w) for w in words):
                label = fspec.get("value_labels", {}).get(canonical, canonical)
                filters.append(Filter(field=field, value=canonical, label=f"con {fspec['label']} {label}"))
                break
        if fspec.get("match_values"):
            # Longest values first so "Empresa AB" wins over "Empresa A".
            values = sorted(known.get((dataset, field), []), key=len, reverse=True)
            for value in values:
                if _contains_phrase(q, normalize(value)):
                    prefix = {"city": "en", "seller": "de"}.get(field, f"con {fspec['label']}")
                    filters.append(Filter(field=field, value=value, label=f"{prefix} {value}"))
                    break

    if dataset == "sales":
        pairs = [p.split("\x00") for p in known.get(("customers", "_name_to_id"), [])]
        for name, customer_id in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
            if _contains_phrase(q, normalize(name)):
                filters.append(Filter(field="customer_id", value=customer_id, label=f"del cliente {name}"))
                break
    return filters

def _date_filters(q: str, today: date) -> list[Filter]:
    def day(d: date, label: str) -> list[Filter]:
        return [Filter(field="sale_date", value=d.isoformat(), label=label)]

    def month_range(year: int, month: int, label: str) -> list[Filter]:
        start = date(year, month, 1)
        end = start + timedelta(days=calendar.monthrange(year, month)[1])
        return [
            Filter(field="sale_date", operator="gte", value=start.isoformat(), label=label),
            Filter(field="sale_date", operator="lt", value=end.isoformat(), label=label),
        ]

    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", q)
    if iso:
        return day(date.fromisoformat(iso.group(1)), f"del {iso.group(1)}")
    if _has(r"\bhoy\b", q):
        return day(today, "de hoy")
    if _has(r"\bayer\b", q):
        return day(today - timedelta(days=1), "de ayer")
    if _has(r"\beste mes\b", q):
        return month_range(today.year, today.month, "de este mes")
    if _has(r"\bmes pasado\b", q):
        prev = today.replace(day=1) - timedelta(days=1)
        return month_range(prev.year, prev.month, "del mes pasado")

    month_match = re.search(r"\b(" + "|".join(MONTHS) + r")\b(?:\s+(?:de|del)?\s*(\d{4}))?", q)
    if month_match:
        month = MONTHS[month_match.group(1)]
        year = int(month_match.group(2)) if month_match.group(2) else today.year
        return month_range(year, month, f"en {MONTH_NAMES[month]} de {year}")

    year_match = re.search(r"\b(20\d{2})\b", q)
    if year_match:
        year = int(year_match.group(1))
        return [
            Filter(field="sale_date", operator="gte", value=f"{year}-01-01", label=f"en {year}"),
            Filter(field="sale_date", operator="lt", value=f"{year + 1}-01-01", label=f"en {year}"),
        ]
    return []

def _detect_group_by(q: str, dataset: str) -> str | None:
    match = re.search(r"\bpor (\w+)", q)
    if not match:
        return None
    word = match.group(1)
    for field, fspec in DATA_DICTIONARY[dataset]["fields"].items():
        if word in fspec.get("group_words", []):
            return field
    return None

def parse_question(question: str, known: KnownValues, today: date | None = None) -> QueryAST:
    today = today or date.today()
    q = normalize(question)
    if not q:
        raise NotUnderstood("Pregunta vacía")

    # "¿Quién vendió más?" / "mejor vendedor" -> ranking of sellers.
    if _has(r"\b(quien\w* (vendio|ha vendido|vende) mas|mejor\w* vendedor\w*)\b", q):
        return QueryAST(
            dataset="sales", operation="sum", field="amount", group_by="seller",
            filters=_date_filters(q, today), limit=1,
        )

    operation = _detect_operation(q)
    filters_by_dataset = {ds: _match_values(q, ds, known) for ds in DATA_DICTIONARY}
    dataset = _detect_dataset(q, operation)
    if dataset is None:
        # Fall back to the dataset whose values were mentioned (e.g. a seller name).
        matched = [ds for ds, fs in filters_by_dataset.items() if fs]
        if len(matched) == 1:
            dataset = matched[0]
    if dataset is None:
        raise NotUnderstood("No identifiqué si la pregunta es sobre clientes o ventas")

    if operation is None:
        operation = "count"
    if operation not in DATA_DICTIONARY[dataset]["operations"]:
        raise NotUnderstood(f"La operación no aplica para {DATA_DICTIONARY[dataset]['label'][1]}")

    # Never silently drop a condition the user asked for: if it belongs to another
    # dataset (e.g. "ventas en Bogotá" needs a join) say so instead of answering.
    for other, other_filters in filters_by_dataset.items():
        if other == dataset:
            continue
        ignored = [f for f in other_filters if not (dataset == "sales" and f.field == "name")]
        if ignored:
            labels = ", ".join(f.label or f.field for f in ignored)
            raise NotUnderstood(
                f"todavía no puedo cruzar {DATA_DICTIONARY[dataset]['label'][1]} con el filtro '{labels}'"
            )

    filters = list(filters_by_dataset[dataset])
    if dataset == "sales":
        filters += _date_filters(q, today)

    field = DATA_DICTIONARY[dataset].get("default_measure") if operation in {"sum", "avg", "min", "max"} else None
    group_by = _detect_group_by(q, dataset) if operation != "list" else None
    return QueryAST(dataset=dataset, operation=operation, field=field, filters=filters, group_by=group_by)
