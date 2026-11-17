"""Rebuild semantic memory from PostgreSQL, the source of truth.

    python -m app.memory.rebuild

The vector store is an index, not the record: resolved tickets keep their resolution and overridden tickets keep
both the AI's guess and the agent's decision in PostgreSQL. If the vector store is wiped (a free Qdrant cluster
deleted after inactivity, a new environment), the API rebuilds it on start-up and nothing learned is lost.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Ticket
from .semantic import KnowledgeItem, SemanticMemory, seed_knowledge

log = logging.getLogger("supportflow.memory")


def rebuild_learned(db: Session, memory: SemanticMemory) -> dict[str, int]:
    """Re-add every resolved ticket (knowledge) and every correction. Idempotent: entries are upserted by ticket id."""
    from ..services.tickets import is_correction  # late import: services import this package

    tickets = db.scalars(select(Ticket).options(selectinload(Ticket.analyses)).order_by(Ticket.created_at)).all()
    resolved = [KnowledgeItem(id=t.id, subject=t.subject or "(no subject)", body=t.body, resolution=t.resolution,
                              category=t.decision_category or "other", source="ticket", resolved_at=t.resolved_at.isoformat())
                for t in tickets if t.resolution and t.resolved_at]
    memory.upsert_knowledge(resolved)
    corrections = 0
    for t in tickets:
        if t.decision_status != "overridden" or not t.analyses:
            continue
        # the analysis the agent was looking at when they decided
        seen = [a for a in t.analyses if not t.decided_at or a.analyzed_at <= t.decided_at] or t.analyses
        a = seen[-1]
        if is_correction(a, t.decision_category, t.decision_priority):
            memory.add_correction(t.id, t.subject, t.body, {"category": a.category, "priority": a.priority},
                                  {"category": t.decision_category, "priority": t.decision_priority})
            corrections += 1
    return {"knowledge": len(resolved), "corrections": corrections}


def ensure_ready(db: Session, memory: SemanticMemory) -> None:
    """Start-up check: seed the curated KB if the store is empty, and if it was empty, restore what was learned."""
    if memory.knowledge.count():
        return
    seeded = seed_knowledge(memory)
    restored = rebuild_learned(db, memory)
    log.info("semantic memory was empty: seeded %d KB articles, restored %s from PostgreSQL", seeded, restored)


if __name__ == "__main__":
    from ..config import get_settings
    from ..db import get_engine
    from .semantic import build_semantic_memory

    mem = build_semantic_memory(get_settings())
    seed_knowledge(mem)
    with Session(get_engine()) as session:
        print("rebuilt:", rebuild_learned(session, mem), "| stats:", mem.stats())
