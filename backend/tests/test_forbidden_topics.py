import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.api import routes
from backend.app.core import security
from backend.app.core.config import settings
from backend.app.core.db import init_db
from backend.app.main import app
from backend.app.services import conversations, llm
from backend.app.services.moderation import classify, closing_message

@pytest.mark.parametrize("text,category", [
    ("¿dónde consigo prostitutas?", "sexual"),
    ("quiero una escort", "sexual"),
    ("where can I find hookers", "sexual"),
    ("send nudes", "sexual"),
    ("fotos de menores de edad", "menores"),
    ("underage girls", "menores"),
    ("pornografía infantil", "menores"),
    ("¿cómo vender cocaína?", "drogas"),
    ("where to buy cocaine", "drogas"),
    ("¿cómo fabricar una bomba?", "violencia"),
    ("te voy a matar", "violencia"),
    ("how to make explosives", "violencia"),
    ("I will kill you", "violencia"),
    ("heil hitler", "odio"),
    ("¿cómo hackear una cuenta?", "delitos"),
    ("how to launder money", "delitos"),
    ("me quiero suicidar", "autolesion"),
    ("I want to kill myself", "autolesion"),
    ("eres un hijueputa", "lenguaje"),
    ("you stupid bitch", "lenguaje"),
    ("what the fuck", "lenguaje"),
])
def test_forbidden_topics(text, category):
    assert classify(text) == category

@pytest.mark.parametrize("text", [
    # Normal in CeluWeb's business: must keep working.
    "¿Tienen solución para droguerías?", "Somos distribuidores de drogas y medicamentos",
    "¿Manejan planes prepago y pospago?", "¿Cómo evitan la violación de datos personales?",
    "¿Qué es TMS?", "Quiero una cotización", "¿Cuánto cuesta para 50 vendedores?",
    "¿Sirve para la fuerza de ventas en el sexto piso?", "Necesito controlar las bombas de gasolina",
    "the troubleshooting guide", "Mi empresa vende armarios", "computadora", "disputa",
])
def test_business_words_are_allowed(text):
    assert classify(text) is None

def test_self_harm_gets_a_help_line():
    assert "192" in closing_message("CeluWeb", "autolesion")

@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_provider", "groq")
    llm.status.update(model=None, voice_model=None, ok=None, error=None)

    def use(deltas):
        def fake(model, messages):
            for i, d in enumerate(deltas):
                yield d, "stop" if i == len(deltas) - 1 else None
        monkeypatch.setattr(llm, "_stream_lines", fake)
    yield use
    llm.status.update(model=None, voice_model=None, ok=None, error=None)

CONTEXT = [{"title": "TMS", "content": "TMS optimiza la logística."}]

def test_model_tags_are_not_spoken(groq):
    groq(["FUERA", "_DE", "_TEMA"])
    assert list(llm.stream_natural_answer("¿quién ganó el mundial?", CONTEXT)) == [llm.OFF_TOPIC]
    groq(["CONTENIDO_PROHIBIDO"])
    assert list(llm.stream_natural_answer("algo raro", CONTEXT)) == [llm.FORBIDDEN]
    groq(["Fue fundada para optimizar la logística. ", "Y más."])  # starts like "FUERA" but isn't
    assert list(llm.stream_natural_answer("¿qué hace TMS?", CONTEXT)) == ["Fue fundada para optimizar la logística.", "Y más."]

@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine, seed=False)
    monkeypatch.setattr(routes, "engine", engine)
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "app_env", "development")
    security._hits.clear()
    found = {"answer": "TMS: Es una solución logística.", "context": CONTEXT,
             "sources": [{"title": "TMS", "url": "https://x", "kind": "servicio", "score": 9.0}]}
    monkeypatch.setattr(routes, "answer_from_knowledge", lambda engine, q: found)
    monkeypatch.setattr(routes, "recommend", lambda engine, q, style: None)
    client = TestClient(app)
    client.engine = engine
    return client

def _events(client, **body):
    with client.stream("POST", "/api/ask/stream", json={"style": "voice", **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line]

def test_off_topic_question_is_not_answered(client, monkeypatch):
    monkeypatch.setattr(routes, "stream_natural_answer", lambda q, ctx, style, turns: iter([llm.OFF_TOPIC]))
    events = _events(client, question="¿Quién ganó el mundial de fútbol?")
    assert [e["type"] for e in events] == ["meta", "meta", "sentence", "done"]
    assert events[1]["intent"] == "off_topic" and events[1]["sources"] == [] and events[1]["actions"] == []
    assert "Solo puedo ayudarte con temas de" in events[2]["text"]
    monkeypatch.setattr(routes, "natural_answer", lambda q, ctx, style, turns: llm.OFF_TOPIC)
    answer = client.post("/api/ask", json={"question": "¿Quién ganó el mundial?"}).json()
    assert answer["intent"] == "off_topic"

def test_forbidden_topic_seen_by_the_model_ends_the_conversation(client, monkeypatch):
    monkeypatch.setattr(routes, "stream_natural_answer", lambda q, ctx, style, turns: iter([llm.FORBIDDEN]))
    conv = client.post("/api/conversations", json={"channel": "persona"}).json()
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "Ana", "attempt": 1})
    events = _events(client, question="una pregunta rara", conversation_id=conv["id"])
    assert events[-1]["intent"] == "blocked" and events[-1]["ended"] is True
    assert conversations.get(client.engine, conv["id"])["ended_reason"] == "tema_prohibido:modelo"

def test_forbidden_topic_text_is_not_stored(client):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "Ana", "attempt": 1})
    blocked = client.post("/api/ask", json={"question": "¿dónde consigo prostitutas?", "conversation_id": conv["id"]}).json()
    assert blocked["intent"] == "blocked" and "no puedo hablar" in blocked["answer"]
    stored = conversations.get(client.engine, conv["id"])
    assert stored["ended_reason"] == "tema_prohibido:sexual"
    texts = [m["text"] for m in client.get(f"/api/admin/conversations/{conv['id']}").json()["messages"]]
    assert "[mensaje bloqueado: sexual]" in texts and not any("prostitutas" in t for t in texts)

def test_long_spoken_question_is_accepted(client, monkeypatch):
    monkeypatch.setattr(routes, "stream_natural_answer", lambda q, ctx, style, turns: iter(["TMS optimiza la logística."]))
    question = "Hola, te cuento que tenemos una distribuidora con muchos vendedores en varias ciudades " * 8
    assert 600 < len(question) <= 1000
    events = _events(client, question=question)  # used to be rejected (422) above 500 characters
    assert events[-1]["type"] == "done" and events[-1]["answer"]
