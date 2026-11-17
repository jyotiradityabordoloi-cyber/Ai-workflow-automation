// Domain types shared by the UI. They mirror the JSON schemas the FastAPI backend will
// validate (step 2+), so swapping the mock API for the real one needs no UI changes.

export type Category = "billing" | "bug" | "feature_request" | "account" | "other";
export type Priority = "P1" | "P2" | "P3";
export type Sentiment = "positive" | "neutral" | "frustrated" | "angry";
export type Channel = "email" | "chat" | "web_form";

export type TicketStatus =
  | "new" // not analysed yet
  | "needs_review" // analysed, classification awaiting agent decision
  | "in_progress" // classification accepted / set by agent
  | "awaiting_approval" // response or escalation waiting for a human decision
  | "escalated"
  | "resolved";

export type FlagType = "manual_review" | "senior_agent" | "manager_review";

export interface ReviewFlag {
  type: FlagType;
  reason: string;
}

export interface Customer {
  name: string;
  company: string;
  email: string;
  plan: "Starter" | "Pro" | "Business" | "Enterprise";
}

/** Output of the classification step (Module 1). */
export interface Analysis {
  language?: string | null; // ISO 639-1, reported by the model (live mode)
  category: Category;
  priority: Priority;
  sentiment: Sentiment;
  confidence: number; // 0..1
  summary: string; // max two sentences
  flags: ReviewFlag[];
  model: string;
  analyzedAt: string;
  latencyMs: number;
}

/** The agent's decision on the AI classification. AI output is never auto-approved. */
export interface ClassificationDecision {
  status: "pending" | "accepted" | "overridden";
  category?: Category;
  priority?: Priority;
  decidedBy?: string;
  decidedAt?: string;
}

export interface Ticket {
  id: string;
  subject: string;
  body: string;
  customer: Customer;
  channel: Channel;
  createdAt: string;
  status: TicketStatus;
  assignee: string | null;
  analysis: Analysis | null;
  decision: ClassificationDecision;
  /** set when the agent marks the manager-review flag as cleared */
  managerApproval?: { by: string; at: string };
}

export interface KnowledgeDoc {
  id: string;
  subject: string;
  body: string;
  resolution: string;
  category: Category;
  resolvedAt: string;
}

export interface RetrievedDoc {
  doc: KnowledgeDoc;
  similarity: number; // 0..1
}

export type DraftStatus = "generated" | "edited" | "approved" | "rejected";

export interface Draft {
  id: string;
  ticketId: string;
  body: string;
  originalBody: string; // what the AI produced, kept for audit and edit-distance analytics
  sources: { id: string; similarity: number }[];
  status: DraftStatus;
  generatedAt: string;
  model: string;
  decidedBy?: string;
  decidedAt?: string;
  rejectionReason?: string;
}

export interface EscalationBrief {
  summary: string;
  troubleshooting: string[];
  priority: Priority;
  ticketUrl: string;
  impact: string;
}

export type EscalationStatus = "pending_approval" | "posted" | "rejected";

export interface Escalation {
  id: string;
  ticketId: string;
  brief: EscalationBrief;
  channel: string;
  status: EscalationStatus;
  requestedBy: string;
  requestedAt: string;
  decidedBy?: string;
  decidedAt?: string;
  rejectionReason?: string;
  slackMode: "simulated" | "live";
  slackMessageTs?: string;
}

export interface AuditEvent {
  id: string;
  ticketId: string;
  at: string;
  actor: "ai" | "agent" | "system";
  action: string;
  detail?: string;
}

/** Summary written by backend/eval/run_eval.py (snake_case, served as-is). */
export interface EvaluationSummary {
  run_at: string;
  dataset: string;
  split: "dev" | "test" | string;
  n: number;
  model: string;
  fields: Record<"category" | "priority" | "sentiment", {
    accuracy_pct: number; majority_baseline_pct: number; majority_label: string; errors: Record<string, number>; macro_f1?: number;
  }>;
  manual_review: { expected: number; caught: number; recall_pct: number | null; precision_pct: number | null; extra: string[] };
  calibration: { threshold: number; above_n: number; above_accuracy_pct: number | null; below_n: number; below_accuracy_pct: number | null; confidence_values: Record<string, number> };
  latency_ms: { p50: number | null; p95: number | null };
  llm_failures: number;
}

export interface Workspace {
  tickets: Ticket[];
  knowledge: KnowledgeDoc[];
  drafts: Draft[];
  escalations: Escalation[];
  audit: AuditEvent[];
  currentAgent: string;
  currentRole: "agent" | "manager";
}
