from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.core.db import init_db
from backend.app.services.answer import build_answer
from backend.app.services.nl_parser import NotUnderstood, load_known_values, parse_question
from backend.app.services.query_engine import Filter, QueryAST, execute_query

TODAY = date(2026, 10, 6)

@pytest.fixture(scope="module")
def engine():
    # A single shared connection keeps the in-memory database alive.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    return engine

def ask(engine, question):
    ast = parse_question(question, load_known_values(engine), today=TODAY)
    result = execute_query(engine, ast)
    return ast, result, build_answer(ast, result)

def test_count_active_customers_in_bogota(engine):
    ast, result, answer = ask(engine, "¿Cuántos clientes activos hay en Bogotá?")
    assert ast.dataset == "customers" and ast.operation == "count"
    assert result["value"] == 1
    assert answer == "Hay 1 cliente en Bogotá, con estado activo."

def test_inactive_is_not_confused_with_active(engine):
    _, result, _ = ask(engine, "cuantos clientes inactivos hay")
    assert result["value"] == 1

def test_sum_by_seller(engine):
    ast, result, answer = ask(engine, "¿Cuánto vendió Felipe?")
    assert ast.operation == "sum" and ast.field == "amount"
    assert result["value"] == 250000
    assert "$250.000" in answer

def test_month_filter(engine):
    _, result, _ = ask(engine, "total de ventas en octubre")
    assert result["value"] == 475000
    _, result, answer = ask(engine, "total de ventas en noviembre")
    assert result["value"] is None
    assert answer.startswith("No encontré ventas")

def test_best_seller(engine):
    _, result, answer = ask(engine, "¿Quién vendió más?")
    assert result["groups"][0]["key"] == "Felipe"
    assert answer.startswith("Felipe")

def test_sales_by_customer_name(engine):
    ast, result, _ = ask(engine, "cuantas ventas tiene Empresa A")
    assert {"field": "customer_id", "value": "001"}.items() <= ast.filters[0].model_dump().items()
    assert result["value"] == 2

def test_group_by(engine):
    _, result, _ = ask(engine, "total de ventas por vendedor")
    assert result["groups"] == [{"key": "Felipe", "value": 250000.0}, {"key": "Laura", "value": 225000.0}]

def test_cross_dataset_filter_is_refused(engine):
    with pytest.raises(NotUnderstood):
        ask(engine, "cuanto se vendio en Cali")

def test_unrelated_question_is_refused(engine):
    with pytest.raises(NotUnderstood):
        ask(engine, "cuéntame un chiste")

def test_ast_rejects_unknown_field(engine):
    with pytest.raises(ValueError):
        execute_query(engine, QueryAST(dataset="sales", operation="sum", field="password"))

def test_ast_rejects_sum_on_text(engine):
    with pytest.raises(ValueError):
        execute_query(engine, QueryAST(dataset="sales", operation="sum", field="seller"))

def test_filter_values_are_parameters_not_sql(engine):
    ast = QueryAST(dataset="customers", operation="count", filters=[Filter(field="name", value="x' OR '1'='1")])
    assert execute_query(engine, ast)["value"] == 0
