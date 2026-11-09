"""Data minimisation, CSV safety, error messages and query counts."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

from backend.app.api import routes
from backend.app.core import security
from backend.app.core.config import settings
from backend.app.core.db import conversations as conv_table, init_db, query_log
from backend.app.main import app
from backend.app.services import conversations as conv_service
from backend.app.services.stt import STTUnavailable

@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine, seed=False)
    monkeypatch.setattr(routes, "engine", engine)
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "global_rate_limit_per_minute", 0)
    security._hits.clear()
    return TestClient(app)

def _start(client, text: str | None = "me llamo ana"):
    conv = client.post("/api/conversations", json={"channel": "chat"}).json()
    if text:
        client.post(f"/api/conversations/{conv['id']}/name", json={"text": text, "attempt": 1})
    return conv

def _logs():
    with routes.engine.connect() as conn:
        return conn.execute(select(query_log)).all()

def test_query_log_has_no_text_without_consent(client):
    client.post("/api/ask", json={"question": "Quiero hablar con un asesor de TMS"})  # no conversation
    conv = _start(client, "no")  # declined
    client.post("/api/ask", json={"question": "Quiero cotizar Pricing", "conversation_id": conv["id"]})
    rows = _logs()
    assert rows
    assert all(r.question is None and r.answer is None and r.query is None and r.status for r in rows)

def test_query_log_keeps_redacted_text_with_consent(client):
    conv = _start(client)
    client.post("/api/ask", json={"question": "Quiero un asesor, mi celular es 3001234567",
                                  "conversation_id": conv["id"]})
    rows = _logs()
    assert any(r.question and "3001234567" not in r.question for r in rows)

def test_purge_expired_also_clears_old_query_log(client):
    old = conv_service._now() - timedelta(days=400)
    with routes.engine.begin() as conn:
        conn.execute(insert(query_log).values(status="ok", question="vieja", created_at=old))
        conn.execute(insert(query_log).values(status="ok", question="nueva"))
    conv_service.purge_expired(routes.engine, days=365, force=True)
    assert [r.question for r in _logs()] == ["nueva"]

def test_name_is_redacted_and_user_agent_not_stored(client):
    conv = _start(client, None)
    client.post(f"/api/conversations/{conv['id']}/name", json={"text": "me llamo ana 3001234567", "attempt": 1},
                headers={"User-Agent": "Mozilla/5.0 test"})
    transcript = client.get(f"/api/admin/conversations/{conv['id']}").json()
    assert transcript["messages"] and all("3001234567" not in m["text"] for m in transcript["messages"])
    with routes.engine.connect() as conn:
        assert conn.execute(select(conv_table.c.user_agent)).scalar_one() is None

def test_csv_neutralises_formulas(client):
    conv = _start(client)
    conv_service.log_message(routes.engine, conv["id"], "visitante", '=HYPERLINK("http://x")', is_question=True)
    conv_service.log_message(routes.engine, conv["id"], "visitante", "@SUM(A1)")
    text = client.get("/api/admin/export.csv").text.replace('"', "")
    assert ";'=HYPERLINK" in text and ";'@SUM" in text
    assert ";=HYPERLINK" not in text and ";@SUM" not in text

def test_list_conversations_last_question(client):
    ids = []
    for who in ("ana", "luis"):
        conv = _start(client, f"me llamo {who}")
        conv_service.log_message(routes.engine, conv["id"], "visitante", f"primera de {who}", is_question=True)
        conv_service.log_message(routes.engine, conv["id"], "visitante", f"ultima de {who}", is_question=True)
        ids.append(conv["id"])
    items = {i["id"]: i for i in client.get("/api/admin/conversations").json()["items"]}
    assert items[ids[0]]["last_question"] == "ultima de ana"
    assert items[ids[1]]["last_question"] == "ultima de luis"

def test_health_does_not_touch_the_database(client):
    # The cron pings /health: querying the database would keep the free Neon plan awake 24/7.
    body = client.get("/health").json()
    assert body["status"] == "ok" and "db" not in body

def test_stt_errors_are_generic_and_size_checked(client, monkeypatch):
    big = client.post("/api/stt", content=b"x", headers={"Content-Length": str(4 * 1024 * 1024)})
    assert big.status_code in (413, 400)

    def boom(audio, content_type):
        raise STTUnavailable("secret internal detail")

    monkeypatch.setattr(routes, "transcribe", boom)
    res = client.post("/api/stt", content=b"abc", headers={"Content-Type": "audio/webm"})
    assert res.status_code == 503 and "secret" not in res.text

def test_knowledge_index_signature_is_cached(client, monkeypatch):
    from backend.app.services import knowledge
    calls = []
    original = knowledge._docs_signature
    monkeypatch.setattr(knowledge, "_docs_signature", lambda: calls.append(1) or original())
    knowledge.invalidate_index()
    with routes.engine.begin() as conn:
        from backend.app.core.db import knowledge_chunks
        conn.execute(insert(knowledge_chunks).values(source_url="u", title="TMS", kind="servicio", content="TMS rutas"))
    knowledge.get_index(routes.engine)
    knowledge.get_index(routes.engine)
    knowledge.get_index(routes.engine)
    assert len(calls) == 1
    knowledge.invalidate_index()
    knowledge.get_index(routes.engine)
    assert len(calls) == 2
