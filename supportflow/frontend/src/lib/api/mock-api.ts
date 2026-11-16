"use client";

import { CONFIDENCE_THRESHOLD, hasFlag } from "../rules";
import { buildAnalysis, MOCK_MODEL, PENDING_ANALYSES } from "../mock/seed";
import { search } from "../mock/retrieval";
import type { AuditEvent, Category, Draft, Escalation, EscalationBrief, Priority, RetrievedDoc, Ticket, Workspace } from "../types";
import { getState, resetState, setState } from "./store";

// Mock implementation of the SupportFlow API. Every function is async and enforces the same
// human-approval rules the backend will, so the UI is built against real behaviour, not props.

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const now = () => new Date().toISOString();
let seq = Date.now() % 100000;
const nextId = (p: string) => `${p}-${++seq}`;

export class ApiError extends Error {}

function ticketOf(s: Workspace, id: string): Ticket {
  const t = s.tickets.find((x) => x.id === id);
  if (!t) throw new ApiError(`Ticket ${id} not found`);
  return t;
}

function patchTicket(s: Workspace, id: string, patch: Partial<Ticket>): Workspace {
  return { ...s, tickets: s.tickets.map((t) => (t.id === id ? { ...t, ...patch } : t)) };
}

function audit(s: Workspace, ticketId: string, actor: AuditEvent["actor"], action: string, detail?: string): Workspace {
  return { ...s, audit: [...s.audit, { id: nextId("AU"), ticketId, at: now(), actor, action, detail }] };
}

export const mockApi = {
  mode: "mock" as const,

  async analyzeTicket(ticketId: string): Promise<void> {
    const started = performance.now();
    await wait(900);
    setState((s) => {
      const t = ticketOf(s, ticketId);
      const a = PENDING_ANALYSES[ticketId] ?? (t.analysis && [t.analysis.category, t.analysis.priority, t.analysis.sentiment, t.analysis.confidence, t.analysis.summary]);
      if (!a) throw new ApiError("No mock analysis available for this ticket");
      const analysis = buildAnalysis(`${t.subject} ${t.body}`, a as never, now(), Math.round(performance.now() - started));
      let next = patchTicket(s, ticketId, { analysis, status: "needs_review", decision: { status: "pending" } });
      next = audit(next, ticketId, "ai", "Classified ticket", `${analysis.category} · ${analysis.priority} · confidence ${analysis.confidence.toFixed(2)}`);
      for (const f of analysis.flags) next = audit(next, ticketId, "system", "Safety flag raised", f.reason);
      return next;
    });
  },

  /** Agent accepts the AI classification, or sets their own (required for manual-review tickets). */
  async decideClassification(ticketId: string, choice: { accept: true } | { category: Category; priority: Priority }): Promise<void> {
    await wait(150);
    setState((s) => {
      const t = ticketOf(s, ticketId);
      if ("accept" in choice) {
        if (!t.analysis) throw new ApiError("Nothing to accept: ticket has not been analysed");
        if (hasFlag(t.analysis.flags, "manual_review")) throw new ApiError("Low-confidence tickets must be classified manually");
      }
      const decision = "accept" in choice
        ? { status: "accepted" as const, category: t.analysis!.category, priority: t.analysis!.priority }
        : { status: "overridden" as const, category: choice.category, priority: choice.priority };
      const next = patchTicket(s, ticketId, {
        decision: { ...decision, decidedBy: s.currentAgent, decidedAt: now() },
        status: t.status === "new" || t.status === "needs_review" ? "in_progress" : t.status,
        assignee: t.assignee ?? s.currentAgent,
      });
      return audit(next, ticketId, "agent", "accept" in choice ? "Accepted AI classification" : "Set classification manually",
        `${decision.category} · ${decision.priority}`);
    });
  },

  async assignSenior(ticketId: string): Promise<void> {
    await wait(150);
    setState((s) => audit(patchTicket(s, ticketId, { assignee: "Sam Patel (Senior)" }), ticketId, "agent", "Assigned to senior agent", "Sam Patel"));
  },

  async recordManagerApproval(ticketId: string): Promise<void> {
    await wait(150);
    setState((s) => {
      if (s.currentRole !== "manager") throw new ApiError("Only a manager can clear a manager-review flag");
      return audit(patchTicket(s, ticketId, { managerApproval: { by: s.currentAgent, at: now() } }), ticketId, "agent", "Manager approved handling", s.currentAgent);
    });
  },

  async retrieve(ticketId: string): Promise<RetrievedDoc[]> {
    await wait(250);
    const s = getState();
    const t = ticketOf(s, ticketId);
    return search(s.knowledge, `${t.subject} ${t.body}`, 3);
  },

  async searchKnowledge(query: string, k = 5): Promise<RetrievedDoc[]> {
    await wait(150);
    return search(getState().knowledge, query, k);
  },

  async generateDraft(ticketId: string): Promise<void> {
    const sources = await mockApi.retrieve(ticketId);
    await wait(700);
    setState((s) => {
      const t = ticketOf(s, ticketId);
      if (t.decision.status === "pending") throw new ApiError("Confirm the classification before drafting a reply");
      const first = t.customer.name.split(" ")[0];
      const top = sources[0];
      const manager = hasFlag(t.analysis?.flags, "manager_review");
      const body = manager
        ? `Hi ${first},\n\nThank you for your message, and I'm sorry for the trouble. Your case is being reviewed by our team lead and we'll come back to you with an update shortly.\n\nBest,\n[Agent name]`
        : top && top.similarity >= 0.15
          ? `Hi ${first},\n\nThanks for reaching out. ${top.doc.resolution}\n\nLet me know if anything is still not working and I'll pick it up straight away.\n\nBest,\n[Agent name]`
          : `Hi ${first},\n\nThanks for reaching out. I'm looking into this now and will get back to you shortly.\n\nAGENT CHECK: no closely matching resolved ticket was found.\n\nBest,\n[Agent name]`;
      const draft: Draft = { id: nextId("DR"), ticketId, body, originalBody: body, model: MOCK_MODEL, status: "generated", generatedAt: now(),
        sources: sources.map((r) => ({ id: r.doc.id, similarity: r.similarity })) };
      const others = s.drafts.map((d) => (d.ticketId === ticketId && (d.status === "generated" || d.status === "edited") ? { ...d, status: "rejected" as const, rejectionReason: "Superseded by a new draft" } : d));
      const next = patchTicket({ ...s, drafts: [...others, draft] }, ticketId, { status: "awaiting_approval" });
      return audit(next, ticketId, "ai", "Drafted response", `Grounded in ${draft.sources.map((x) => x.id).join(", ") || "no sources"}`);
    });
  },

  async editDraft(draftId: string, body: string): Promise<void> {
    setState((s) => ({ ...s, drafts: s.drafts.map((d) => (d.id === draftId && (d.status === "generated" || d.status === "edited") ? { ...d, body, status: body === d.originalBody ? "generated" : "edited" } : d)) }));
  },

  async approveDraft(draftId: string): Promise<void> {
    await wait(200);
    setState((s) => {
      const d = s.drafts.find((x) => x.id === draftId);
      if (!d) throw new ApiError("Draft not found");
      const t = ticketOf(s, d.ticketId);
      if (hasFlag(t.analysis?.flags, "manager_review") && !t.managerApproval) throw new ApiError("Manager review is required before any response is sent");
      if (/\[Agent name\]/.test(d.body)) throw new ApiError("Replace [Agent name] before approving");
      const next = { ...s, drafts: s.drafts.map((x) => (x.id === draftId ? { ...x, status: "approved" as const, decidedBy: s.currentAgent, decidedAt: now() } : x)) };
      return audit(patchTicket(next, d.ticketId, { status: "resolved" }), d.ticketId, "agent", "Approved response", d.body === d.originalBody ? "Sent as drafted" : "Sent after edits");
    });
  },

  async rejectDraft(draftId: string, reason: string): Promise<void> {
    await wait(150);
    setState((s) => {
      const d = s.drafts.find((x) => x.id === draftId);
      if (!d) throw new ApiError("Draft not found");
      const next = { ...s, drafts: s.drafts.map((x) => (x.id === draftId ? { ...x, status: "rejected" as const, rejectionReason: reason, decidedBy: s.currentAgent, decidedAt: now() } : x)) };
      return audit(patchTicket(next, d.ticketId, { status: "in_progress" }), d.ticketId, "agent", "Rejected draft", reason);
    });
  },

  async requestEscalation(ticketId: string): Promise<void> {
    await wait(800);
    setState((s) => {
      const t = ticketOf(s, ticketId);
      if (s.escalations.some((e) => e.ticketId === ticketId && e.status === "pending_approval")) throw new ApiError("An escalation is already awaiting approval");
      const priority = t.decision.priority ?? t.analysis?.priority ?? "P2";
      const sentences = t.body.split(/(?<=[.!?])\s+/);
      const tried = sentences.filter((x) => /\b(tried|reinstall|clear|restart|reboot|checked|escap|quot|same result)/i.test(x));
      const brief: EscalationBrief = {
        summary: (t.analysis?.summary ?? t.subject).split(/(?<=[.!?])\s+/).slice(0, 2).join("\n"),
        troubleshooting: tried.length ? tried : ["No troubleshooting steps mentioned by the customer"],
        priority, ticketUrl: `https://supportflow.example/tickets/${t.id}`,
        impact: `${t.customer.plan} plan · ${t.customer.company}`,
      };
      const esc: Escalation = { id: nextId("ESC"), ticketId, brief, channel: "#eng-escalations", status: "pending_approval",
        requestedBy: s.currentAgent, requestedAt: now(), slackMode: "simulated" };
      const next = patchTicket({ ...s, escalations: [...s.escalations, esc] }, ticketId, { status: "awaiting_approval" });
      return audit(next, ticketId, "ai", "Generated escalation brief", `${esc.id} → ${esc.channel}`);
    });
  },

  async updateEscalationBrief(id: string, brief: EscalationBrief): Promise<void> {
    setState((s) => ({ ...s, escalations: s.escalations.map((e) => (e.id === id && e.status === "pending_approval" ? { ...e, brief } : e)) }));
  },

  async approveEscalation(id: string): Promise<void> {
    await wait(500);
    setState((s) => {
      const e = s.escalations.find((x) => x.id === id);
      if (!e || e.status !== "pending_approval") throw new ApiError("Escalation is not awaiting approval");
      const next = { ...s, escalations: s.escalations.map((x) => (x.id === id ? { ...x, status: "posted" as const, decidedBy: s.currentAgent, decidedAt: now(), slackMessageTs: `sim-${Date.now()}` } : x)) };
      return audit(patchTicket(next, e.ticketId, { status: "escalated" }), e.ticketId, "agent", "Approved escalation", `Posted to ${e.channel} (simulated Slack)`);
    });
  },

  async rejectEscalation(id: string, reason: string): Promise<void> {
    await wait(150);
    setState((s) => {
      const e = s.escalations.find((x) => x.id === id);
      if (!e) throw new ApiError("Escalation not found");
      const next = { ...s, escalations: s.escalations.map((x) => (x.id === id ? { ...x, status: "rejected" as const, rejectionReason: reason, decidedBy: s.currentAgent, decidedAt: now() } : x)) };
      return audit(patchTicket(next, e.ticketId, { status: "in_progress" }), e.ticketId, "agent", "Rejected escalation", reason);
    });
  },

  async setRole(role: Workspace["currentRole"]): Promise<void> {
    setState((s) => ({ ...s, currentRole: role, currentAgent: role === "manager" ? "Jordan Lee" : "Alex Rivera" }));
  },

  async reset(): Promise<void> {
    resetState();
  },
};

export { CONFIDENCE_THRESHOLD };
