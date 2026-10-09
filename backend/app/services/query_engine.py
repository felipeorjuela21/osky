"""Controlled query engine.

Queries arrive as a structured Query AST, are validated against the Data
Dictionary and are translated to SQL with SQLAlchemy Core (never string SQL).
"""
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import desc, func, insert, select
from sqlalchemy.engine import Engine

from backend.app.core.data_dictionary import DATA_DICTIONARY, NUMERIC_TYPES
from backend.app.core.db import TABLES, query_log

SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Kept for backwards compatibility; the Data Dictionary is the source.
ALLOWED_DATASETS = {name: set(spec["fields"]) for name, spec in DATA_DICTIONARY.items()}

Operation = Literal["count", "sum", "avg", "min", "max", "list"]
Operator = Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains"]

class Filter(BaseModel):
    field: str
    operator: Operator = "eq"
    value: str | int | float
    label: str | None = Field(default=None, description="Human readable description, not used for execution")

class QueryAST(BaseModel):
    dataset: str
    operation: Operation
    field: str | None = None
    filters: list[Filter] = Field(default_factory=list)
    group_by: str | None = None
    limit: int = Field(default=50, ge=1, le=500)

def validate_identifier(value: str) -> str:
    if not SAFE_IDENTIFIER.match(value):
        raise ValueError(f"Invalid identifier: {value}")
    return value

def validate_dataset(dataset: str) -> None:
    if dataset not in ALLOWED_DATASETS:
        raise ValueError(f"Dataset not allowed: {dataset}")

def validate_field(dataset: str, field: str) -> None:
    validate_dataset(dataset)
    if field not in ALLOWED_DATASETS[dataset]:
        raise ValueError(f"Field '{field}' is not allowed for dataset '{dataset}'")

def field_spec(dataset: str, field: str) -> dict:
    return DATA_DICTIONARY[dataset]["fields"][field]

def validate_query(ast: QueryAST) -> None:
    validate_dataset(ast.dataset)
    spec = DATA_DICTIONARY[ast.dataset]
    if ast.operation not in spec["operations"]:
        raise ValueError(f"Operation '{ast.operation}' is not allowed for dataset '{ast.dataset}'")
    if ast.operation in {"sum", "avg", "min", "max"}:
        if not ast.field:
            raise ValueError(f"Operation '{ast.operation}' requires a field")
        validate_field(ast.dataset, ast.field)
        if field_spec(ast.dataset, ast.field)["type"] not in NUMERIC_TYPES:
            raise ValueError(f"Field '{ast.field}' is not numeric")
    elif ast.field:
        validate_field(ast.dataset, ast.field)
    for f in ast.filters:
        validate_field(ast.dataset, f.field)
        if f.operator == "contains" and field_spec(ast.dataset, f.field)["type"] != "string":
            raise ValueError("Operator 'contains' only applies to text fields")
    if ast.group_by:
        if ast.operation == "list":
            raise ValueError("group_by cannot be used with 'list'")
        validate_field(ast.dataset, ast.group_by)

def _coerce(dataset: str, field: str, value):
    kind = field_spec(dataset, field)["type"]
    try:
        if kind in NUMERIC_TYPES:
            return float(value)
        if kind == "date":
            return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid value '{value}' for field '{field}' ({kind})") from exc
    return str(value)

def _condition(dataset: str, f: Filter):
    column = TABLES[dataset].c[f.field]
    value = _coerce(dataset, f.field, f.value)
    if isinstance(value, str):
        # Case-insensitive text comparison: voice transcripts rarely match casing.
        column, value = func.lower(column), value.lower()
        if f.operator == "contains":
            return column.contains(value, autoescape=True)
    ops = {
        "eq": column.__eq__,
        "neq": column.__ne__,
        "gt": column.__gt__,
        "gte": column.__ge__,
        "lt": column.__lt__,
        "lte": column.__le__,
    }
    return ops[f.operator](value)

def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value

def execute_query(engine: Engine, ast: QueryAST) -> dict:
    validate_query(ast)
    table = TABLES[ast.dataset]
    conditions = [_condition(ast.dataset, f) for f in ast.filters]

    with engine.connect() as conn:
        if ast.operation == "list":
            stmt = select(table).where(*conditions).limit(ast.limit)
            rows = [{k: _jsonable(v) for k, v in r._mapping.items()} for r in conn.execute(stmt)]
            return {"rows": rows, "count": len(rows)}

        if ast.operation == "count":
            aggregate = func.count()
        else:
            aggregate = getattr(func, ast.operation)(table.c[ast.field])

        if ast.group_by:
            key = table.c[ast.group_by]
            stmt = (
                select(key.label("key"), aggregate.label("value"))
                .where(*conditions)
                .group_by(key)
                .order_by(desc("value"))
                .limit(ast.limit)
            )
            groups = [{"key": _jsonable(r.key), "value": _jsonable(r.value)} for r in conn.execute(stmt)]
            return {"groups": groups}

        stmt = select(aggregate).select_from(table).where(*conditions)
        return {"value": _jsonable(conn.execute(stmt).scalar_one())}

def log_query(engine: Engine, question: str | None, ast: QueryAST | None, answer: str, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(query_log).values(
                question=question,
                query=ast.model_dump() if ast else None,
                answer=answer,
                status=status,
            )
        )

def recent_logs(engine: Engine, limit: int = 20) -> list[dict]:
    stmt = select(query_log).order_by(query_log.c.id.desc()).limit(limit)
    with engine.connect() as conn:
        return [{k: _jsonable(v) for k, v in r._mapping.items()} for r in conn.execute(stmt)]

def list_datasets(engine=None):
    return list(ALLOWED_DATASETS.keys())

# Simple helpers used by the original GET endpoints.

def count_records(engine, dataset: str, field: str | None = None, value: str | None = None):
    filters = [Filter(field=field, value=value)] if field is not None else []
    return execute_query(engine, QueryAST(dataset=dataset, operation="count", filters=filters))["value"]

def sum_field(engine, dataset: str, field: str):
    value = execute_query(engine, QueryAST(dataset=dataset, operation="sum", field=field))["value"]
    return float(value or 0)

def average_field(engine, dataset: str, field: str):
    value = execute_query(engine, QueryAST(dataset=dataset, operation="avg", field=field))["value"]
    return float(value) if value is not None else None
