"""Episodic memory: what happened with this customer, in time order (PostgreSQL ``episodes`` table).

Episodes are written by the ticket service as things happen (opened, classified, agent decision, senior or
manager step, resolved) and recalled by customer. Only the customer's *earlier* tickets are recalled, so a
ticket is never shown its own future, and re-classifying an old ticket sees what its agent would have seen.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Episode, Ticket, utcnow


def customer_key(email: str | None, company: str | None, name: str | None) -> str:
    """The same customer across tickets: their email, else company + name (both lower-cased)."""
    email = (email or "").strip().lower()
    return email or f"{(company or '').strip().lower()}|{(name or '').strip().lower()}"


def key_of(t: Ticket) -> str:
    return customer_key(t.customer_email, t.customer_company, t.customer_name)


def record(db: Session, t: Ticket, kind: str, summary: str, data: dict[str, Any] | None = None, at: datetime | None = None) -> None:
    """Add an episode to the current transaction (the caller commits)."""
    db.add(Episode(customer_key=key_of(t), ticket_id=t.id, kind=kind, summary=summary, data=data or {}, occurred_at=at or utcnow()))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes


def earlier_tickets(db: Session, t: Ticket, days: int, limit: int) -> list[tuple[Ticket, list[Episode]]]:
    """The customer's tickets opened before ``t`` (within ``days``), newest first, each with its episodes in order."""
    since = _aware(t.created_at) - timedelta(days=days)
    rows = db.execute(
        select(Ticket, Episode).join(Episode, Episode.ticket_id == Ticket.id)
        .where(Episode.customer_key == key_of(t), Ticket.id != t.id, Ticket.created_at < t.created_at, Ticket.created_at >= since)
        .order_by(Ticket.created_at.desc(), Episode.occurred_at, Episode.id)
    ).all()
    grouped: OrderedDict[str, tuple[Ticket, list[Episode]]] = OrderedDict()
    for ticket, ep in rows:
        if ticket.id not in grouped:
            if len(grouped) == limit:
                break
            grouped[ticket.id] = (ticket, [])
        grouped[ticket.id][1].append(ep)
    return list(grouped.values())


def _ago(then: datetime, now: datetime) -> str:
    s = max((now - _aware(then)).total_seconds(), 0)
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= size:
            n = int(s // size)
            return f"{n} {unit}{'s' if n != 1 else ''} before this ticket"
    return "just before this ticket"


def history_lines(tickets: list[tuple[Ticket, list[Episode]]], current: Ticket) -> list[str]:
    """One compact line per earlier ticket for the classifier: what was asked, how it was read, how it ended.

    Built from structured episode data, never from free text the customer wrote beyond the subject, so a
    previous message cannot smuggle instructions into this ticket's prompt."""
    lines = []
    for t, eps in tickets:
        parts = [f"{t.id}, {_ago(t.created_at, _aware(current.created_at))}: \"{t.subject[:120]}\""]
        cls = next((e.data for e in reversed(eps) if e.kind == "classified"), None)
        dec = next((e.data for e in reversed(eps) if e.kind == "decision"), None)
        res = next((e.data for e in reversed(eps) if e.kind == "resolved"), None)
        if dec:
            parts.append(f"agent confirmed {dec['category']} {dec['priority']}" if dec["status"] == "accepted"
                         else f"agent set {dec['category']} {dec['priority']} (AI had said {dec.get('aiCategory', '?')} {dec.get('aiPriority', '?')})")
        elif cls:
            parts.append(f"AI read it as {cls['category']} {cls['priority']}, {cls['sentiment']}")
        if cls and dec:
            parts.append(f"sentiment {cls['sentiment']}")
        parts.append(f"resolved: {res['resolution'][:160]}" if res else f"status {t.status.replace('_', ' ')}")
        lines.append("; ".join(parts))
    return lines
