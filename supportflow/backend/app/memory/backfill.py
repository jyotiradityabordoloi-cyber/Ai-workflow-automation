"""Rebuild episodic memory for tickets that existed before the memory step (non-destructive, idempotent).

    python -m app.memory.backfill

Episodes are derived from what the database already holds: the ticket (opened), every analysis
(classified), the agent's decision, the manager approval and the resolution. Tickets that already have
episodes are skipped.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_engine
from ..models import Episode, Ticket
from . import episodic


def backfill(db: Session) -> int:
    done = set(db.scalars(select(Episode.ticket_id).distinct()))
    tickets = db.scalars(select(Ticket).options(selectinload(Ticket.analyses)).order_by(Ticket.created_at)).all()
    n = 0
    for t in tickets:
        if t.id in done:
            continue
        episodic.record(db, t, "opened", f"Opened {t.id}: {t.subject or '(no subject)'}", {"channel": t.channel}, at=t.created_at)
        for a in t.analyses:
            episodic.record(db, t, "classified", f"AI classified it {a.category} · {a.priority} · {a.sentiment} ({a.confidence:.2f})",
                            {"category": a.category, "priority": a.priority, "sentiment": a.sentiment, "confidence": a.confidence},
                            at=a.analyzed_at)
        a = t.latest_analysis
        if t.decision_status != "pending" and t.decided_at:
            episodic.record(db, t, "decision", f"{t.decided_by} {'confirmed' if t.decision_status == 'accepted' else 'set'} "
                                               f"{t.decision_category} · {t.decision_priority}",
                            {"status": t.decision_status, "category": t.decision_category, "priority": t.decision_priority,
                             "by": t.decided_by, "aiCategory": a and a.category, "aiPriority": a and a.priority}, at=t.decided_at)
        if t.manager_approved_by and t.manager_approved_at:
            episodic.record(db, t, "manager", f"Manager {t.manager_approved_by} approved handling", {"by": t.manager_approved_by},
                            at=t.manager_approved_at)
        if t.resolution and t.resolved_at:
            episodic.record(db, t, "resolved", f"Resolved by {t.resolved_by}: {t.resolution[:200]}",
                            {"resolution": t.resolution, "by": t.resolved_by}, at=t.resolved_at)
        n += 1
    db.commit()
    return n


if __name__ == "__main__":
    with Session(get_engine()) as session:
        print(f"backfilled episodes for {backfill(session)} ticket(s)")
