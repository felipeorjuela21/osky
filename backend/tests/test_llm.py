import httpx

from backend.app.core.config import settings
from backend.app.services import llm

CONTEXT = [{"title": "TMS", "content": "TMS optimiza la operación logística de transporte."}]

def _response(status: int, body: dict, url: str) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", url))

def test_retired_model_switches_to_an_available_one(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "llm_model", "llama-3.3-70b-versatile")  # retired by Groq
    llm.status.update(model=None, ok=None, error=None)
    used = []

    def fake_post(url, headers, json, timeout):
        used.append(json["model"])
        if json["model"] == settings.llm_model:
            return _response(400, {"error": {"message": "The model has been decommissioned"}}, url)
        return _response(200, {"choices": [{"message": {"content": "Claro, TMS optimiza tu logística."}}]}, url)

    def fake_get(url, headers, timeout):
        return _response(200, {"data": [{"id": "whisper-large-v3"}, {"id": "openai/gpt-oss-120b"}]}, url)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm.httpx, "get", fake_get)
    assert llm.natural_answer("¿Qué es TMS?", CONTEXT) == "Claro, TMS optimiza tu logística."
    assert used == [settings.llm_model, "openai/gpt-oss-120b"]
    assert llm.status["model"] == "openai/gpt-oss-120b" and llm.status["ok"] is True
    llm.status.update(model=None, ok=None, error=None)

def test_errors_are_reported_without_the_key(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "secret-key")
    monkeypatch.setattr(settings, "llm_provider", "groq")
    llm.status.update(model=None, ok=None, error=None)
    monkeypatch.setattr(llm.httpx, "post", lambda url, headers, json, timeout: _response(
        401, {"error": {"message": "Invalid API Key"}}, url))
    assert llm.natural_answer("¿Qué es TMS?", CONTEXT) is None
    assert llm.status["ok"] is False and "401" in llm.status["error"] and "secret-key" not in llm.status["error"]
    llm.status.update(model=None, ok=None, error=None)
