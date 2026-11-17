from app.ai.classification import FALLBACK_SUMMARY, build_classifier
from app.ai.llm import FakeLLM

GOOD = {"language": "en", "category": "bug", "priority": "P2", "sentiment": "neutral", "confidence": 0.9, "summary": "Search fails on apostrophes."}


def run(llm, body="Search returns nothing for O'Brien, tried quoting it.", subject="Search bug"):
    return build_classifier(llm).invoke({"subject": subject, "body": body})


def test_happy_path():
    llm = FakeLLM([GOOD])
    s = run(llm)
    assert s["output"]["category"] == "bug" and s["attempts"] == 1 and s["error"] is None
    assert s["flags"] == [] and llm.calls == 1


def test_precheck_skips_llm_for_unsupported_input():
    llm = FakeLLM([GOOD])
    s = run(llm, body="help", subject="")
    assert llm.calls == 0
    assert s["output"]["summary"] == FALLBACK_SUMMARY
    assert [f["type"] for f in s["flags"]] == ["manual_review"]


def test_invalid_output_is_retried_once_with_feedback():
    llm = FakeLLM([{"language": "en", "category": "refunds", "priority": "P2", "sentiment": "neutral", "confidence": 0.9, "summary": "x"}, GOOD])
    s = run(llm)
    assert s["attempts"] == 2 and s["output"]["category"] == "bug" and llm.calls == 2


def test_invalid_twice_falls_back_to_manual_review():
    bad = {"category": "nope"}
    s = run(FakeLLM([bad, bad]))
    assert s["error"] == "LLM output failed schema validation twice"
    assert s["output"]["category"] == "other"
    assert [f["reason"] for f in s["flags"]] == ["AI classification unavailable"]


def test_llm_outage_falls_back_instead_of_raising():
    s = run(FakeLLM(fail=True))
    assert s["error"].startswith("LLM unavailable")
    assert [f["type"] for f in s["flags"]] == ["manual_review"]


def test_low_confidence_and_angry_p1_flags():
    s = run(FakeLLM([{**GOOD, "confidence": 0.4}]))
    assert [f["type"] for f in s["flags"]] == ["manual_review"]
    s = run(FakeLLM([{**GOOD, "priority": "P1", "sentiment": "angry"}]))
    assert [f["type"] for f in s["flags"]] == ["senior_agent"]


def test_german_ticket_never_reaches_llm():
    llm = FakeLLM([GOOD])
    s = run(llm, body="Funktioniert nicht mehr seit dem Update, bitte dringend helfen.", subject="")
    assert llm.calls == 0 and s["flags"][0]["reason"] == "Unsupported language (de)"


def test_language_backstop_when_precheck_misses():
    s = run(FakeLLM([{**GOOD, "language": "pt", "confidence": 0.9}]))
    assert [f["type"] for f in s["flags"]] == ["manual_review"]
