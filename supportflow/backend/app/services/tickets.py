"""Ticket workflow rules (Module 1 + 4). The API layer stays thin; every rule lives here."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Analysis, AuditEvent, Ticket, utcnow
from ..schemas import (AnalysisOut, AuditOut, Customer, DecisionIn, DecisionOut, ManagerApprovalOut, ReviewFlag, TicketCreate,
                       TicketOut)


class DomainError(Exception):
    status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409


class Forbidden(DomainError):
    status = 403


class Invalid(DomainError):
    status = 422


@dataclass(frozen=True)
class Actor:
    name: str
    role: Literal["agent", "manager"]


def _has_flag(a: Analysis | None, flag: str) -> bool:
    return bool(a and any(f.get("type") == flag for f in a.flags))


def _audit(db: Session, ticket_id: str, actor: str, action: str, detail: str | None = None) -> None:
    db.add(AuditEvent(ticket_id=ticket_id, actor=actor, action=action, detail=detail))


# ---------------------------------------------------------------- serialisation
def to_out(t: Ticket) -> TicketOut:
    a = t.latest_analysis
    return TicketOut(
        id=t.id, subject=t.subject, body=t.body, channel=t.channel, created_at=t.created_at, status=t.status, assignee=t.assignee,
        customer=Customer(name=t.customer_name, company=t.customer_company, email=t.customer_email, plan=t.customer_plan),
        analysis=None if a is None else AnalysisOut(
            language=a.language, category=a.category, priority=a.priority, sentiment=a.sentiment, confidence=a.confidence, summary=a.summary,
            flags=[ReviewFlag(**f) for f in a.flags], model=a.model, analyzed_at=a.analyzed_at, latency_ms=a.latency_ms, error=a.error),
        decision=DecisionOut(status=t.decision_status, category=t.decision_category, priority=t.decision_priority,
                             decided_by=t.decided_by, decided_at=t.decided_at),
        manager_approval=ManagerApprovalOut(by=t.manager_approved_by, at=t.manager_approved_at) if t.manager_approved_by else None,
    )


# ---------------------------------------------------------------- queries
def list_tickets(db: Session) -> list[Ticket]:
    return list(db.scalars(select(Ticket).options(selectinload(Ticket.analyses)).order_by(Ticket.created_at.desc())))


def get_ticket(db: Session, ticket_id: str) -> Ticket:
    t = db.scalars(select(Ticket).options(selectinload(Ticket.analyses)).where(Ticket.id == ticket_id)).first()
    if not t:
        raise NotFound(f"Ticket {ticket_id} not found")
    return t


def list_audit(db: Session, ticket_id: str | None = None, limit: int = 500) -> list[AuditOut]:
    q = select(AuditEvent).order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(limit)
    if ticket_id:
        q = q.where(AuditEvent.ticket_id == ticket_id)
    return [AuditOut.model_validate(e) for e in db.scalars(q)]


def _next_id(db: Session) -> str:
    nums = [int(m.group(1)) for i in db.scalars(select(Ticket.id)) if (m := re.fullmatch(r"SF-(\d+)", i))]
    return f"SF-{max(nums, default=1000) + 1}"


# ---------------------------------------------------------------- commands
def create_ticket(db: Session, data: TicketCreate, actor: Actor) -> Ticket:
    t = Ticket(id=_next_id(db), subject=data.subject.strip(), body=data.body.strip(), channel=data.channel,
               customer_name=data.customer.name, customer_company=data.customer.company, customer_email=data.customer.email,
               customer_plan=data.customer.plan, status="new")
    db.add(t)
    db.flush()
    _audit(db, t.id, "agent", "Created ticket", f"via {data.channel.replace('_', ' ')} by {actor.name}")
    db.commit()
    return get_ticket(db, t.id)


def analyze_ticket(db: Session, ticket_id: str, classifier: Any) -> Ticket:
    t = get_ticket(db, ticket_id)
    state = classifier.invoke({"subject": t.subject, "body": t.body})
    o = state["output"]
    a = Analysis(ticket_id=t.id, language=o.get("language"), category=o["category"], priority=o["priority"], sentiment=o["sentiment"], confidence=o["confidence"],
                 summary=o["summary"], flags=state["flags"], model=state["model"], latency_ms=state["latency_ms"],
                 attempts=state["attempts"], error=state.get("error"))
    db.add(a)
    had_decision = t.decision_status != "pending"
    # New AI output always goes back to an agent: it is never auto-approved.
    t.decision_status, t.decision_category, t.decision_priority, t.decided_by, t.decided_at = "pending", None, None, None, None
    if t.status in ("new", "in_progress"):
        t.status = "needs_review"
    _audit(db, t.id, "ai", "Classified ticket", f"{a.category} · {a.priority} · confidence {a.confidence:.2f} · {a.model}")
    if a.error:
        _audit(db, t.id, "system", "AI fallback used", a.error)
    for f in a.flags:
        _audit(db, t.id, "system", "Safety flag raised", f["reason"])
    if had_decision:
        _audit(db, t.id, "system", "Classification reset for agent review")
    db.commit()
    db.refresh(t)
    return get_ticket(db, t.id)


def decide_classification(db: Session, ticket_id: str, d: DecisionIn, actor: Actor) -> Ticket:
    t = get_ticket(db, ticket_id)
    a = t.latest_analysis
    if d.accept:
        if a is None:
            raise Conflict("Nothing to accept: the ticket has not been analysed")
        if _has_flag(a, "manual_review"):
            raise Conflict("Low-confidence tickets must be classified manually")
        status, category, priority = "accepted", a.category, a.priority
    else:
        if not (d.category and d.priority):
            raise Invalid("Provide both category and priority, or set accept=true")
        status, category, priority = "overridden", d.category, d.priority
    t.decision_status, t.decision_category, t.decision_priority = status, category, priority
    t.decided_by, t.decided_at = actor.name, utcnow()
    if t.status in ("new", "needs_review"):
        t.status = "in_progress"
    t.assignee = t.assignee or actor.name
    _audit(db, t.id, "agent", "Accepted AI classification" if d.accept else "Set classification manually", f"{category} · {priority} · {actor.name}")
    db.commit()
    return get_ticket(db, t.id)


def assign_senior(db: Session, ticket_id: str, actor: Actor, senior: str = "Sam Patel (Senior)") -> Ticket:
    t = get_ticket(db, ticket_id)
    t.assignee = senior
    _audit(db, t.id, "agent", "Assigned to senior agent", f"{senior} · by {actor.name}")
    db.commit()
    return get_ticket(db, t.id)


def record_manager_approval(db: Session, ticket_id: str, actor: Actor) -> Ticket:
    t = get_ticket(db, ticket_id)
    if actor.role != "manager":
        raise Forbidden("Only a manager can clear a manager-review flag")
    if not _has_flag(t.latest_analysis, "manager_review"):
        raise Conflict("This ticket has no manager-review flag")
    t.manager_approved_by, t.manager_approved_at = actor.name, utcnow()
    _audit(db, t.id, "agent", "Manager approved handling", actor.name)
    db.commit()
    return get_ticket(db, t.id)
