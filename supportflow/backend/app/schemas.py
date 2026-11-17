"""Pydantic schemas: API contracts (camelCase JSON, matching frontend/src/lib/types.ts) and
the structured output the LLM must return."""
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

Category = Literal["billing", "bug", "feature_request", "account", "other"]
Priority = Literal["P1", "P2", "P3"]
Sentiment = Literal["positive", "neutral", "frustrated", "angry"]
Channel = Literal["email", "chat", "web_form"]
Plan = Literal["Starter", "Pro", "Business", "Enterprise"]
FlagType = Literal["manual_review", "senior_agent", "manager_review"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---------------------------------------------------------------- LLM output contract
class ClassificationOutput(BaseModel):
    """Exactly what the classifier LLM must return. Anything else is rejected and retried."""

    model_config = ConfigDict(extra="forbid")

    language: Annotated[str, Field(pattern=r"^[a-z]{2}$", description="ISO 639-1 code of the message language, e.g. en")]
    category: Category
    priority: Priority
    sentiment: Sentiment
    confidence: Annotated[float, Field(ge=0, le=1)]
    summary: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("summary")
    @classmethod
    def max_two_sentences(cls, v: str) -> str:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s]
        return " ".join(sentences[:2])


# ---------------------------------------------------------------- API models
class ReviewFlag(ApiModel):
    type: FlagType
    reason: str


class Customer(ApiModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    company: Annotated[str, Field(max_length=160)] = ""
    email: Annotated[str, Field(max_length=200)] = ""
    plan: Plan = "Starter"


class AnalysisOut(ApiModel):
    language: str | None = None
    category: Category
    priority: Priority
    sentiment: Sentiment
    confidence: float
    summary: str
    flags: list[ReviewFlag]
    model: str
    analyzed_at: datetime
    latency_ms: int
    error: str | None = None
    memory: "MemoryUsedOut | None" = None


class MemoryRef(ApiModel):
    id: str
    similarity: float


class MemoryUsedOut(ApiModel):
    """What the recall step put in front of the classifier for this analysis."""

    history: list[str] = []          # earlier ticket ids of the same customer (episodic)
    corrections: list[MemoryRef] = []  # near-identical tickets an agent re-classified (semantic)
    knowledge: list[MemoryRef] = []    # similar resolved problems (semantic; recorded, not sent to the classifier)


class DecisionOut(ApiModel):
    status: Literal["pending", "accepted", "overridden"]
    category: Category | None = None
    priority: Priority | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None


class ManagerApprovalOut(ApiModel):
    by: str
    at: datetime


class TicketOut(ApiModel):
    id: str
    subject: str
    body: str
    customer: Customer
    channel: Channel
    created_at: datetime
    status: str
    assignee: str | None
    analysis: AnalysisOut | None
    decision: DecisionOut
    manager_approval: ManagerApprovalOut | None = None
    resolution: "ResolutionOut | None" = None


class ResolutionOut(ApiModel):
    text: str
    by: str
    at: datetime


class TicketCreate(ApiModel):
    subject: Annotated[str, Field(max_length=300)] = ""
    body: Annotated[str, Field(min_length=1, max_length=5000)]
    customer: Customer
    channel: Channel = "web_form"


class DecisionIn(ApiModel):
    """Either accept the AI classification, or set category + priority yourself."""

    accept: bool = False
    category: Category | None = None
    priority: Priority | None = None


class ResolveIn(ApiModel):
    resolution: Annotated[str, Field(min_length=10, max_length=2000, description="What fixed it; becomes searchable knowledge")]


# ---------------------------------------------------------------- memory
class EpisodeOut(ApiModel):
    kind: str
    summary: str
    occurred_at: datetime


class PastTicketOut(ApiModel):
    id: str
    subject: str
    status: str
    created_at: datetime
    episodes: list[EpisodeOut]


class KnowledgeOut(ApiModel):
    id: str
    subject: str
    body: str
    resolution: str
    category: str
    source: Literal["kb", "ticket"]
    resolved_at: str | None = None
    similarity: float | None = None


class CorrectionOut(ApiModel):
    ticket_id: str
    similarity: float
    excerpt: str
    ai: dict[str, str]
    agent: dict[str, str]


class TicketMemoryOut(ApiModel):
    """Everything memory holds that is relevant to one ticket."""

    customer_key: str
    earlier_tickets: list[PastTicketOut]   # episodic: this customer's earlier tickets and what happened
    knowledge: list[KnowledgeOut]          # semantic: top-3 similar resolved problems
    corrections: list[CorrectionOut]       # semantic: agent corrections on near-identical tickets
    used_by_ai: MemoryUsedOut | None       # what the latest analysis actually saw


class MemoryStatsOut(ApiModel):
    embedder: str
    knowledge: int
    corrections: int
    episodes: int


class AuditOut(ApiModel):
    id: int
    ticket_id: str
    at: datetime
    actor: Literal["ai", "agent", "system"]
    action: str
    detail: str | None


class HealthOut(ApiModel):
    ok: bool
    database: bool
    llm_provider: str
    llm_model: str
    llm_configured: bool


AnalysisOut.model_rebuild()
TicketOut.model_rebuild()
