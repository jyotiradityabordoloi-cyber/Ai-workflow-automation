"""LLM access behind a small interface, so the graph can use Groq in production and a fake in tests.

Groq exposes an OpenAI-compatible API. We request JSON constrained by a JSON Schema, then
validate it again with Pydantic: the schema is a strong hint to the model, not a guarantee.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ..config import Settings

log = logging.getLogger("supportflow.llm")


class LLMError(RuntimeError):
    """The LLM could not produce an answer (network, auth, rate limit exhausted, bad JSON)."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0  # the successful HTTP call only (excludes rate-limit pacing and retries)
    waited_ms: int = 0  # time spent pacing / backing off before that call


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> LLMResult: ...


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no JSON object in reply", text, 0)


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is not set")
        self.model = settings.llm_model
        self._s = settings
        self._http = httpx.Client(base_url=settings.llm_base_url, timeout=settings.llm_timeout_s,
                                  headers={"Authorization": f"Bearer {settings.groq_api_key}"})
        self._lock = threading.Lock()
        self._window: deque[tuple[float, int]] = deque()
        self._use_schema = True

    def _pace(self, est_tokens: int) -> None:
        """Client-side tokens-per-minute pacing so bursts don't hit the provider's rate limit."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._window and now - self._window[0][0] > 60:
                    self._window.popleft()
                if not self._window or sum(t for _, t in self._window) + est_tokens <= self._s.llm_tpm_limit:
                    self._window.append((now, est_tokens))
                    return
                wait = 60 - (now - self._window[0][0]) + 0.25
            time.sleep(wait)

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> LLMResult:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last: Exception | None = None
        t_start = time.perf_counter()
        for attempt in range(1, 7):
            payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1}
            if self._use_schema:
                payload["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema}}
            else:
                payload["response_format"] = {"type": "json_object"}
            if "gpt-oss" in self.model:
                payload["reasoning_effort"] = self._s.llm_reasoning_effort
            self._pace(len(json.dumps(messages)) // 4 + 600)
            t_call = time.perf_counter()
            try:
                r = self._http.post("/chat/completions", json=payload)
            except httpx.HTTPError as e:
                last = LLMError(f"network error: {type(e).__name__}")
                time.sleep(min(2 * attempt, 10))
                continue
            if r.status_code == 200:
                body = r.json()
                try:
                    data = parse_json(body["choices"][0]["message"]["content"] or "")
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    raise LLMError(f"reply was not JSON: {e}") from e
                usage = body.get("usage") or {}
                now = time.perf_counter()
                return LLMResult(data, body.get("model", self.model), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                                 latency_ms=int((now - t_call) * 1000), waited_ms=int((t_call - t_start) * 1000))
            text = r.text[:400]
            if r.status_code == 400 and self._use_schema and ("json_schema" in text or "response_format" in text):
                log.warning("provider rejected json_schema; falling back to json_object mode")
                self._use_schema = False
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                hint = re.search(r"try again in ([\d.]+)(ms|s)", text)
                delay = float(hint.group(1)) / (1000 if hint.group(2) == "ms" else 1) + 1 if hint else min(2 ** attempt, 30)
                log.warning("LLM %s, retrying in %.1fs (attempt %d)", r.status_code, delay, attempt)
                last = LLMError(f"provider returned {r.status_code}")
                time.sleep(delay)
                continue
            # 401/403/404 etc.: retrying won't help. Never include the raw body: it can contain account ids.
            raise LLMError(f"provider returned {r.status_code}")
        raise last or LLMError("LLM call failed")


class FakeLLM:
    """Deterministic keyword classifier used by tests and when no API key is configured."""

    model = "fake-llm (keyword rules)"

    def __init__(self, responses: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.responses = list(responses or [])
        self.fail = fail
        self.calls = 0
        self.prompts: list[str] = []  # every user message received, so tests can check what memory was shown

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> LLMResult:
        self.calls += 1
        self.prompts.append(user)
        if self.fail:
            raise LLMError("fake failure")
        if self.responses:
            return LLMResult(self.responses.pop(0), self.model)
        try:  # keyword rules read the current message only, never the recalled memory
            payload = json.loads(user.split("\n\nYour previous reply")[0])
            text = f"{payload.get('subject', '')} {payload.get('message', '')}".lower()
        except (json.JSONDecodeError, AttributeError):
            text = user.lower()
        rules = [("billing", r"charg|invoice|bill|refund|payment|price|seat"), ("bug", r"error|crash|fail|blank|broken|delay|wrong"),
                 ("feature_request", r"would (love|be great)|any plan|dark mode|endpoint"), ("account", r"password|owner|access|delete|admin|login")]
        cat = next((c for c, rx in rules if re.search(rx, text)), "other")
        angry = bool(re.search(r"unacceptable|\bnow\b|lawyer|embarrass", text))
        return LLMResult({"language": "en", "category": cat, "priority": "P1" if angry else "P2", "sentiment": "angry" if angry else "neutral",
                          "confidence": 0.85, "summary": "Keyword-based stand-in summary."}, self.model)


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake" or not settings.groq_api_key:
        if settings.llm_provider != "fake":
            log.warning("GROQ_API_KEY missing: using the fake keyword classifier")
        return FakeLLM()
    return GroqClient(settings)
