import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.core import security
from backend.app.core.config import settings
from backend.app.services import knowledge, llm, tts

def make_request(ip: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (ip, 1)})

def test_rate_limit_blocks_after_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    security._hits.clear()
    for _ in range(3):
        security.rate_limit(make_request("9.9.9.9"))
    with pytest.raises(HTTPException) as err:
        security.rate_limit(make_request("9.9.9.9"))
    assert err.value.status_code == 429
    security.rate_limit(make_request("8.8.8.8"))  # other visitors are not affected

def test_forged_forwarded_for_does_not_skip_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "global_rate_limit_per_minute", 0)
    security._hits.clear()
    # The proxy appends the real address at the END; the forged start changes on every call.
    with pytest.raises(HTTPException) as err:
        for i in range(10):
            security.rate_limit(make_request("1.1.1.1", f"10.0.0.{i}, 5.5.5.5"))
    assert err.value.status_code == 429

def test_global_cap_applies_across_ips(monkeypatch):
    monkeypatch.setattr(settings, "global_rate_limit_per_minute", 4)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 100)
    security._hits.clear()
    security._global_hits.clear()
    with pytest.raises(HTTPException) as err:
        for i in range(10):
            security.rate_limit(make_request(f"7.7.7.{i}"))
    assert err.value.status_code == 429
    security._global_hits.clear()

def test_media_limit_is_separate_and_higher(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "media_rate_limit_per_minute", 5)
    monkeypatch.setattr(settings, "global_rate_limit_per_minute", 0)
    security._hits.clear()
    for _ in range(2):
        security.rate_limit(make_request("4.4.4.4"))
    with pytest.raises(HTTPException):
        security.rate_limit(make_request("4.4.4.4"))
    for _ in range(5):  # same visitor, voice endpoints still work
        security.rate_limit_media(make_request("4.4.4.4"))
    with pytest.raises(HTTPException):
        security.rate_limit_media(make_request("4.4.4.4"))

def test_admin_blocks_after_many_wrong_tokens(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "secreto")
    security._failures.clear()
    request = make_request("3.3.3.3")
    for _ in range(security.ADMIN_MAX_FAILS):
        with pytest.raises(HTTPException) as err:
            security.require_admin(request, "mal")
        assert err.value.status_code == 401
    with pytest.raises(HTTPException) as err:
        security.require_admin(request, "secreto")  # even the right one, from the blocked IP
    assert err.value.status_code == 429
    security.require_admin(make_request("2.2.2.2"), "secreto")  # other IPs are fine
    security._failures.clear()

def test_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "secreto")
    security._failures.clear()
    request = make_request("6.6.6.6")
    with pytest.raises(HTTPException):
        security.require_admin(request, None)
    with pytest.raises(HTTPException):
        security.require_admin(request, "otro")
    security.require_admin(request, "secreto")

def test_admin_required_in_production_without_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(HTTPException):
        security.require_admin(make_request("6.6.6.6"), None)

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
