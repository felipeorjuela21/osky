from backend.app.services.smalltalk import match_smalltalk, strip_greeting

def test_intents():
    assert match_smalltalk("¡Hola!")["intent"] == "greeting"
    assert match_smalltalk("Hola Osky")["intent"] == "greeting"
    assert match_smalltalk("muchas gracias")["intent"] == "thanks"
    assert match_smalltalk("¿Quién eres?")["intent"] == "identity"
    assert match_smalltalk("adiós, hasta luego")["intent"] == "goodbye"
    assert match_smalltalk("¿Cómo estás?")["intent"] == "how_are_you"

def test_real_questions_are_not_smalltalk():
    assert match_smalltalk("hola, ¿qué es TMS?") is None
    assert match_smalltalk("¿qué es Pricing?") is None

def test_strip_greeting():
    assert strip_greeting("Hola Osky, ¿qué es TMS?") == "¿qué es TMS?"
    assert strip_greeting("Buenos días, ¿qué es TMS?") == "¿qué es TMS?"
    assert strip_greeting("¿qué es TMS?") == "¿qué es TMS?"

def test_stt_term_corrections():
    from backend.app.services.stt import correct_terms
    assert correct_terms("¿Qué esté meces?") == "¿Qué es TMS?"
    assert correct_terms("Que es pricy.") == "Que es Pricing."
    assert correct_terms("el asistente de Celubeb") == "el asistente de CeluWeb"
    assert correct_terms("Tienen chatbot") == "Tienen Chat Bot"
    assert correct_terms("Quiero saber cómo los contacto") == "Quiero saber cómo los contacto"
