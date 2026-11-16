"""One client for every free LLM provider.

Groq, Google Gemini, OpenRouter and Ollama all expose an OpenAI-compatible
`/chat/completions` endpoint, so a single stdlib HTTP client covers them all.
Switch provider with `--provider` or the LLM_PROVIDER env var; override the
model with LLM_MODEL.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
import urllib.error
import urllib.request
from typing import Any, Callable

PROVIDERS: dict[str, dict[str, Any]] = {
    # Free tier, very fast inference, strong open models. Recommended default.
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "tpm": 7500,  # free tier allows 8,000 tokens/minute for gpt-oss-120b; keep a margin
    },
    # Free tier via Google AI Studio key; good at structured JSON.
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
    # Many ":free" models behind one key; availability varies.
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "key_env": "OPENROUTER_API_KEY",
    },
    # 100% local and free, no key, data never leaves the machine.
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:3b",
        "key_env": None,
    },
    # Deterministic heuristics, no LLM at all. For tests/CI only.
    "mock": {"base_url": "", "model": "heuristic-mock", "key_env": None},
}


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating code fences and chatter."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no JSON object found", text, 0)


class LLM:
    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 180,
        temperature: float = 0.1,
    ) -> None:
        provider = provider or os.environ.get("LLM_PROVIDER") or "groq"
        if provider not in PROVIDERS:
            raise LLMError(f"Unknown provider '{provider}'. Choose from: {', '.join(PROVIDERS)}")
        spec = PROVIDERS[provider]
        self.provider = provider
        self.model = model or os.environ.get("LLM_MODEL") or spec["model"]
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or spec["base_url"]).rstrip("/")
        key_env = spec["key_env"]
        self.api_key = api_key or (os.environ.get(key_env) if key_env else None)
        if key_env and not self.api_key:
            raise LLMError(
                f"{key_env} is not set. Paste it into .env (free key: {spec.get('key_url', 'see .env.example')}) "
                "or run with --provider ollama."
            )
        self.timeout = timeout
        self.temperature = temperature
        self._json_mode = True
        self._lock = threading.Lock()
        self._window: deque[tuple[float, int]] = deque()  # (time, estimated tokens) sent in the last minute
        self.tpm = int(os.environ.get("LLM_TPM_LIMIT") or spec.get("tpm") or 0)
        self.stats = {
            "calls": 0,
            "failed_calls": 0,
            "retries": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "seconds": 0.0,
        }

    # ------------------------------------------------------------------ public
    def chat_json(
        self,
        system: str,
        user: str,
        mock: Callable[[], Any] | None = None,
        max_attempts: int = 4,
    ) -> Any:
        """Ask for a JSON object and return it parsed.

        `mock` is only used by the "mock" provider, so workflows stay testable
        without any model.
        """
        if self.provider == "mock":
            with self._lock:
                self.stats["calls"] += 1
            if mock is None:
                raise LLMError("mock provider needs a mock= callable")
            return mock()

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_err: Exception | None = None
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            }
            if self._json_mode:
                payload["response_format"] = {"type": "json_object"}
            if "gpt-oss" in self.model:
                # reasoning models: keep thinking short for extraction-style tasks (faster, fewer tokens)
                payload["reasoning_effort"] = os.environ.get("LLM_REASONING_EFFORT", "low")
            # ~4 chars per token for the prompt + a typical completion; calibrated on real Groq usage
            self._reserve(len(json.dumps(messages)) // 4 + 700)
            t0 = time.perf_counter()
            try:
                data = self._post(payload)
                content = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage") or {}
                with self._lock:
                    self.stats["calls"] += 1
                    self.stats["seconds"] += time.perf_counter() - t0
                    self.stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                    self.stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                return extract_json(content)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:500]
                last_err = LLMError(f"HTTP {e.code} from {self.provider}: {body}")
                if e.code == 400 and self._json_mode and "response_format" in body:
                    self._json_mode = False  # model does not support JSON mode; rely on prompt
                elif e.code in (429, 500, 502, 503, 504):
                    retry_after = e.headers.get("retry-after")
                    hinted = re.search(r"try again in ([\d.]+)(ms|s)", body)
                    if hinted:
                        delay = float(hinted.group(1)) / (1000 if hinted.group(2) == "ms" else 1) + 1
                    elif retry_after and retry_after.replace(".", "").isdigit():
                        delay = float(retry_after) + 1
                    else:
                        delay = 2.0 * 2 ** (attempt - 1)
                    if e.code == 429:
                        max_attempts = max(max_attempts, 8)  # rate limits are temporary: wait them out
                    time.sleep(min(delay, 60))
                else:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = LLMError(f"Cannot reach {self.provider} at {self.base_url}: {e}")
                time.sleep(2.0 * attempt)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                last_err = LLMError(f"Unparseable reply from {self.provider}: {e}")
                messages = messages[:2] + [
                    {"role": "user", "content": "Your previous reply was not valid JSON. Reply with ONLY the JSON object."}
                ]
            with self._lock:
                self.stats["retries"] += 1
        with self._lock:
            self.stats["failed_calls"] += 1
        raise last_err or LLMError("LLM call failed")

    def ping(self) -> str:
        """Cheap connectivity check used by `main.py providers`."""
        out = self.chat_json(
            "You reply with JSON only.",
            'Return {"ok": true}.',
            mock=lambda: {"ok": True},
            max_attempts=1,
        )
        return "ok" if isinstance(out, dict) and out.get("ok") else f"unexpected reply: {out!r}"

    def describe(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}

    # ----------------------------------------------------------------- private
    def _reserve(self, est_tokens: int) -> None:
        """Client-side tokens-per-minute pacing so parallel calls don't trip the provider's rate limit."""
        if not self.tpm:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                while self._window and now - self._window[0][0] > 60:
                    self._window.popleft()
                used = sum(t for _, t in self._window)
                if used + est_tokens <= self.tpm or not self._window:
                    self._window.append((now, est_tokens))
                    return
                wait = 60 - (now - self._window[0][0]) + 0.25
            with self._lock:
                self.stats["paced_seconds"] = round(self.stats.get("paced_seconds", 0) + wait, 1)
            time.sleep(wait)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "User-Agent": "awa/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
