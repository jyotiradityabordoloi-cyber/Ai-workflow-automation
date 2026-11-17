r"""Module 1 classification pipeline as a LangGraph state graph.

    START -> precheck -> recall --(readable)--> classify --> apply_rules -> END
                                \--(unsupported/too short)--> fallback --/

* precheck: deterministic language / length check; unsupported input never reaches the LLM.
* recall: agent memory. The caller passes episodic history (this customer's earlier tickets); this node adds
  semantic memory: agent corrections on near-identical tickets (sent to the model) and similar resolved
  problems (recorded for the agent and for drafting, not sent to the classifier). Memory failures degrade to
  "no memory", never to a failed classification.
* classify: LLM call with a JSON-Schema response format, then strict Pydantic validation.
  An invalid reply is retried once with the validation error; if the LLM is unavailable the
  ticket gets a safe fallback analysis instead of an exception.
* apply_rules: Module 4 flags (manual / senior / manager review), computed in code.

Steps 3 and 4 add drafting and escalation nodes to the same graph style.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from ..config import get_settings
from ..schemas import ClassificationOutput
from .llm import LLMClient, LLMError
from .rules import compute_flags, language_issue

log = logging.getLogger("supportflow.classify")

FALLBACK_SUMMARY = "Insufficient information to classify. Recommend manual review."

SYSTEM_PROMPT = """You are a support ticket classifier for a B2B SaaS product. Read the customer's message and return ONLY a JSON object with:
- language: the ISO 639-1 code of the language the message is written in (e.g. "en", "de", "es")
- category: one of billing, bug, feature_request, account, other
- priority: P1, P2 or P3
- sentiment: positive, neutral, frustrated or angry
- confidence: a number from 0 to 1, the probability that your category is correct
- summary: at most two sentences an agent can scan in five seconds; facts only, no advice

Category definitions: billing = charges, invoices, prices, plans, seats, refunds, payment methods; bug = the product behaves incorrectly; feature_request = asks for a capability the product does not have; account = login, passwords, users, roles, ownership, security, data deletion, compliance documents; other = sales, partnerships or anything else. A "how do I..." question about existing functionality belongs to the area it is about (adding a user = account), not feature_request.
Priority: P1 = service down or broken for many users, security incident, money taken wrongly, or an angry customer who has already chased; P2 = broken for one user or team with impact, account access problems, billing questions that need action; P3 = how-to questions, feature requests, minor cosmetic issues.
Sentiment: angry = hostile or threatening language, ALL CAPS, ultimatums, words like unacceptable; frustrated = annoyed or under pressure but civil; neutral = matter-of-fact; positive = thanks or enthusiasm. Urgency alone is not anger.

If the message is too short, ambiguous, or not in English, return category "other", priority "P2", sentiment "neutral", confidence 0.3 and summary "Insufficient information to classify. Recommend manual review."

The input can also carry memory:
- customer_history: this customer's earlier tickets, newest first. Use it only to judge priority and sentiment (a customer chasing the same unresolved problem again is more urgent and more frustrated). Never copy a category from it: classify the current message.
- agent_corrections: earlier tickets very similar to this one that a human agent re-classified after the AI got them wrong. If the current message is the same kind of request, follow the agent's category and priority.

Example message: "I've been charged twice this month and I've sent 3 emails already. This is unacceptable."
Example output: {"language": "en", "category": "billing", "priority": "P1", "sentiment": "angry", "confidence": 0.95, "summary": "Customer reports double billing this month. Has attempted contact 3 times without resolution."}"""

SCHEMA = ClassificationOutput.model_json_schema()


class ClassifyState(TypedDict, total=False):
    subject: str
    body: str
    ticket_id: str | None
    history: list[str]                 # episodic memory, supplied by the caller
    corrections: list[dict[str, Any]]  # semantic memory, filled by recall
    knowledge: list[dict[str, Any]]
    precheck_issue: str | None
    output: dict[str, Any]
    attempts: int
    error: str | None
    model: str
    latency_ms: int
    flags: list[dict[str, str]]


def _fallback_output(confidence: float = 0.0) -> dict[str, Any]:
    return {"language": None, "category": "other", "priority": "P2", "sentiment": "neutral", "confidence": confidence, "summary": FALLBACK_SUMMARY}


def user_message(state: ClassifyState) -> str:
    """The classifier's input. Memory keys appear only when there is memory, so a ticket with none is sent
    exactly as before the memory step existed."""
    payload: dict[str, Any] = {"subject": state.get("subject", ""), "message": state["body"]}
    if state.get("history"):
        payload["customer_history"] = state["history"]
    if state.get("corrections"):
        payload["agent_corrections"] = [
            {"message": c["excerpt"], "ai_said": f"{c['ai']['category']} {c['ai']['priority']}",
             "agent_set": f"{c['agent']['category']} {c['agent']['priority']}"} for c in state["corrections"]]
    return json.dumps(payload, ensure_ascii=False)


def build_classifier(llm: LLMClient, memory: Any = None):
    """``memory`` is a SemanticMemory (or None: no semantic recall, e.g. in the evaluation harness)."""
    settings = get_settings()

    def precheck(state: ClassifyState) -> ClassifyState:
        return {"precheck_issue": language_issue(f"{state.get('subject', '')} {state['body']}".strip())}

    def recall(state: ClassifyState) -> ClassifyState:
        # An unreadable message has no meaning an English embedder could match: skip semantic recall.
        if memory is None or state.get("precheck_issue"):
            return {"corrections": [], "knowledge": []}
        text = f"{state.get('subject', '')}. {state['body']}"
        try:
            return {
                "corrections": memory.search_corrections(text, k=2, min_similarity=settings.correction_min_similarity,
                                                         exclude_id=state.get("ticket_id")),
                "knowledge": memory.search_knowledge(text, k=3, min_similarity=settings.knowledge_min_similarity,
                                                     exclude_id=state.get("ticket_id")),
            }
        except Exception as e:  # noqa: BLE001 - memory is an aid; classification must not depend on it
            log.warning("semantic recall failed, classifying without it: %s", e)
            return {"corrections": [], "knowledge": []}

    def classify(state: ClassifyState) -> ClassifyState:
        user = user_message(state)
        started = time.perf_counter()
        attempts, feedback = 0, ""
        for attempts in (1, 2):
            try:
                res = llm.complete_json(SYSTEM_PROMPT, user + feedback, SCHEMA, "ticket_classification")
            except LLMError as e:
                log.warning("classification LLM failure: %s", e)
                return {"output": _fallback_output(), "error": f"LLM unavailable: {e}", "attempts": attempts,
                        "model": llm.model, "latency_ms": int((time.perf_counter() - started) * 1000)}
            try:
                out = ClassificationOutput.model_validate(res.data)
                # Model latency excludes client-side rate-limit pacing, which says nothing about the model.
                total = int((time.perf_counter() - started) * 1000)
                return {"output": out.model_dump(), "error": None, "attempts": attempts, "model": res.model,
                        "latency_ms": res.latency_ms or max(total - res.waited_ms, 0)}
            except ValidationError as e:
                problems = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'root'}: {x['msg']}" for x in e.errors())
                log.warning("classification output failed validation (attempt %d): %s", attempts, problems)
                feedback = f"\n\nYour previous reply was invalid ({problems}). Return only the JSON object."
        return {"output": _fallback_output(), "error": "LLM output failed schema validation twice", "attempts": attempts,
                "model": llm.model, "latency_ms": int((time.perf_counter() - started) * 1000)}

    def fallback(state: ClassifyState) -> ClassifyState:
        return {"output": _fallback_output(), "error": None, "attempts": 0, "model": "precheck (no LLM call)", "latency_ms": 0}

    def apply_rules(state: ClassifyState) -> ClassifyState:
        o = state["output"]
        flags = compute_flags(f"{state.get('subject', '')} {state['body']}", confidence=o["confidence"], priority=o["priority"],
                              sentiment=o["sentiment"], precheck_issue=state.get("precheck_issue"),
                              llm_unavailable=bool(state.get("error")), language=o.get("language"))
        return {"flags": [f.model_dump() for f in flags]}

    g = StateGraph(ClassifyState)
    g.add_node("precheck", precheck)
    g.add_node("recall", recall)
    g.add_node("classify", classify)
    g.add_node("fallback", fallback)
    g.add_node("apply_rules", apply_rules)
    g.add_edge(START, "precheck")
    g.add_edge("precheck", "recall")
    g.add_conditional_edges("recall", lambda s: "fallback" if s.get("precheck_issue") else "classify", ["fallback", "classify"])
    g.add_edge("classify", "apply_rules")
    g.add_edge("fallback", "apply_rules")
    g.add_edge("apply_rules", END)
    return g.compile()
