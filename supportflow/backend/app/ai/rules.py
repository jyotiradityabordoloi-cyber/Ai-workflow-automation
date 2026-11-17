"""Module 4: safety and fallback rules. Deterministic code; the LLM cannot override them."""
import re

from ..config import get_settings
from ..schemas import ReviewFlag


_STOPWORDS: dict[str, set[str]] = {
    "en": set("the and is are was to of in it not we you for on with this my our since have has can please but they".split()),
    "es": set("el la los las de del que y en no se por con una mi desde pero es para me lo está".split()),
    "fr": set("le la les de des et est je ne pas pour que une avec mon depuis il nous vous ce sur".split()),
    "de": set("der die das und ist nicht ich wir mit seit dem den ein eine bitte es auf für sich mehr noch".split()),
    "pt": set("o a os as de que e não em um uma com para meu desde por está é".split()),
    "it": set("il la di che e non un una per con mio da sono gli le del è".split()),
    "nl": set("de het en van een niet ik we met voor sinds is dat op zijn".split()),
}


def detect_language(text: str) -> str | None:
    """Cheap, explainable language guess from function words. Returns an ISO code or None if unsure."""
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    if len(words) < 4:
        return None
    scores = {lang: sum(w in sw for w in words) for lang, sw in _STOPWORDS.items()}
    other, best = max(((k, v) for k, v in scores.items() if k != "en"), key=lambda kv: kv[1])
    if scores["en"] >= best:
        return "en" if scores["en"] else None
    return other if best >= 2 else None


def language_issue(text: str) -> str | None:
    """Return why a ticket can't be classified reliably, or None."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "No readable text"
    non_latin = sum(1 for c in letters if ord(c) > 0x24F) / len(letters)
    if non_latin > 0.3:
        return "Unsupported language (non-Latin script)"
    lang = detect_language(text)
    if lang and lang != "en":
        return f"Unsupported language ({lang})"
    if len(text.split()) < 4:
        return "Too short to classify reliably"
    return None


def manager_keywords(text: str) -> list[str]:
    kws = get_settings().manager_keywords
    rx = re.compile(r"\b(" + "|".join(map(re.escape, kws)) + r")\w*", re.I)
    return sorted({m.group(1).lower() for m in rx.finditer(text)})


def compute_flags(text: str, *, confidence: float, priority: str, sentiment: str, precheck_issue: str | None,
                  llm_unavailable: bool = False, language: str | None = "en") -> list[ReviewFlag]:
    threshold = get_settings().confidence_threshold
    flags: list[ReviewFlag] = []
    if precheck_issue:
        flags.append(ReviewFlag(type="manual_review", reason=precheck_issue))
    elif language and language != "en":
        # Backstop: the model reports the language; anything non-English is not trusted.
        flags.append(ReviewFlag(type="manual_review", reason=f"Unsupported language ({language}, reported by model)"))
    elif llm_unavailable:
        flags.append(ReviewFlag(type="manual_review", reason="AI classification unavailable"))
    elif confidence < threshold:
        flags.append(ReviewFlag(type="manual_review", reason=f"Confidence {confidence:.2f} is below {threshold}"))
    if sentiment == "angry" and priority == "P1":
        flags.append(ReviewFlag(type="senior_agent", reason="Angry customer on a P1 ticket"))
    kws = manager_keywords(text)
    if kws:
        flags.append(ReviewFlag(type="manager_review", reason=f"Mentions {', '.join(kws)}"))
    return flags
