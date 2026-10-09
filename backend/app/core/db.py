from datetime import date
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from backend.app.core.config import settings

metadata = MetaData()

customers = Table(
    "customers",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("name", Text, nullable=False),
    Column("city", Text),
    Column("status", String(50)),
)

sales = Table(
    "sales",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("customer_id", String(100)),
    Column("seller", Text),
    Column("amount", Numeric(14, 2, asdecimal=False)),
    Column("sale_date", Date),
)

query_log = Table(
    "query_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("question", Text),
    Column("query", JSON),
    Column("answer", Text),
    Column("status", String(30)),
)

knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_url", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("kind", String(30), nullable=False),
    Column("content", Text, nullable=False),
    Column("fetched_at", DateTime, server_default=func.now()),
)

# One row per chat with a visitor (name + when it started), for the admin log.
conversations = Table(
    "conversations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("visitor_name", String(80)),
    Column("channel", String(20)),  # "chat" | "persona"
    Column("started_at", DateTime),  # UTC
    Column("last_activity_at", DateTime),  # UTC
    Column("questions", Integer, default=0),
    Column("user_agent", String(200)),
)

# Every message of every conversation, in order.
chat_messages = Table(
    "chat_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("conversation_id", String(36), index=True, nullable=False),
    Column("created_at", DateTime),  # UTC
    Column("role", String(12)),  # "visitante" | "osky"
    Column("text", Text),
    Column("intent", String(30)),
    Column("source", Text),  # page used for the answer, or "WhatsApp → advisor"
)

TABLES = {"customers": customers, "sales": sales}

SEED_CUSTOMERS = [
    {"id": "001", "name": "Empresa A", "city": "Bogotá", "status": "active"},
    {"id": "002", "name": "Empresa B", "city": "Cali", "status": "active"},
    {"id": "003", "name": "Empresa C", "city": "Bogotá", "status": "inactive"},
]

SEED_SALES = [
    {"id": "S001", "customer_id": "001", "seller": "Felipe", "amount": 150000, "sale_date": date(2026, 10, 1)},
    {"id": "S002", "customer_id": "001", "seller": "Laura", "amount": 225000, "sale_date": date(2026, 10, 2)},
    {"id": "S003", "customer_id": "002", "seller": "Felipe", "amount": 100000, "sale_date": date(2026, 10, 3)},
]

def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)

def init_db(engine: Engine, seed: bool = True) -> None:
    metadata.create_all(engine)
    if not seed:
        return
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(customers)).scalar_one() == 0:
            conn.execute(insert(customers), SEED_CUSTOMERS)
        if conn.execute(select(func.count()).select_from(sales)).scalar_one() == 0:
            conn.execute(insert(sales), SEED_SALES)

engine = make_engine()
