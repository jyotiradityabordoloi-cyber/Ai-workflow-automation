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
