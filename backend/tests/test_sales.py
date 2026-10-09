from urllib.parse import unquote

from backend.app.services.sales import detect_solution, is_sales_request, whatsapp_action

def test_sales_intent():
    for q in ["Quiero hablar con un asesor", "¿Cuánto cuesta TMS?", "Quiero cotizar", "¿Qué precio tiene Pricing?",
              "Necesito una demo", "Me pueden contactar", "Quiero contratar Chat Bot"]:
        assert is_sales_request(q), q

def test_product_questions_are_not_sales():
    for q in ["¿Qué es Fuerza de Ventas?", "¿Qué es TMS?", "¿Qué hace Pricing con los precios?",
              "¿Tienen algo para WhatsApp?", "¿Cuál es la misión de CeluWeb?", "La demora en entregas"]:
        assert not is_sales_request(q), q

def test_detect_solution_uses_question_then_topic():
    assert detect_solution("¿Cuánto cuesta TMS?", None) == "TMS"
    assert detect_solution("Quiero cotizar", "Pricing") == "Pricing"
    assert detect_solution("Quiero cotizar", None) is None

def test_whatsapp_link_has_number_and_message():
    action = whatsapp_action("TMS")
    assert action["url"].startswith("https://wa.me/57")
    assert "TMS" in unquote(action["url"])
    assert "Osky" in unquote(action["url"])

def test_three_advisors_rotate_and_fallback_is_only_backup(tmp_path, monkeypatch):
    import json
    from backend.app.services import sales
    path = tmp_path / "contacts.json"
    contacts = [
        {"name": "Ana", "phone": "573001111111", "active": True},
        {"name": "Beto", "phone": "573002222222", "active": True},
        {"name": "Caro", "phone": "573003333333", "active": True},
        {"name": "Línea", "phone": "573104695891", "active": True, "fallback": True},
    ]
    path.write_text(json.dumps({"contacts": contacts}), encoding="utf-8")
    monkeypatch.setattr(sales, "CONTACTS_PATH", path)
    sales._cache.update(mtime=None, data=None)
    picked = [sales.whatsapp_action()["contact"] for _ in range(6)]
    assert picked == ["Ana", "Beto", "Caro", "Ana", "Beto", "Caro"]

    for c in contacts[:3]:
        c["active"] = False
    path.write_text(json.dumps({"contacts": contacts}), encoding="utf-8")
    sales._cache.update(mtime=None, data=None)
    assert sales.whatsapp_action()["contact"] == "Línea"

def test_picker_offers_three_advisors_specialist_first_with_context(tmp_path, monkeypatch):
    import json
    from backend.app.services import sales
    path = tmp_path / "contacts.json"
    contacts = [
        {"name": "Ana", "phone": "573001111111", "photo": "/comerciales/ana.jpg", "solutions": ["Pricing"]},
        {"name": "Beto", "phone": "573002222222", "solutions": ["TMS"]},
        {"name": "Caro", "phone": "573003333333"},
        {"name": "Dani", "phone": "573004444444"},
    ]
    path.write_text(json.dumps({"contacts": contacts}), encoding="utf-8")
    monkeypatch.setattr(sales, "CONTACTS_PATH", path)
    sales._cache.update(mtime=None, data=None)
    action = sales.whatsapp_action("TMS", "Laura", ["¿Qué es TMS?", "Quiero cotizar"])
    assert len(action["advisors"]) == 3
    assert action["advisors"][0]["name"] == "Beto"  # TMS specialist first
    text = unquote(action["advisors"][0]["url"])
    assert "soy Laura" in text and "Me interesa: TMS." in text and "“Quiero cotizar”" in text
    assert action["label"] == "Hablar con un asesor sobre TMS"
