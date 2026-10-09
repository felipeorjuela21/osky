import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.core import security
from backend.app.core.config import settings
from backend.app.services import knowledge, llm, tts

def make_request(ip: str) -> Request:
    return Request({"type": "http", "headers": [(b"x-forwarded-for", ip.encode())], "client": ("1.1.1.1", 1)})

def test_rate_limit_blocks_after_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    security._hits.clear()
    for _ in range(3):
        security.rate_limit(make_request("9.9.9.9"))
    with pytest.raises(HTTPException) as err:
        security.rate_limit(make_request("9.9.9.9"))
    assert err.value.status_code == 429
    security.rate_limit(make_request("8.8.8.8"))  # other visitors are not affected

def test_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "secreto")
    with pytest.raises(HTTPException):
        security.require_admin(None)
    with pytest.raises(HTTPException):
        security.require_admin("otro")
    security.require_admin("secreto")

def test_admin_required_in_production_without_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(HTTPException):
        security.require_admin(None)

def test_llm_number_guard():
    assert llm._numbers("Somos más de 140 personas y 1.200 clientes") == {"140", "1200"}
    assert llm._numbers("Atendemos 24/7") == {"24", "7"}

def test_llm_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "auto")
    assert llm.natural_answer("¿Qué es TMS?", [{"title": "TMS", "content": "x"}]) is None

def test_tts_word_estimate_covers_audio():
    words = tts._estimate_words("¡Hola! Soy Osky, el asistente virtual.", 3.0)
    assert [w["text"] for w in words] == ["Hola", "Soy", "Osky", "el", "asistente", "virtual"]
    assert words[0]["start"] < words[-1]["start"] < 3.0

def test_documents_folder(tmp_path, monkeypatch):
    (tmp_path / "Ficha TMS.md").write_text("TMS planifica rutas.\n\nIncluye seguimiento en tiempo real.", encoding="utf-8")
    (tmp_path / "LEEME.md").write_text("instrucciones", encoding="utf-8")
    monkeypatch.setattr(knowledge, "DOCS_DIR", tmp_path)
    chunks = knowledge.load_documents()
    assert {c.title for c in chunks} == {"Ficha TMS"}
    assert "seguimiento en tiempo real" in chunks[0].content
