"use client";

import type { AuditEvent, Category, Channel, Customer, EvaluationSummary, KnowledgeDoc, Priority, RetrievedDoc, Ticket, TicketMemory } from "../types";
import { ApiError, mockApi } from "./mock-api";
import { getState, setState } from "./store";

// Live mode (step 2): tickets, classification and Module-4 decisions come from the FastAPI backend.
// Drafting (step 3) and escalation (step 4) still run on the mock until their backend modules exist.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ServerAudit = { id: number; ticketId: string; at: string; actor: AuditEvent["actor"]; action: string; detail: string | null };
type ServerTicket = Ticket & { analysis: (Ticket["analysis"] & { error?: string | null }) | null };
type ServerKnowledge = KnowledgeDoc & { similarity: number | null };
type ServerMemory = Omit<TicketMemory, "knowledge"> & { knowledge: ServerKnowledge[] };

const toRetrieved = ({ similarity, ...doc }: ServerKnowledge): RetrievedDoc => ({ doc, similarity: similarity ?? 0 });

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const s = getState();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Agent-Name": s.currentAgent, "X-Agent-Role": s.currentRole, ...init?.headers },
    });
  } catch {
    throw new ApiError(`Backend unreachable at ${API_URL}`);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(body.error ?? `Request failed (${res.status})`);
  return body as T;
}

/** Audit actions produced by modules that still run on the mock in step 2 (kept across syncs). */
const LOCAL_ACTIONS = new Set(["Drafted response", "Approved response", "Rejected draft", "Generated escalation brief", "Approved escalation", "Rejected escalation"]);

const toAudit = (e: ServerAudit): AuditEvent => ({ id: `srv-${e.id}`, ticketId: e.ticketId, at: e.at, actor: e.actor, action: e.action, detail: e.detail ?? undefined });

/** Server-owned fields replace local ones; local-only audit events (drafts, escalations) are kept. */
function mergeTicket(t: ServerTicket, audit: ServerAudit[]) {
  setState((s) => {
    const exists = s.tickets.some((x) => x.id === t.id);
    return {
      ...s,
      tickets: exists ? s.tickets.map((x) => (x.id === t.id ? { ...x, ...t } : x)) : [t, ...s.tickets],
      audit: [...s.audit.filter((e) => e.ticketId !== t.id || !e.id.startsWith("srv-")), ...audit.map(toAudit)],
    };
  });
}

async function act(ticketId: string, path: string, body?: unknown) {
  const t = await http<ServerTicket>(`/api/tickets/${encodeURIComponent(ticketId)}${path}`, { method: "POST", body: body ? JSON.stringify(body) : undefined });
  mergeTicket(t, await http<ServerAudit[]>(`/api/audit?ticketId=${encodeURIComponent(ticketId)}`));
  return t;
}

export const liveApi = {
  ...mockApi,
  mode: "live" as const,

  async health() {
    return http<{ ok: boolean; database: boolean; llmProvider: string; llmModel: string; llmConfigured: boolean }>("/api/health");
  },

  /** Load all tickets + audit + knowledge from the backend (replacing any mock data). */
  async sync(): Promise<void> {
    const [tickets, audit, knowledge] = await Promise.all([
      http<ServerTicket[]>("/api/tickets"), http<ServerAudit[]>("/api/audit"), http<ServerKnowledge[]>("/api/knowledge"),
    ]);
    const ids = new Set(tickets.map((t) => t.id));
    setState((s) => ({
      ...s,
      knowledge: knowledge.map((k) => toRetrieved(k).doc),
      tickets: tickets.map((t) => ({ ...s.tickets.find((x) => x.id === t.id), ...t })),
      audit: [...s.audit.filter((e) => !e.id.startsWith("srv-") && ids.has(e.ticketId) && LOCAL_ACTIONS.has(e.action)), ...audit.map(toAudit)],
      drafts: s.drafts.filter((d) => ids.has(d.ticketId)),
      escalations: s.escalations.filter((e) => ids.has(e.ticketId)),
    }));
  },

  async latestEvaluation(): Promise<EvaluationSummary | null> {
    try {
      return await http<EvaluationSummary>("/api/evaluations/latest");
    } catch (e) {
      if (e instanceof ApiError && /No evaluation/.test(e.message)) return null;
      throw e;
    }
  },

  async analyzeTicket(ticketId: string) { await act(ticketId, "/analyze"); },

  async decideClassification(ticketId: string, choice: { accept: true } | { category: Category; priority: Priority }) {
    await act(ticketId, "/decision", choice);
  },

  async assignSenior(ticketId: string) { await act(ticketId, "/assign-senior"); },

  async recordManagerApproval(ticketId: string) { await act(ticketId, "/manager-approval"); },

  /** Episodic + semantic memory for one ticket, from PostgreSQL and the ChromaDB vector store. */
  async ticketMemory(ticketId: string): Promise<TicketMemory> {
    const m = await http<ServerMemory>(`/api/tickets/${encodeURIComponent(ticketId)}/memory`);
    return { ...m, knowledge: m.knowledge.map(toRetrieved) };
  },

  /** Top-3 similar resolved problems by embedding similarity (replaces the mock's in-browser TF-IDF). */
  async retrieve(ticketId: string): Promise<RetrievedDoc[]> {
    return (await liveApi.ticketMemory(ticketId)).knowledge;
  },

  async searchKnowledge(query: string, k = 5): Promise<RetrievedDoc[]> {
    return (await http<ServerKnowledge[]>(`/api/knowledge/search?q=${encodeURIComponent(query)}&k=${k}`)).map(toRetrieved);
  },

  async resolveTicket(ticketId: string, resolution: string) {
    await act(ticketId, "/resolve", { resolution });
    const knowledge = await http<ServerKnowledge[]>("/api/knowledge");
    setState((s) => ({ ...s, knowledge: knowledge.map((k) => toRetrieved(k).doc) }));
  },

  async createTicket(input: { subject: string; body: string; customer: Customer; channel: Channel; analyze: boolean }): Promise<string> {
    const { analyze, ...payload } = input;
    const t = await http<ServerTicket>(`/api/tickets?analyze=${analyze}`, { method: "POST", body: JSON.stringify(payload) });
    mergeTicket(t, await http<ServerAudit[]>(`/api/audit?ticketId=${encodeURIComponent(t.id)}`));
    return t.id;
  },
};
