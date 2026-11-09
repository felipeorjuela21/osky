from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.pool import StaticPool

from backend.app.api import routes
from backend.app.core import security
from backend.app.core.config import settings
from backend.app.core.db import chat_messages, conversations as conversations_table, init_db
from backend.app.main import app
from backend.app.services import conversations
from backend.app.services.moderation import is_offensive
from backend.app.services.privacy import redact

@pytest.mark.parametrize("text", [
    "hijueputa", "eres un malparido", "HPTA", "hijo de puta", "qué gonorrea", "p.u.t.a", "putaaaa",
    "h*********", "huevón", "qué mierda es eso", "fuck you", "muéstrame porno", "careverga",
    "estúpido robot", "h1jueput4", "me llamo hijueputa",
])
def test_offensive(text):
    assert is_offensive(text)

@pytest.mark.parametrize("text", [
    "computadora", "disputa", "¿Qué es TMS?", "quiero una cotización de Pricing", "precio para 50 usuarios",
    "¿tienen presencia en el Cono Sur?", "qué chimba de servicio", "me da vergüenza preguntar",
    "¿cómo protegen mis datos personales?", "Hola Osky", "sexto piso", "Me llamo Ana",
])
def test_not_offensive(text):
    assert not is_offensive(text)

def test_redact():
    text = redact("mi correo es juan.p@x.com, mi cel 300 123 4567 y cédula 1.094.888.123; somos 50 usuarios")
    assert text == "mi correo es [correo], mi cel [número] y cédula [número]; somos 50 usuarios"

def test_add_name():
    assert conversations.add_name("¡Claro! TMS optimiza rutas.", "Ana") == "¡Claro, Ana! TMS optimiza rutas."
    assert conversations.add_name("Mira, TMS optimiza rutas.", "Ana") == "Mira, Ana, TMS optimiza rutas."
    assert conversations.add_name("TMS optimiza rutas.", "Ana") == "Ana, TMS optimiza rutas."
    assert conversations.add_name("Nuestra solución TMS...", "Ana") == "Ana, nuestra solución TMS..."

@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine, seed=False)
    return engine

@pytest.fixture
def client(monkeypatch, engine):
    monkeypatch.setattr(routes, "engine", engine)
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "app_env", "development")
    security._hits.clear()
    return TestClient(app)

def _messages(engine, conversation_id):
    with engine.connect() as conn:
        return conn.execute(select(chat_messages.c.text).where(chat_messages.c.conversation_id == conversation_id)).scalars().all()

def test_greeting_asks_for_authorisation(client):
    conv = client.post("/api/conversations", json={"channel": "persona"}).json()
    assert "política de datos" in conv["greeting"] and "cómo te llamas" in conv["greeting"]
    assert conv["privacy_url"] == settings.privacy_policy_url

def test_name_is_consent(client, engine):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "Me llamo Ana", "attempt": 1})
    stored = conversations.get(engine, conv["id"])
    assert stored["consent"] == "si" and stored["visitor_name"] == "Ana"
    assert stored["consent_at"] and stored["policy_version"] == settings.privacy_policy_version
    client.post("/api/ask", json={"question": "Quiero un asesor, mi cel es 3001234567", "conversation_id": conv["id"]})
    texts = _messages(engine, conv["id"])
    assert "Quiero un asesor, mi cel es [número]" in texts and not any("3001234567" in t for t in texts)

def test_declined_stores_nothing(client, engine):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    reply = client.post(f"/api/conversations/{conv['id']}/name", json={"text": "no", "attempt": 1}).json()
    assert reply["status"] == "declined" and "no guardaré" in reply["reply"]
    answer = client.post("/api/ask", json={"question": "Quiero un asesor", "conversation_id": conv["id"]}).json()
    assert answer["intent"] == "sales" and answer["name"] is None
    assert conversations.get(engine, conv["id"])["consent"] == "no"
    assert _messages(engine, conv["id"]) == []

def test_offensive_language_ends_the_conversation(client, engine):
    conv = client.post("/api/conversations", json={"channel": "persona"}).json()
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "Pedro", "attempt": 1})
    blocked = client.post("/api/ask", json={"question": "eres un malparido", "conversation_id": conv["id"]}).json()
    assert blocked["intent"] == "blocked" and blocked["ended"] is True
    assert conversations.get(engine, conv["id"])["ended_reason"] == "lenguaje_inapropiado"
    # The conversation stays closed, even for a polite question.
    again = client.post("/api/ask", json={"question": "¿Qué es TMS?", "conversation_id": conv["id"]}).json()
    assert again["intent"] == "blocked"

def test_offensive_name_ends_the_conversation(client, engine):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    reply = client.post(f"/api/conversations/{conv['id']}/name", json={"text": "me llamo gonorrea", "attempt": 1}).json()
    assert reply["status"] == "blocked" and reply["ended"] is True
    stored = conversations.get(engine, conv["id"])
    assert stored["visitor_name"] is None and stored["ended_reason"] == "lenguaje_inapropiado"

def test_admin_can_delete_a_conversation(client, engine):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "Ana", "attempt": 1})
    assert client.delete(f"/api/admin/conversations/{conv['id']}").json() == {"status": "deleted"}
    assert conversations.get(engine, conv["id"]) is None and _messages(engine, conv["id"]) == []
    assert client.delete(f"/api/admin/conversations/{conv['id']}").status_code == 404

def test_old_conversations_are_purged(engine):
    old = conversations.start(engine, "chat")
    recent = conversations.start(engine, "chat")
    conversations.log_message(engine, old, "visitante", "hola")
    with engine.begin() as conn:
        conn.execute(update(conversations_table).where(conversations_table.c.id == old).values(
            last_activity_at=conversations._now() - timedelta(days=400)))
    assert conversations.purge_expired(engine, days=365, force=True) == 1
    assert conversations.get(engine, old) is None and conversations.get(engine, recent)
    assert _messages(engine, old) == []
