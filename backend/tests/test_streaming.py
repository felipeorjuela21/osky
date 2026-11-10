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
from backend.app.services import llm

CONTEXT = [{"title": "TMS", "content": "TMS optimiza la logística. Tiene 3 módulos."}]

def test_sentences_split_only_at_sentence_ends():
    done, rest = llm._sentences("TMS optimiza la logística. Cuesta 1.5 veces menos. Y adem")
    assert done == ["TMS optimiza la logística.", "Cuesta 1.5 veces menos."] and rest == "Y adem"
    # Very short pieces ("Sí.") wait for the next sentence.
    assert llm._sentences("Sí. TMS es una solución de rutas. ")[0] == ["Sí. TMS es una solución de rutas."]

@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_provider", "groq")
    llm.status.update(model=None, voice_model=None, ok=None, error=None)

    def use(deltas, finish="stop"):
        def fake(model, messages):
            for i, d in enumerate(deltas):
                yield d, finish if i == len(deltas) - 1 else None
        monkeypatch.setattr(llm, "_stream_lines", fake)
    yield use
    llm.status.update(model=None, voice_model=None, ok=None, error=None)

def test_stream_yields_sentences_as_they_arrive(groq):
    groq(["<think>pienso", "</think>¡Claro! TMS opti", "miza la logística. ", "Tiene 3 módulos."])
    assert list(llm.stream_natural_answer("¿Qué es TMS?", CONTEXT)) == [
        "¡Claro! TMS optimiza la logística.", "Tiene 3 módulos."]

def test_stream_stops_before_an_invented_figure(groq):
    groq(["TMS optimiza la logística de tu empresa. ", "Cuesta 500 dólares. ", "Y más cosas."])
    assert list(llm.stream_natural_answer("¿Qué es TMS?", CONTEXT)) == ["TMS optimiza la logística de tu empresa."]

def test_stream_drops_a_cut_off_sentence(groq):
    groq(["TMS optimiza la logística de tu empresa. ", "Además permite"], finish="length")
    assert list(llm.stream_natural_answer("¿Qué es TMS?", CONTEXT)) == ["TMS optimiza la logística de tu empresa."]

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
    return TestClient(app)

def _events(client, **body):
    with client.stream("POST", "/api/ask/stream", json={"style": "voice", **body}) as r:
        assert r.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in r.iter_lines() if line]

def test_stream_endpoint_sends_meta_sentences_done(client, monkeypatch):
    monkeypatch.setattr(routes, "stream_natural_answer",
                        lambda q, ctx, style, turns: iter(["¡Claro! TMS optimiza la logística.", "Tiene 3 módulos."]))
    conv = client.post("/api/conversations", json={"channel": "persona"}).json()
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "Ana", "attempt": 1})
    events = _events(client, question="¿Qué es TMS?", conversation_id=conv["id"])
    assert [e["type"] for e in events] == ["meta", "sentence", "sentence", "done"]
    assert events[0]["intent"] == "answer" and events[0]["sources"][0]["title"] == "TMS"
    assert events[1]["text"] == "¡Claro, Ana! TMS optimiza la logística."  # name in the first answer
    assert events[-1]["answer"] == "¡Claro, Ana! TMS optimiza la logística. Tiene 3 módulos."
    transcript = client.get(f"/api/admin/conversations/{conv['id']}").json()
    assert transcript["messages"][-1]["text"] == events[-1]["answer"]

def test_stream_endpoint_falls_back_to_the_extract(client, monkeypatch):
    monkeypatch.setattr(routes, "stream_natural_answer", lambda q, ctx, style, turns: iter([]))
    events = _events(client, question="¿Qué es TMS?")
    assert [e["type"] for e in events] == ["meta", "sentence", "done"]
    assert "TMS: Es una solución logística." in events[1]["text"] and events[-1]["answer"] == events[1]["text"]

def test_stream_endpoint_blocks_offensive_language(client):
    events = _events(client, question="eres un malparido")
    assert events[0]["intent"] == "blocked" and events[-1]["ended"] is True

def test_voice_uses_the_faster_model_and_chat_keeps_its_own(groq, monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "voice_llm_model", "openai/gpt-oss-20b")
    used = []

    def fake(model, messages):
        used.append(model)
        yield "TMS optimiza la logística de tu empresa.", "stop"
    monkeypatch.setattr(llm, "_stream_lines", fake)
    list(llm.stream_natural_answer("¿Qué es TMS?", CONTEXT, "voice"))
    list(llm.stream_natural_answer("¿Qué es TMS?", CONTEXT, "chat"))
    assert used == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    assert llm.status["voice_model"] == "openai/gpt-oss-20b" and llm.status["model"] == "openai/gpt-oss-120b"
