from backend.app.services.knowledge import KnowledgeIndex, typo_distance
from backend.app.services.needs import match_needs

def test_needs_map_to_solutions():
    assert match_needs("necesito control de empleados")[1][:2] == ["Supervisores", "Mapas"]
    assert match_needs("tienen algo para WhatsApp")[1][0] == "Chat Bot"
    assert match_needs("quiero saber dónde están mis vendedores")[1][0] == "Supervisores"
    assert match_needs("tengo problemas con las entregas")[1][0] == "TMS"
    assert match_needs("precios de la competencia")[1] == ["Pricing"]
    assert match_needs("¿cuál es su misión?")[1] == []

def test_typo_distance_counts_swaps_as_one():
    assert typo_distance("presios", "precios", 2) == 1
    assert typo_distance("nesecito", "necesito", 2) == 2
    assert typo_distance("escrito", "necesito", 2) > 2

def test_fuzzy_correction_uses_known_words():
    from backend.app.services.knowledge import Chunk
    index = KnowledgeIndex([Chunk(1, "Pricing", "servicio", "", "Monitorea precios del mercado")])
    assert index.correct("nesecito presios de pricin") == "necesito precios de pricing"
    assert index.correct("Ana") == "ana"  # short words are left alone
