"""Per-client sliding-window rate limits for a public demo (single process, in memory).

Two budgets per client IP over a 10-minute window: "ai" for requests that call the LLM (they spend the shared
Groq quota), and "writes" for every POST. Off when a limit is 0, the local default.
"""
from __future__ import annotations

import re
import time
from collections import deque

from fastapi import Request

WINDOW_S = 600
_ANALYZE = re.compile(r"^/api/tickets/[^/]+/analyze$")


def client_ip(request: Request) -> str:
    # Behind the host's proxy the address it appends last is the one it saw; earlier entries can be forged.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def calls_llm(request: Request) -> bool:
    path = request.url.path
    if path == "/api/tickets":
        return request.query_params.get("analyze", "true").lower() != "false"
    return bool(_ANALYZE.match(path))


class RateLimiter:
    def __init__(self, ai_per_window: int, writes_per_window: int, window_s: int = WINDOW_S, clock=time.monotonic) -> None:
        self.limits = {"ai": ai_per_window, "writes": writes_per_window}
        self.window_s, self.clock = window_s, clock
        self.hits: dict[tuple[str, str], deque[float]] = {}

    @property
    def enabled(self) -> bool:
        return any(self.limits.values())

    def check(self, request: Request) -> int | None:
        """Record the request; return seconds to wait if it is over a limit, else None."""
        if request.method != "POST" or not self.enabled:
            return None
        ip, now = client_ip(request), self.clock()
        buckets = ["writes"] + (["ai"] if calls_llm(request) else [])
        for b in buckets:
            limit = self.limits[b]
            if not limit:
                continue
            q = self.hits.setdefault((b, ip), deque())
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= limit:
                return int(self.window_s - (now - q[0])) + 1
        for b in buckets:
            if self.limits[b]:
                self.hits[(b, ip)].append(now)
        if len(self.hits) > 10_000:  # forget idle clients so memory stays bounded
            self.hits = {k: q for k, q in self.hits.items() if q and now - q[-1] < self.window_s}
        return None
