from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.smalltalk import match_smalltalk

client = TestClient(app)

def ask(question: str) -> str:
    return client.post("/api/ask", json={"question": question}).json()["answer"]

def test_owner_and_manager_come_from_official_facts():
    assert "Oscar Lozada" in ask("¿Quién es el dueño de CeluWeb?")
    assert "Oscar Lozada" in ask("quien es el dueno")
    assert "Juan Pablo Zambrano" in ask("¿Quién es el gerente de CeluWeb?")
    assert "Juan Pablo Zambrano" in ask("quien es el jerente")  # typo

def test_creator():
    for q in ["¿Quién te creó?", "quien te hizo osky", "¿quiénes te desarrollaron?", "quien es tu creador"]:
        talk = match_smalltalk(q)
        assert talk and talk["intent"] == "creator", q
        assert "Juan Felipe Orjuela" in talk["answer"]
    assert match_smalltalk("¿Qué es TMS?") is None
