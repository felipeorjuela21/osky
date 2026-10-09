"""Turns a query result into a Spanish sentence. Only uses values from the result."""
from backend.app.core.data_dictionary import DATA_DICTIONARY
from backend.app.services.query_engine import QueryAST

def format_number(value, currency: bool = False) -> str:
    if value is None:
        return "sin dato"
    number = float(value)
    text = f"{number:,.0f}" if number == int(number) or currency else f"{number:,.2f}"
    text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"${text}" if currency else text

def describe_filters(ast: QueryAST) -> str:
    labels: list[str] = []
    for f in ast.filters:
        label = f.label or f"con {f.field} {f.value}"
        if label not in labels:
            labels.append(label)
    return (" " + ", ".join(labels)) if labels else ""

def _is_currency(ast: QueryAST) -> bool:
    if ast.operation == "count" or not ast.field:
        return False
    return bool(DATA_DICTIONARY[ast.dataset]["fields"][ast.field].get("currency"))

def _describe_row(dataset: str, row: dict) -> str:
    if dataset == "customers":
        return f"{row.get('name')} ({row.get('city')})"
    if dataset == "sales":
        return f"{row.get('id')} de {row.get('seller')} por {format_number(row.get('amount'), True)} el {row.get('sale_date')}"
    return ", ".join(str(v) for v in row.values())

def build_answer(ast: QueryAST, result: dict) -> str:
    singular, plural = DATA_DICTIONARY[ast.dataset]["label"]
    where = describe_filters(ast)
    currency = _is_currency(ast)

    if "rows" in result:
        rows = result["rows"]
        if not rows:
            return f"No encontré {plural}{where}."
        shown = rows[:10]
        items = "; ".join(_describe_row(ast.dataset, r) for r in shown)
        extra = f" y {len(rows) - len(shown)} más" if len(rows) > len(shown) else ""
        noun = singular if len(rows) == 1 else plural
        return f"Encontré {len(rows)} {noun}{where}: {items}{extra}."

    if "groups" in result:
        groups = result["groups"]
        if not groups:
            return f"No encontré {plural}{where}."
        group_label = DATA_DICTIONARY[ast.dataset]["fields"][ast.group_by]["label"]
        if ast.limit == 1:
            top = groups[0]
            return f"{top['key']} es el {group_label} con más {plural}{where}: {format_number(top['value'], currency)}."
        parts = "; ".join(f"{g['key']}: {format_number(g['value'], currency)}" for g in groups)
        metric = {"count": "Cantidad de", "sum": "Total de", "avg": "Promedio de", "max": "Máximo de", "min": "Mínimo de"}[ast.operation]
        return f"{metric} {plural} por {group_label}{where}. {parts}."

    value = result.get("value")
    if ast.operation == "count":
        if not value:
            return f"No encontré {plural}{where}."
        noun = singular if value == 1 else plural
        return f"Hay {value} {noun}{where}."
    if value is None:
        return f"No encontré {plural}{where}, así que no tengo un valor para reportar."
    templates = {
        "sum": "El total de {plural}{where} es {value}.",
        "avg": "El promedio por {singular}{where} es {value}.",
        "max": "La {singular} más alta{where} es de {value}.",
        "min": "La {singular} más baja{where} es de {value}.",
    }
    return templates[ast.operation].format(
        plural=plural, singular=singular, where=where, value=format_number(value, currency)
    )
