"""Database tables for step 2 (tickets, AI analyses, audit trail).

Drafts, escalations and the knowledge base are added by later migrations in steps 3 and 4.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="web_form")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    assignee: Mapped[str | None] = mapped_column(String(120))

    customer_name: Mapped[str] = mapped_column(String(120))
    customer_company: Mapped[str] = mapped_column(String(160), default="")
    customer_email: Mapped[str] = mapped_column(String(200), default="")
    customer_plan: Mapped[str] = mapped_column(String(20), default="Starter")

    # Agent's decision on the AI classification. AI output is never applied without one.
    decision_status: Mapped[str] = mapped_column(String(20), default="pending")
    decision_category: Mapped[str | None] = mapped_column(String(30))
    decision_priority: Mapped[str | None] = mapped_column(String(2))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    manager_approved_by: Mapped[str | None] = mapped_column(String(120))
    manager_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="ticket", order_by="Analysis.id", cascade="all, delete-orphan")

    @property
    def latest_analysis(self) -> "Analysis | None":
        return self.analyses[-1] if self.analyses else None


class Analysis(Base):
    """One classification run. Kept as history: re-running analysis adds a row."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    language: Mapped[str | None] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(2))
    sentiment: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    flags: Mapped[list[dict]] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(120))
    latency_ms: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text)  # set when the LLM failed and a fallback was stored
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="analyses")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(10))  # ai | agent | system
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(Text)
