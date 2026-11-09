"""Whisper hallucination filter and read-aloud normalisation (no network)."""
from backend.app.services import stt, tts


# ---------- STT ----------

def test_url_only_is_dropped_but_question_about_site_is_kept():
    assert stt.is_hallucination("www.celuweb.com", 3.0)
    assert stt.is_hallucination("celuweb.com.", 3.0)
    assert not stt.is_hallucination("¿Es celuweb.com?", 3.0)
    assert not stt.is_hallucination("Visita celuweb.com para más información", 4.0)


def test_classic_whisper_inventions_always_dropped():
    assert stt.is_hallucination("Subtítulos realizados por la comunidad de Amara.org", 5.0)
    assert stt.is_hallucination("Gracias por ver el video", 5.0)


def test_short_closings_dropped_only_when_clip_short_or_unsure():
    for phrase in ["Gracias.", "¡Hasta la próxima!", "Y eso es todo", "Chao"]:
        assert stt.is_hallucination(phrase, 0.5), phrase
        assert stt.is_hallucination(phrase, 3.0, -1.4), phrase
        assert not stt.is_hallucination(phrase, 3.0, -0.2), phrase  # real, confident "gracias"
        assert not stt.is_hallucination(phrase, 3.0), phrase


def test_real_short_answers_survive():
    assert not stt.is_hallucination("Sí", 0.5, -0.9)
    assert not stt.is_hallucination("Ok", 0.5)
    assert not stt.is_hallucination("Quiero saber del TMS", 0.5)


def test_keep_segment_uses_no_speech_and_logprob():
    assert not stt.keep_segment(0.8, -0.1)
    assert not stt.keep_segment(0.5, -1.5)
    assert stt.keep_segment(0.5, -0.4)
    assert stt.keep_segment(0.1, -1.5)
    assert stt.keep_segment(0.5, None)


def test_transcribe_log_has_no_transcript(monkeypatch, caplog):
    monkeypatch.setattr(stt.settings.__class__, "effective_stt", property(lambda self: "groq"))
    monkeypatch.setattr(stt, "_transcribe_groq", lambda a, c: ("mi número es 300 123 4567", 2.0, -0.2))
    with caplog.at_level("INFO", logger="uvicorn.error"):
        result = stt.transcribe(b"x")
    assert result["text"] == "mi número es 300 123 4567"
    assert "300" not in caplog.text and "chars" in caplog.text


# ---------- TTS: speakable ----------

def test_acronyms_spelled_out():
    assert tts.speakable("Usa el TMS y el CRM.") == "Usa el te eme ese y el ce erre eme."
    assert tts.speakable("Es B2B,") == "Es be tu be,"
    assert tts.speakable("(GPS)") == "(ge pe ese)"


def test_urls():
    assert tts.speakable("Entra a www.celuweb.com.") == "Entra a celuweb punto com."
    assert tts.speakable("https://celuweb.com/contacto") == "celuweb punto com"
    assert tts.speakable("celuweb.com.co") == "celuweb punto com punto co"


def test_phone_numbers_grouped():
    assert tts.speakable("Llama al 300 123 4567 hoy") == "Llama al 300, 123, 45, 67 hoy"
    assert tts.speakable("Es 3001234567.") == "Es 300, 123, 45, 67."
    assert tts.speakable("+57 300 123 4567") == "más cincuenta y siete, 300, 123, 45, 67"


def test_percent():
    assert tts.speakable("Ahorra 20% al mes") == "Ahorra 20 por ciento al mes"
    assert tts.speakable("el 15,5%.") == "el 15,5 por ciento."


def test_plain_text_unchanged():
    text = "Hola, soy Osky. ¿En qué te ayudo?"
    assert tts.speakable(text) == text
    assert tts.speakable("TMSX no cambia") == "TMSX no cambia"


# ---------- TTS: captions stay aligned ----------

def _fake_words(spoken: str):
    return [{"text": w.strip(".,"), "start": i * 0.3, "duration": 0.25} for i, w in enumerate(spoken.split())]


def test_realign_maps_spoken_words_back_to_shown_words():
    text = "El TMS ayuda, llama al 300 123 4567 ya"
    words = _fake_words(tts.speakable(text))
    out = tts.realign_words(text, words)
    assert [w["text"] for w in out] == ["El", "TMS", "ayuda", "llama", "al", "300", "123", "4567", "ya"]
    assert out[-1]["start"] == words[-1]["start"]            # the tail is not shifted
    assert out[1]["start"] == words[1]["start"]               # TMS starts with "te"
    assert out[1]["start"] + out[1]["duration"] > words[3]["start"]  # ...and spans "te eme ese"
    assert all(a["start"] <= b["start"] for a, b in zip(out, out[1:]))


def test_realign_untouched_when_nothing_changes_or_counts_differ():
    words = _fake_words("hola mundo")
    assert tts.realign_words("hola mundo", words) is words
    # The engine split the spoken text differently: timings are estimated over the SHOWN words,
    # so the captions (indexed over the shown text) never run ahead.
    odd = _fake_words("uno dos")
    assert [w["text"] for w in tts.realign_words("el TMS", odd)] == ["el", "TMS"]
