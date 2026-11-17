import pytest
from pydantic import ValidationError

from app.ai.rules import compute_flags, language_issue, manager_keywords
from app.schemas import ClassificationOutput


def types(flags):
    return {f.type for f in flags}


def test_language_issue():
    assert language_issue("help") == "Too short to classify reliably"
    assert "non-Latin" in language_issue("मेरा खाता लॉक हो गया है, कृपया मदद करें")
    assert language_issue("The dashboard returns 500 errors for everyone") is None


def test_manager_keywords_match_word_forms():
    assert manager_keywords("We will issue a CHARGEBACK and call our lawyers; refunded?") == ["chargeback", "lawyer", "refund"]
    assert manager_keywords("legally speaking") == ["legal"]
    assert manager_keywords("thanks for the fix") == []


@pytest.mark.parametrize("conf,pri,sent,pre,expected", [
    (0.95, "P2", "neutral", None, set()),
    (0.69, "P2", "neutral", None, {"manual_review"}),
    (0.70, "P2", "neutral", None, set()),  # threshold is "below 0.7", so 0.7 passes
    (0.95, "P1", "angry", None, {"senior_agent"}),
    (0.95, "P2", "angry", None, set()),
    (0.95, "P2", "neutral", "Too short to classify reliably", {"manual_review"}),
])
def test_compute_flags(conf, pri, sent, pre, expected):
    assert types(compute_flags("my screen is broken", confidence=conf, priority=pri, sentiment=sent, precheck_issue=pre)) == expected


def test_manager_flag_from_text():
    flags = compute_flags("refund me or I call my lawyer", confidence=0.9, priority="P2", sentiment="frustrated", precheck_issue=None)
    assert types(flags) == {"manager_review"}


def test_llm_unavailable_forces_manual_review():
    flags = compute_flags("x y z w", confidence=0.0, priority="P2", sentiment="neutral", precheck_issue=None, llm_unavailable=True)
    assert [f.reason for f in flags] == ["AI classification unavailable"]


VALID = {"language": "en", "category": "billing", "priority": "P1", "sentiment": "angry", "confidence": 0.9, "summary": "Double charge."}


def test_schema_accepts_valid_and_truncates_to_two_sentences():
    out = ClassificationOutput.model_validate({**VALID, "summary": "One. Two! Three? Four."})
    assert out.summary == "One. Two!"


@pytest.mark.parametrize("patch", [
    {"category": "refunds"}, {"priority": "P0"}, {"sentiment": "furious"}, {"confidence": 1.4}, {"confidence": -0.1},
    {"summary": ""}, {"extra_field": "x"},
])
def test_schema_rejects_invalid(patch):
    with pytest.raises(ValidationError):
        ClassificationOutput.model_validate({**VALID, **patch})


@pytest.mark.parametrize("text,lang", [
    ("Funktioniert nicht mehr seit dem Update, bitte dringend helfen.", "de"),
    ("No puedo iniciar sesión desde ayer, me dice que mi contraseña es incorrecta.", "es"),
    ("Bonjour, je n'arrive pas à me connecter depuis ce matin.", "fr"),
    ("The export to Excel is stuck at 99% since this morning and we need it.", "en"),
    ("Our CSV import fails at row 1,200 with an invalid date format.", "en"),
])
def test_detect_language(text, lang):
    from app.ai.rules import detect_language
    assert detect_language(text) == lang


def test_non_english_latin_script_goes_to_manual_review():
    assert language_issue("Funktioniert nicht mehr seit dem Update, bitte dringend helfen.") == "Unsupported language (de)"


def test_model_reported_language_is_a_backstop():
    flags = compute_flags("Some message text here", confidence=0.95, priority="P2", sentiment="neutral", precheck_issue=None, language="pt")
    assert [f.reason for f in flags] == ["Unsupported language (pt, reported by model)"]


def test_schema_requires_language_code():
    with pytest.raises(ValidationError):
        ClassificationOutput.model_validate({**VALID, "language": "English"})
