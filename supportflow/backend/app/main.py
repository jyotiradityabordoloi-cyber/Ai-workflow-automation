"""FastAPI application: wiring, middleware, error handling, logging."""
import contextvars
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .ai.classification import build_classifier
from .ai.llm import LLMClient, build_llm
from .api import router
from .config import get_settings
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
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines would log full request URLs


def create_app(llm: LLMClient | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("supportflow")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm = llm or build_llm(settings)
        app.state.classifier = build_classifier(app.state.llm)
        log.info("ready: llm=%s", app.state.llm.model)
        yield

    app = FastAPI(title="SupportFlow AI", version="0.2.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["Content-Type", "X-Agent-Name", "X-Agent-Role"])

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        token = request_id.set(request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8])
        started = time.perf_counter()
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
    return app


app = create_app()
