import type { Category, FlagType, Priority, Sentiment, TicketStatus } from "./types";

export const CATEGORY_LABEL: Record<Category, string> = {
  billing: "Billing", bug: "Bug", feature_request: "Feature request", account: "Account", other: "Other",
};
export const CATEGORIES = Object.keys(CATEGORY_LABEL) as Category[];
export const PRIORITIES: Priority[] = ["P1", "P2", "P3"];

export const SENTIMENT_LABEL: Record<Sentiment, string> = {
  positive: "Positive", neutral: "Neutral", frustrated: "Frustrated", angry: "Angry",
};

export const STATUS_LABEL: Record<TicketStatus, string> = {
  new: "New", needs_review: "Needs review", in_progress: "In progress", awaiting_approval: "Awaiting approval", escalated: "Escalated", resolved: "Resolved",
};

export const FLAG_LABEL: Record<FlagType, string> = {
  manual_review: "Manual review", senior_agent: "Senior agent", manager_review: "Manager review",
};

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const initials = (name: string) => name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
