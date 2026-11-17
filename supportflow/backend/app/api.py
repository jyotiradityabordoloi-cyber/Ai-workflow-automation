"""HTTP routes. Thin: parse input, call the service layer, return schemas."""
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import BACKEND_DIR, get_settings
from .db import get_session
from .schemas import (AuditOut, DecisionIn, HealthOut, KnowledgeOut, MemoryStatsOut, ResolveIn, TicketCreate, TicketMemoryOut,
                      TicketOut)
from .services import tickets as svc

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_session)]


def get_actor(x_agent_name: Annotated[str, Header()] = "Alex Rivera",
              x_agent_role: Annotated[Literal["agent", "manager"], Header()] = "agent") -> svc.Actor:
    """Demo identity from headers. Replace with real authentication before any production use."""
    return svc.Actor(name=x_agent_name[:120], role=x_agent_role)


Actor = Annotated[svc.Actor, Depends(get_actor)]


def get_classifier(request: Request):
    return request.app.state.classifier


def get_memory(request: Request):
    return request.app.state.memory


@router.get("/health", response_model=HealthOut)
def health(db: DB, request: Request) -> HealthOut:
    s = get_settings()
    try:
        db.execute(text("select 1"))
        ok_db = True
    except Exception:  # noqa: BLE001 - health must never raise
        ok_db = False
    llm = request.app.state.llm
    return HealthOut(ok=ok_db, database=ok_db, llm_provider="fake" if llm.model.startswith("fake") else s.llm_provider,
                     llm_model=llm.model, llm_configured=not llm.model.startswith("fake"))


@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(db: DB) -> list[TicketOut]:
    return [svc.to_out(t) for t in svc.list_tickets(db)]


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketCreate, db: DB, actor: Actor, request: Request,
                  analyze: Annotated[bool, Query(description="Classify immediately after creating")] = True) -> TicketOut:
    t = svc.create_ticket(db, body, actor)
    if analyze:
        t = svc.analyze_ticket(db, t.id, get_classifier(request))
    return svc.to_out(t)


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str, db: DB) -> TicketOut:
    return svc.to_out(svc.get_ticket(db, ticket_id))


@router.post("/tickets/{ticket_id}/analyze", response_model=TicketOut)
def analyze(ticket_id: str, db: DB, request: Request) -> TicketOut:
    return svc.to_out(svc.analyze_ticket(db, ticket_id, get_classifier(request)))


@router.post("/tickets/{ticket_id}/decision", response_model=TicketOut)
def decide(ticket_id: str, body: DecisionIn, db: DB, actor: Actor, request: Request) -> TicketOut:
    return svc.to_out(svc.decide_classification(db, ticket_id, body, actor, get_memory(request)))


@router.post("/tickets/{ticket_id}/assign-senior", response_model=TicketOut)
def assign_senior(ticket_id: str, db: DB, actor: Actor) -> TicketOut:
    return svc.to_out(svc.assign_senior(db, ticket_id, actor))


@router.post("/tickets/{ticket_id}/manager-approval", response_model=TicketOut)
def manager_approval(ticket_id: str, db: DB, actor: Actor) -> TicketOut:
    return svc.to_out(svc.record_manager_approval(db, ticket_id, actor))


@router.post("/tickets/{ticket_id}/resolve", response_model=TicketOut)
def resolve(ticket_id: str, body: ResolveIn, db: DB, actor: Actor, request: Request) -> TicketOut:
    return svc.to_out(svc.resolve_ticket(db, ticket_id, body, actor, get_memory(request)))


@router.get("/tickets/{ticket_id}/memory", response_model=TicketMemoryOut)
def ticket_memory(ticket_id: str, db: DB, request: Request) -> TicketMemoryOut:
    """Episodic (this customer's earlier tickets) and semantic (similar fixes, agent corrections) memory for one ticket."""
    return svc.ticket_memory(db, ticket_id, get_memory(request))


@router.get("/memory/stats", response_model=MemoryStatsOut)
def memory_stats(db: DB, request: Request) -> MemoryStatsOut:
    return svc.memory_stats(db, get_memory(request))


@router.get("/knowledge", response_model=list[KnowledgeOut])
def knowledge(request: Request) -> list[KnowledgeOut]:
    """Everything in semantic memory's knowledge collection: curated articles and consolidated resolved tickets."""
    memory = get_memory(request)
    return [KnowledgeOut.model_validate(k) for k in memory.list_knowledge()] if memory is not None else []


@router.get("/knowledge/search", response_model=list[KnowledgeOut])
def knowledge_search(request: Request, q: Annotated[str, Query(min_length=1, max_length=2000)],
                     k: Annotated[int, Query(ge=1, le=10)] = 5) -> list[KnowledgeOut]:
    """Semantic search over knowledge, unfiltered by the similarity floor, so the scores can be inspected."""
    memory = get_memory(request)
    return [KnowledgeOut.model_validate(h) for h in memory.search_knowledge(q, k=k)] if memory is not None else []


@router.get("/evaluations/latest")
def latest_evaluation() -> dict:
    """Summary of the most recent `python -m eval.run_eval` run (per-ticket predictions omitted)."""
    files = sorted((BACKEND_DIR / "eval" / "results").glob("*.json"))
    if not files:
        raise svc.NotFound("No evaluation has been run yet")
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    data.pop("predictions", None)
    return data


@router.get("/audit", response_model=list[AuditOut])
def audit(db: DB, ticket_id: Annotated[str | None, Query(alias="ticketId")] = None) -> list[AuditOut]:
    return svc.list_audit(db, ticket_id)
