"""Live demo server for the Nimbus3D ticket router (standard library only).

    py server.py                 # http://localhost:8000
    PORT=8080 py server.py

Endpoints
    GET  /               demo page (web/index.html)
    GET  /api/showcase   measured results shown on the page (web/showcase.json)
    POST /api/triage     {"subject": "...", "body": "...", "escalate": false} -> routing result
    GET  /healthz        liveness probe for the host

Safety for a public URL: per-IP and global daily rate limits, input size caps,
ticket text is never logged, and provider error details never reach the browser.
Without an API key the server runs the deterministic mock (clearly flagged as demo mode).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from awa.env import load_dotenv  # noqa: E402
from awa.llm import LLM, LLMError  # noqa: E402
from awa.orchestrator import RunContext  # noqa: E402
from awa.workflows import ticket_triage  # noqa: E402

load_dotenv(ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("server")

CONFIG = json.loads((ROOT / "config" / "tickets_teams.json").read_text(encoding="utf-8"))
HISTORY = ROOT / CONFIG["history_file"]
WEB = ROOT / "web"

MAX_SUBJECT, MAX_BODY = 200, 2000
PER_IP_PER_MIN = int(os.environ.get("DEMO_PER_IP_PER_MIN", 6))
PER_IP_PER_DAY = int(os.environ.get("DEMO_PER_IP_PER_DAY", 40))
GLOBAL_PER_DAY = int(os.environ.get("DEMO_GLOBAL_PER_DAY", 500))


def make_llm() -> tuple[LLM, bool]:
    provider = os.environ.get("LLM_PROVIDER", "groq")
    try:
        return LLM(provider), False
    except LLMError as e:
        log.warning("LLM unavailable (%s); running in demo mode with the mock provider", e)
        return LLM("mock"), True


LLM_CLIENT, DEMO_MODE = make_llm()


class RateLimiter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.minute: dict[str, deque] = defaultdict(deque)
        self.day: dict[str, int] = defaultdict(int)
        self.global_day = 0
        self.day_key = time.strftime("%Y-%m-%d")

    def check(self, ip: str) -> str | None:
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            if today != self.day_key:
                self.day.clear()
                self.global_day, self.day_key = 0, today
            now = time.monotonic()
            q = self.minute[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= PER_IP_PER_MIN:
                return "Too many requests: please wait a minute and try again."
            if self.day[ip] >= PER_IP_PER_DAY:
                return "Daily limit for your connection reached. Try again tomorrow."
            if self.global_day >= GLOBAL_PER_DAY:
                return "The demo has reached today's free-tier budget. Try again tomorrow."
            q.append(now)
            self.day[ip] += 1
            self.global_day += 1
            return None


LIMITER = RateLimiter()


def triage_one(subject: str, body: str, escalate: bool) -> dict:
    ticket = {"id": "LIVE-1", "created_at": time.strftime("%Y-%m-%dT%H:%M"), "customer": "Website visitor",
              "plan": "Demo", "subject": subject, "body": body, "agent_escalate": escalate}
    with tempfile.TemporaryDirectory() as tmp:
        ctx = RunContext(run_id="live", out_dir=Path(tmp), llm=LLM_CLIENT,
                         config={"tickets": CONFIG, "batch_size": 1, "llm_concurrency": 1})
        run = ticket_triage.build_workflow(None, HISTORY, tickets=[ticket]).run(ctx, max_workers=4)
    tri = ctx.results.get("triage", [{}])[0]
    return {
        "ok": run["status"] == "success",
        "demo_mode": DEMO_MODE,
        "model": LLM_CLIENT.describe(),
        "result": {k: tri.get(k) for k in ("queue", "manager_review", "reasons", "confidence", "ai")},
        "ai_error": bool(ctx.metrics.get("ai_batch_failures") or ctx.metrics.get("ai_missing")),
        "similar": ctx.results.get("retrieve", {}).get("LIVE-1", []),
        "draft": ctx.results.get("draft_replies", {}).get("LIVE-1"),
        "slack": ctx.results.get("escalation_briefs", {}).get("LIVE-1"),
        "timings": {"total_s": run["total_seconds"],
                    "tasks": [{"name": t["name"], "start": t["start_offset"], "seconds": t["seconds"], "status": t["status"]}
                              for t in run["tasks"]]},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "nimbus3d-demo"

    def log_message(self, fmt: str, *args) -> None:  # keep access logs short; never log bodies
        log.info("%s %s", self.command, self.path.split("?")[0])

    def client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def send(self, code: int, payload: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "public, max-age=300")
        self.end_headers()
        self.wfile.write(payload)

    def json(self, code: int, obj: dict) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self.send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/showcase":
            self.send(200, (WEB / "showcase.json").read_bytes(), "application/json; charset=utf-8")
        elif path == "/healthz":
            self.json(200, {"ok": True, "demo_mode": DEMO_MODE, "model": LLM_CLIENT.describe()})
        else:
            self.json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/api/triage":
            return self.json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 10_000:
                return self.json(413, {"error": "Request too large."})
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self.json(400, {"error": "Send JSON: {\"subject\": \"...\", \"body\": \"...\"}"})
        subject = str(data.get("subject", "")).strip()[:MAX_SUBJECT]
        body = str(data.get("body", "")).strip()
        if not body:
            return self.json(400, {"error": "Please write a message."})
        if len(body) > MAX_BODY:
            return self.json(400, {"error": f"Message too long (max {MAX_BODY} characters)."})
        blocked = LIMITER.check(self.client_ip())
        if blocked:
            return self.json(429, {"error": blocked})
        t0 = time.perf_counter()
        try:
            out = triage_one(subject, body, bool(data.get("escalate")))
        except Exception:  # noqa: BLE001 - never leak internals to the browser
            log.exception("triage failed")
            return self.json(500, {"error": "Something went wrong routing that ticket. Please try again."})
        log.info("triaged %d chars in %.1fs -> %s", len(body), time.perf_counter() - t0,
                 (out["result"].get("ai") or {}).get("category", out["result"].get("queue")))
        self.json(200, out)


def main() -> None:
    port = int(os.environ.get("PORT", 8000))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("serving on http://localhost:%d (model: %s%s)", port, LLM_CLIENT.describe(), ", DEMO MODE" if DEMO_MODE else "")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
