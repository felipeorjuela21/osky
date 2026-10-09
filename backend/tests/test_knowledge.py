from backend.app.services.knowledge import Chunk, KnowledgeIndex, best_extract, tokenize

CHUNKS = [
    Chunk(1, "TMS", "servicio", "https://x/tms", "TMS\nEs una solución para optimizar el transporte y la distribución.\nPlanificación de rutas"),
    Chunk(2, "Chat Bot", "servicio", "https://x/bot", "Automatiza la gestión comercial a través de WhatsApp.\nToma de pedidos por WhatsApp"),
    Chunk(3, "Datos de contacto", "contacto", "https://x/c", "Datos de contacto: Mesa de ayuda: +57 320 000 0000. Correo electrónico: a@b.com."),
    Chunk(4, "Blog TMS", "articulo", "https://x/blog", "El TMS ayuda a reducir costos en transporte."),
]

def search(question):
    return KnowledgeIndex(CHUNKS).search(question)

def test_tokenize_removes_accents_stopwords_and_plurals():
    assert tokenize("¿Cuáles son las Soluciones de CeluWeb?") == ["solucion", "celuweb"]

def test_synonyms_map_everyday_words_to_site_vocabulary():
    assert search("¿tienen algo para whatsapp?")[0][1].id == 2
    assert search("¿cuál es el teléfono?")[0][1].id == 3
    assert search("algo para el transporte")[0][1].id == 1

def test_official_page_outranks_blog():
    assert search("¿qué es TMS?")[0][1].id == 1

def test_unrelated_question_finds_nothing():
    assert search("cuéntame un chiste") == []

def test_extract_is_verbatim_and_starts_at_best_line():
    extract = best_extract("pedidos por whatsapp", CHUNKS[1].content)
    assert extract.rstrip(".") in CHUNKS[1].content.replace("\n", " ")

def test_join_for_speech_reads_bullets_as_a_list():
    from backend.app.services.knowledge import join_for_speech
    text = join_for_speech(["TMS", "Es una solución para el transporte.", "Planificación de rutas", "Asignación de vehículos"])
    assert text == "TMS: Es una solución para el transporte. Planificación de rutas, Asignación de vehículos."

def test_split_for_voice_keeps_first_sentences():
    from backend.app.services.knowledge import split_for_voice
    short, more = split_for_voice("TMS: Es una solución. Permite planificar rutas. Planificación de rutas, Asignación de vehículos.")
    assert short.startswith("TMS: Es una solución.")
    assert (short + " " + more).strip() == "TMS: Es una solución. Permite planificar rutas. Planificación de rutas, Asignación de vehículos."
