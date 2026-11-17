"""FastAPI application: wiring, middleware, error handling, logging."""
import contextvars
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .ai.classification import build_classifier
from .ai.llm import LLMClient, build_llm
from .api import router
from .config import get_settings
from .db import get_engine
from .memory.rebuild import ensure_ready
from .memory.semantic import build_semantic_memory
from .ratelimit import RateLimiter
from .services.tickets import DomainError

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("httpx", "httpx2"):  # their INFO lines would log full request URLs
        logging.getLogger(name).setLevel(logging.WARNING)


def create_app(llm: LLMClient | None = None, memory: Any = None) -> FastAPI:
    """``memory`` is a SemanticMemory; tests inject an in-memory one, the server opens the persistent store."""
    settings = get_settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("supportflow")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm = llm or build_llm(settings)
        app.state.memory = memory
        if memory is None:
            try:
                app.state.memory = build_semantic_memory(settings)
                with Session(get_engine()) as db:
                    ensure_ready(db, app.state.memory)  # seed the KB, and restore learned memory if the store was wiped
            except Exception:  # noqa: BLE001 - run without semantic memory rather than not at all
                log.exception("semantic memory unavailable; classifying without it")
        app.state.classifier = build_classifier(app.state.llm, app.state.memory)
        stats = app.state.memory.stats() if app.state.memory is not None else "off"
        log.info("ready: llm=%s semantic_memory=%s", app.state.llm.model, stats)
        yield

    app = FastAPI(title="SupportFlow AI", version="0.2.0", lifespan=lifespan)

    limiter = RateLimiter(settings.rate_limit_ai_per_10min, settings.rate_limit_writes_per_10min)
    app.state.limiter = limiter

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        token = request_id.set(request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8])
        started = time.perf_counter()
        wait = limiter.check(request)
        if wait is not None:
            mins = max(1, round(wait / 60))
            response = JSONResponse(status_code=429, headers={"Retry-After": str(wait)},
                                    content={"error": f"This public demo allows a limited number of actions per visitor. Try again in about {mins} minute{'s' if mins != 1 else ''}."})
        else:
            response = await call_next(request)
        # method, path, status and duration only: ticket text is never logged
        log.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id.get()
        request_id.reset(token)
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"error": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "Invalid request", "details": details})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "Internal error", "requestId": request_id.get()})

    app.include_router(router)
    # Added last so it is the outermost layer: every response, a 429 from the limiter included, carries CORS headers.
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["Content-Type", "X-Agent-Name", "X-Agent-Role"], expose_headers=["Retry-After", "X-Request-ID"])
    return app


app = create_app()
