import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.api import routes
from backend.app.core.config import settings
from backend.app.core.db import init_db
from backend.app.core import security
from backend.app.main import app
from backend.app.services.conversations import extract_name, name_reply, personalize

@pytest.mark.parametrize("text,name", [
    ("Juan", "Juan"),
    ("juan felipe", "Juan Felipe"),
    ("Hola, me llamo Ana María", "Ana María"),
    ("Buenas tardes, mi nombre es carlos pérez", "Carlos Pérez"),
    ("soy Laura", "Laura"),
    ("Hola Osky, soy Pedro", "Pedro"),
    ("Juan de la Cruz", "Juan"),
])
def test_extract_name(text, name):
    assert extract_name(text) == name

@pytest.mark.parametrize("text", ["¿Qué es TMS?", "quiero hablar con un asesor", "precio de pricing", "hola", "no", "x"])
def test_not_a_name(text):
    assert extract_name(text) is None

def test_name_reply_flow():
    assert name_reply("Me llamo Ana", 1)["status"] == "ok"
    assert name_reply("Prefiero no decirlo", 1)["status"] == "declined"
    assert name_reply("¿Qué es TMS?", 1)["status"] == "retry"
    assert name_reply("¿Qué es TMS?", 2)["status"] == "skip"

def test_personalize():
    assert personalize("¡Con gusto! Te comunico.", "Ana", "sales", "Claro") == "¡Con gusto, Ana! Te comunico."
    assert personalize("Mmm, eso no lo encuentro.", "Ana", "not_found", "Claro") == "Mmm, Ana, eso no lo encuentro."
    assert personalize("TMS: Es una solución.", "Ana", "answer", "Mira") == "Mira, Ana. TMS: Es una solución."
    assert personalize("TMS: Es una solución.", None, "answer", "Mira") == "TMS: Es una solución."

@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine, seed=False)
    monkeypatch.setattr(routes, "engine", engine)
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "app_env", "development")
    security._hits.clear()
    return TestClient(app)  # no "with": the app's startup (knowledge loading) is not needed here

def test_conversation_is_logged_with_name(client):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    assert "cómo te llamas" in conv["greeting"]
    named = client.post(f"/api/conversations/{conv['id']}/name", json={"text": "me llamo ana", "attempt": 1}).json()
    assert named["name"] == "Ana" and "Ana" in named["reply"]

    answer = client.post("/api/ask", json={"question": "Quiero hablar con un asesor", "conversation_id": conv["id"]}).json()
    assert answer["intent"] == "sales" and answer["answer"].startswith("¡Con gusto, Ana!")

    listing = client.get("/api/admin/conversations").json()
    assert listing["total"] == 1 and listing["items"][0]["name"] == "Ana" and listing["items"][0]["questions"] == 1

    transcript = client.get(f"/api/admin/conversations/{conv['id']}").json()
    assert [m["role"] for m in transcript["messages"]] == ["visitante", "osky", "visitante", "osky"]
    assert transcript["messages"][-1]["source"].startswith("WhatsApp → ")

    csv = client.get("/api/admin/export.csv")
    assert "Ana" in csv.text and "Quiero hablar con un asesor" in csv.text

def test_admin_needs_token_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/api/admin/conversations").status_code == 403
    monkeypatch.setattr(settings, "admin_token", "secreto")
    assert client.get("/api/admin/conversations").status_code == 401
    assert client.get("/api/admin/conversations", headers={"X-Admin-Token": "secreto"}).status_code == 200
