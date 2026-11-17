"use client";

import clsx from "clsx";
import { ArrowLeft, Bot, Check, CircleCheck, FileSearch, History, Pencil, RefreshCw, ShieldAlert, ShieldCheck, Siren, Sparkles, User, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Avatar, PageHeader } from "@/components/shell";
import {
  Badge, Button, Card, CardHeader, CategoryBadge, ConfidenceBar, EmptyState, ErrorText, FlagBadge, PriorityBadge, SentimentBadge,
} from "@/components/ui";
import { api, useWorkspace } from "@/lib/api";
import { CATEGORIES, CATEGORY_LABEL, dateTime, PRIORITIES, STATUS_LABEL, timeAgo, subjectOf } from "@/lib/format";
import { CONFIDENCE_THRESHOLD, hasFlag } from "@/lib/rules";
import type { Category, MemoryUsed, Priority, RetrievedDoc, Ticket, TicketMemory } from "@/lib/types";
import { useAction } from "@/lib/use-action";

const select = "h-8 rounded-lg border border-line bg-surface px-2 text-[13px]";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Episodic + semantic memory for the ticket, refetched whenever something that changes it happens. */
function useTicketMemory(t: Ticket) {
  const [mem, setMem] = useState<TicketMemory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stamp = `${t.id}|${t.analysis?.analyzedAt}|${t.decision.status}|${t.decision.category}|${t.status}`;
  useEffect(() => {
    let live = true;
    setError(null);
    api.ticketMemory(t.id).then((m) => live && setMem(m)).catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [stamp]); // eslint-disable-line react-hooks/exhaustive-deps -- stamp covers t.id and every input that changes memory
  return { mem, error };
}

function MemoryUsedLine({ m }: { m: MemoryUsed }) {
  const parts = [
    m.history.length > 0 && plural(m.history.length, "earlier ticket") + " from this customer",
    m.corrections.length > 0 && plural(m.corrections.length, "agent correction") + ` (${m.corrections.map((c) => c.id).join(", ")})`,
  ].filter(Boolean);
  return (
    <p className="flex items-start gap-1.5 text-xs text-muted">
      <History className="mt-px size-3.5 shrink-0" />
      <span>{parts.length ? <>Context the AI saw: {parts.join(" · ")}.</> : "No memory used: no earlier tickets from this customer and no matching agent corrections."}</span>
    </p>
  );
}

function ClassifyForm({ ticket, onDone, submitLabel }: { ticket: Ticket; onDone?: () => void; submitLabel: string }) {
  // On manual-review tickets the AI's guess is hidden, so the form must not pre-fill it either.
  const hideAi = hasFlag(ticket.analysis?.flags, "manual_review");
  const [category, setCategory] = useState<Category | "">(ticket.decision.category ?? (hideAi ? "" : ticket.analysis?.category ?? ""));
  const [priority, setPriority] = useState<Priority | "">(ticket.decision.priority ?? (hideAi ? "" : ticket.analysis?.priority ?? ""));
  const save = useAction(api.decideClassification, "Classification saved");
  return (
    <div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-muted">Category<br />
          <select className={select} value={category} onChange={(e) => setCategory(e.target.value as Category)}>
            {!category && <option value="">Choose…</option>}
            {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">Priority<br />
          <select className={select} value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
            {!priority && <option value="">Choose…</option>}
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <Button variant="primary" loading={save.loading} disabled={!category || !priority}
          onClick={async () => { if (category && priority && await save.run(ticket.id, { category, priority })) onDone?.(); }}>{submitLabel}</Button>
        {onDone && <Button variant="ghost" onClick={onDone}>Cancel</Button>}
      </div>
      <ErrorText>{save.error}</ErrorText>
    </div>
  );
}

function AnalysisCard({ t }: { t: Ticket }) {
  const analyze = useAction(api.analyzeTicket, "Analysis updated");
  const accept = useAction(api.decideClassification, "Classification accepted");
  const [overriding, setOverriding] = useState(false);
  const a = t.analysis;
  const manual = hasFlag(a?.flags, "manual_review");

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="size-3.5 text-accent" /> AI analysis</span>}
        hint="A suggestion until an agent accepts it"
        right={a && <Button variant="ghost" loading={analyze.loading} onClick={() => analyze.run(t.id)}><RefreshCw className="size-3.5" /> Re-run</Button>} />
      <div className="p-4">
        {!a ? (
          <EmptyState icon={<Bot className="size-6" />} title="Not analysed yet">
            <p>Run the classifier to get a category, priority, sentiment, confidence and a two-sentence summary.</p>
            <Button className="mt-3" variant="primary" loading={analyze.loading} onClick={() => analyze.run(t.id)}><Sparkles className="size-3.5" /> Run AI analysis</Button>
            <ErrorText>{analyze.error}</ErrorText>
          </EmptyState>
        ) : manual ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-line bg-warn-soft px-3 py-2.5 text-[13px] text-warn">
              <b>AI suggestion hidden.</b> {a.flags.find((f) => f.type === "manual_review")?.reason}. Classify this ticket yourself.
            </div>
            <ConfidenceBar value={a.confidence} />
            {t.decision.status === "pending"
              ? <ClassifyForm ticket={t} submitLabel="Set classification" />
              : <DecisionLine t={t} onChange={() => setOverriding(true)} />}
            {overriding && t.decision.status !== "pending" && <ClassifyForm ticket={t} submitLabel="Save" onDone={() => setOverriding(false)} />}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="Category"><CategoryBadge c={a.category} /></Field>
              <Field label="Priority"><PriorityBadge p={a.priority} /></Field>
              <Field label="Sentiment"><SentimentBadge s={a.sentiment} /></Field>
              <Field label={`Confidence (min ${CONFIDENCE_THRESHOLD})`}><ConfidenceBar value={a.confidence} /></Field>
            </div>
            <div>
              <p className="text-xs text-muted">Summary</p>
              <p className="mt-0.5 text-[13px] leading-5">{a.summary}</p>
            </div>
            {a.memory && <MemoryUsedLine m={a.memory} />}
            <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
              {t.decision.status === "pending" && !overriding && (
                <>
                  <Button variant="primary" loading={accept.loading} onClick={() => accept.run(t.id, { accept: true })}><Check className="size-3.5" /> Accept classification</Button>
                  <Button onClick={() => setOverriding(true)}><Pencil className="size-3.5" /> Override</Button>
                  <span className="text-xs text-faint">Never applied automatically.</span>
                </>
              )}
              {t.decision.status !== "pending" && !overriding && <DecisionLine t={t} onChange={() => setOverriding(true)} />}
              {overriding && <ClassifyForm ticket={t} submitLabel="Save override" onDone={() => setOverriding(false)} />}
            </div>
            <ErrorText>{accept.error ?? analyze.error}</ErrorText>
            <p className="text-[11px] text-faint">{a.model} · {a.latencyMs} ms · {dateTime(a.analyzedAt)}</p>
          </div>
        )}
      </div>
    </Card>
  );
}

function DecisionLine({ t, onChange }: { t: Ticket; onChange: () => void }) {
  const d = t.decision;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[13px]">
      <ShieldCheck className="size-4 text-ok" />
      <span>{d.status === "accepted" ? "Accepted" : "Set"} by {d.decidedBy}</span>
      {d.category && <CategoryBadge c={d.category} />}
      {d.priority && <PriorityBadge p={d.priority} />}
      {d.status === "overridden" && t.analysis && !hasFlag(t.analysis.flags, "manual_review") && (
        <span className="text-xs text-muted">(AI said {CATEGORY_LABEL[t.analysis.category]} · {t.analysis.priority})</span>
      )}
      <span className="text-xs text-faint">{d.decidedAt && timeAgo(d.decidedAt)}</span>
      <button className="text-xs text-accent hover:underline" onClick={onChange}>Change</button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><p className="mb-1 text-xs text-muted">{label}</p>{children}</div>;
}

function ResponseCard({ t, docs }: { t: Ticket; docs: RetrievedDoc[] | null }) {
  const ws = useWorkspace();
  const [open, setOpen] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const gen = useAction(api.generateDraft, "Draft ready for review");
  const approve = useAction(api.approveDraft, "Response approved");
  const reject = useAction(api.rejectDraft, "Draft rejected");

  const drafts = ws.drafts.filter((d) => d.ticketId === t.id);
  const active = [...drafts].reverse().find((d) => d.status === "generated" || d.status === "edited");
  const history = drafts.filter((d) => d !== active).reverse();
  const undecided = t.decision.status === "pending";
  const managerBlock = hasFlag(t.analysis?.flags, "manager_review") && !t.managerApproval;

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><FileSearch className="size-3.5 text-accent" /> Response assistant</span>}
        hint="Drafted from the closest resolved tickets. Never sent automatically." />
      <div className="space-y-4 p-4">
        <div>
          <p className="mb-2 text-xs text-muted">Similar resolved tickets</p>
          {docs === null ? <p className="text-[13px] text-muted">Retrieving…</p> : docs.length === 0 ? (
            <p className="text-[13px] text-muted">No similar resolved tickets found.</p>
          ) : (
            <ul className="space-y-1.5">
              {docs.map((r) => (
                <li key={r.doc.id} className="rounded-lg border border-line">
                  <button className="flex w-full items-center gap-3 px-3 py-2 text-left" onClick={() => setOpen(open === r.doc.id ? null : r.doc.id)} aria-expanded={open === r.doc.id}>
                    <span className="font-mono text-xs text-muted">{r.doc.id}</span>
                    <span className="min-w-0 flex-1 truncate text-[13px]">{r.doc.subject}</span>
                    {r.doc.source === "ticket" && <Badge tone="accent">Learned</Badge>}
                    <span className="flex w-28 items-center gap-2">
                      <span className="h-1.5 flex-1 rounded-full bg-subtle"><span className="block h-full rounded-full bg-accent" style={{ width: `${r.similarity * 100}%` }} /></span>
                      <span className="font-mono text-[11px] tabular-nums text-muted">{r.similarity.toFixed(2)}</span>
                    </span>
                  </button>
                  {open === r.doc.id && <p className="border-t border-line px-3 py-2 text-[13px] text-muted">{r.doc.resolution}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>

        {active ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={active.status === "edited" ? "accent" : "info"}>{active.status === "edited" ? "Edited by agent" : "AI draft"}</Badge>
              <span className="text-xs text-muted">Sources: {active.sources.map((s) => `${s.id} (${s.similarity.toFixed(2)})`).join(", ") || "none"}</span>
            </div>
            <textarea value={active.body} onChange={(e) => api.editDraft(active.id, e.target.value)} rows={9} aria-label="Draft reply"
              className="w-full rounded-lg border border-line bg-subtle p-3 font-mono text-[13px] leading-5" />
            {active.body.includes("[Agent name]") && (
              <button className="text-xs text-accent hover:underline" onClick={() => api.editDraft(active.id, active.body.replaceAll("[Agent name]", ws.currentAgent))}>
                Replace [Agent name] with {ws.currentAgent}
              </button>
            )}
            {managerBlock && <p className="rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">Manager review required before this reply can be approved.</p>}
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" loading={approve.loading} disabled={managerBlock} onClick={() => approve.run(active.id)}><Check className="size-3.5" /> Approve response</Button>
              <Button variant="danger" onClick={() => setRejecting((v) => !v)}><X className="size-3.5" /> Reject</Button>
              <Button variant="ghost" loading={gen.loading} onClick={() => gen.run(t.id)}><RefreshCw className="size-3.5" /> Regenerate</Button>
            </div>
            {rejecting && (
              <div className="flex flex-wrap gap-2">
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this draft wrong? (used to improve prompts)"
                  className="h-8 min-w-[240px] flex-1 rounded-lg border border-line bg-surface px-3 text-[13px]" aria-label="Rejection reason" />
                <Button variant="danger" disabled={!reason.trim()} loading={reject.loading}
                  onClick={async () => { if (await reject.run(active.id, reason.trim())) { setRejecting(false); setReason(""); } }}>Confirm reject</Button>
              </div>
            )}
            <ErrorText>{approve.error ?? reject.error ?? gen.error}</ErrorText>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-line p-4 text-center">
            <p className="text-[13px] text-muted">{undecided ? "Confirm the classification above before drafting a reply." : "No active draft."}</p>
            <Button className="mt-2" variant="primary" disabled={undecided} loading={gen.loading} onClick={() => gen.run(t.id)}><Sparkles className="size-3.5" /> Generate draft</Button>
            <ErrorText>{gen.error}</ErrorText>
          </div>
        )}

        {history.length > 0 && (
          <details className="text-[13px]">
            <summary className="cursor-pointer text-xs text-muted">Previous drafts ({history.length})</summary>
            <ul className="mt-2 space-y-2">
              {history.map((d) => (
                <li key={d.id} className="rounded-lg bg-subtle p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <Badge tone={d.status === "approved" ? "ok" : "bad"}>{d.status === "approved" ? "Approved" : "Rejected"}</Badge>
                    <span className="text-xs text-muted">{d.decidedBy} · {d.decidedAt && timeAgo(d.decidedAt)}{d.rejectionReason && ` · “${d.rejectionReason}”`}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-muted">{d.body}</p>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}

function SafetyCard({ t }: { t: Ticket }) {
  const ws = useWorkspace();
  const senior = useAction(api.assignSenior, "Assigned to a senior agent");
  const mgr = useAction(api.recordManagerApproval, "Manager approval recorded");
  const flags = t.analysis?.flags ?? [];
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><ShieldAlert className="size-3.5" /> Safety & routing</span>} hint="Rules the AI cannot bypass" />
      <div className="space-y-3 p-4 text-[13px]">
        {!t.analysis && <p className="text-muted">Flags appear after analysis.</p>}
        {t.analysis && flags.length === 0 && <p className="flex items-center gap-2 text-muted"><ShieldCheck className="size-4 text-ok" /> No safety flags.</p>}
        {flags.map((f) => (
          <div key={f.type} className="space-y-2 rounded-lg border border-line p-3">
            <div className="flex items-center gap-2"><FlagBadge f={f.type} /><span className="text-muted">{f.reason}</span></div>
            {f.type === "senior_agent" && (
              t.assignee?.includes("Senior")
                ? <p className="text-xs text-ok">Assigned to {t.assignee}</p>
                : <Button loading={senior.loading} onClick={() => senior.run(t.id)}>Assign to senior agent</Button>
            )}
            {f.type === "manager_review" && (
              t.managerApproval
                ? <p className="text-xs text-ok">Manager approved by {t.managerApproval.by} · {timeAgo(t.managerApproval.at)}</p>
                : <>
                    <Button disabled={ws.currentRole !== "manager"} loading={mgr.loading} onClick={() => mgr.run(t.id)}>Record manager approval</Button>
                    {ws.currentRole !== "manager" && <p className="text-xs text-faint">Switch to the manager account (sidebar) to approve.</p>}
                  </>
            )}
            {f.type === "manual_review" && <p className="text-xs text-faint">The AI&apos;s category and priority are hidden; the agent classifies this ticket.</p>}
          </div>
        ))}
        <ErrorText>{senior.error ?? mgr.error}</ErrorText>
      </div>
    </Card>
  );
}

function EscalationCard({ t }: { t: Ticket }) {
  const ws = useWorkspace();
  const req = useAction(api.requestEscalation, "Escalation brief created");
  const escs = ws.escalations.filter((e) => e.ticketId === t.id);
  const pending = escs.find((e) => e.status === "pending_approval");
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><Siren className="size-3.5" /> Escalation</span>} hint="Posted to engineering only after approval" />
      <div className="space-y-3 p-4 text-[13px]">
        {escs.map((e) => (
          <Link key={e.id} href={`/escalations#${e.id}`} className="block rounded-lg border border-line p-3 hover:bg-hover">
            <div className="mb-1 flex items-center gap-2">
              <span className="font-mono text-xs text-muted">{e.id}</span>
              <Badge tone={e.status === "posted" ? "ok" : e.status === "rejected" ? "neutral" : "warn"}>
                {e.status === "posted" ? `Posted to ${e.channel}` : e.status === "rejected" ? "Rejected" : "Awaiting approval"}
              </Badge>
            </div>
            <p className="line-clamp-2 whitespace-pre-line text-muted">{e.brief.summary}</p>
          </Link>
        ))}
        {!pending && (
          <>
            <Button disabled={!t.analysis} loading={req.loading} onClick={() => req.run(t.id)}><Siren className="size-3.5" /> Request escalation</Button>
            {!t.analysis && <p className="text-xs text-faint">Analyse the ticket first.</p>}
          </>
        )}
        <ErrorText>{req.error}</ErrorText>
      </div>
    </Card>
  );
}

function MemoryCard({ mem, error }: { mem: TicketMemory | null; error: string | null }) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><History className="size-3.5" /> Customer history</span>}
        hint="What happened on this customer's earlier tickets" />
      <div className="space-y-3 p-4 text-[13px]">
        <ErrorText>{error}</ErrorText>
        {!mem && !error && <p className="text-muted">Recalling…</p>}
        {mem && mem.earlierTickets.length === 0 && <p className="text-muted">No earlier tickets from this customer.</p>}
        {mem?.earlierTickets.map((p) => (
          <div key={p.id} className="rounded-lg border border-line">
            <Link href={`/tickets/${p.id}`} className="block rounded-t-lg px-3 py-2 transition-colors hover:bg-hover">
              <span className="flex items-center justify-between gap-2 text-xs">
                <span className="font-mono text-muted">{p.id}</span>
                <span className="text-muted">{STATUS_LABEL[p.status]}</span>
              </span>
              <span className="mt-0.5 line-clamp-2 font-medium">{p.subject || "(no subject)"}</span>
            </Link>
            <ol className="space-y-1 border-t border-line px-3 py-2">
              {p.episodes.filter((e) => e.kind !== "opened").map((e, i) => (
                <li key={i} className="flex gap-2 text-xs">
                  <span className="min-w-0 flex-1 text-muted">{e.summary}</span>
                  <span className="shrink-0 text-faint">{timeAgo(e.occurredAt)}</span>
                </li>
              ))}
              <li className="text-xs text-faint">Opened {timeAgo(p.createdAt)}</li>
            </ol>
          </div>
        ))}
        {mem && mem.corrections.length > 0 && (
          <div className="space-y-1.5 border-t border-line pt-3">
            <p className="text-xs text-muted">Agent corrections on similar tickets</p>
            {mem.corrections.map((c) => (
              <p key={c.ticketId} className="text-xs">
                <Link href={`/tickets/${c.ticketId}`} className="font-mono text-muted hover:underline">{c.ticketId}</Link>{" "}
                AI said {CATEGORY_LABEL[c.ai.category]} · {c.ai.priority}, agent set <b>{CATEGORY_LABEL[c.agent.category]} · {c.agent.priority}</b>
                <span className="font-mono text-faint"> ({c.similarity.toFixed(2)})</span>
              </p>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

function ResolveCard({ t }: { t: Ticket }) {
  const [text, setText] = useState("");
  const resolve = useAction(api.resolveTicket, "Resolved and saved to knowledge");
  const blocked = t.decision.status === "pending" ? "Accept or set the classification first."
    : hasFlag(t.analysis?.flags, "manager_review") && !t.managerApproval ? "A manager must approve handling first." : null;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><CircleCheck className="size-3.5" /> Resolution</span>}
        hint="The fix becomes knowledge for similar tickets" />
      <div className="space-y-2 p-4 text-[13px]">
        {t.resolution ? (
          <>
            <p className="flex items-center gap-1.5 text-ok"><ShieldCheck className="size-4" /> Resolved by {t.resolution.by} · {timeAgo(t.resolution.at)}</p>
            <p className="whitespace-pre-wrap text-muted">{t.resolution.text}</p>
            <p className="text-xs text-faint">Saved to knowledge as {t.id}.</p>
          </>
        ) : (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); resolve.run(t.id, text).then((ok) => ok && setText("")); }}>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} aria-label="What fixed it"
              placeholder="What fixed it? e.g. Refunded the duplicate charge; it reaches the card in 5–7 business days."
              className="w-full rounded-lg border border-line bg-subtle p-2.5 text-[13px] leading-5" />
            <Button type="submit" variant="primary" disabled={!!blocked || text.trim().length < 10} loading={resolve.loading}>
              <CircleCheck className="size-3.5" /> Resolve ticket
            </Button>
            {blocked && <p className="text-xs text-faint">{blocked}</p>}
            <ErrorText>{resolve.error}</ErrorText>
          </form>
        )}
      </div>
    </Card>
  );
}

function Timeline({ t }: { t: Ticket }) {
  const ws = useWorkspace();
  const events = ws.audit.filter((e) => e.ticketId === t.id).sort((a, b) => b.at.localeCompare(a.at));
  return (
    <Card>
      <CardHeader title="Audit trail" hint="Every AI output and human decision" />
      <ol className="space-y-3 p-4">
        {events.length === 0 && <li className="text-[13px] text-muted">No activity yet.</li>}
        {events.map((e) => (
          <li key={e.id} className="flex gap-2.5 text-[13px]">
            <span className={clsx("mt-0.5", e.actor === "ai" ? "text-accent" : e.actor === "system" ? "text-warn" : "text-muted")}>
              {e.actor === "ai" ? <Bot className="size-3.5" /> : e.actor === "system" ? <ShieldAlert className="size-3.5" /> : <User className="size-3.5" />}
            </span>
            <div className="min-w-0">
              <p>{e.action}</p>
              {e.detail && <p className="text-xs text-muted">{e.detail}</p>}
              <p className="text-[11px] text-faint">{dateTime(e.at)}</p>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export default function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const ws = useWorkspace();
  const t = ws.tickets.find((x) => x.id === id);
  if (!t) {
    return <EmptyState title="Ticket not found"><Link className="text-accent" href="/inbox">Back to inbox</Link></EmptyState>;
  }
  return <TicketView t={t} />;
}

function TicketView({ t }: { t: Ticket }) {
  const { mem, error } = useTicketMemory(t);
  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-2"><Link href="/inbox" className="text-muted hover:text-ink" aria-label="Back to inbox"><ArrowLeft className="size-4" /></Link>{subjectOf(t)}</span>}
        subtitle={<>{t.id} · {STATUS_LABEL[t.status]} · {t.channel.replace("_", " ")} · {timeAgo(t.createdAt)}{t.assignee && ` · assigned to ${t.assignee}`}</>}
      />
      <div className="grid gap-4 p-4 md:p-6 xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <div className="flex items-center gap-3 border-b border-line px-4 py-3">
              <Avatar name={t.customer.name} />
              <div className="min-w-0 text-[13px]">
                <p className="font-medium">{t.customer.name}{t.customer.company && <span className="font-normal text-muted"> · {t.customer.company}</span>}</p>
                <p className="text-xs text-muted">{[t.customer.email, `${t.customer.plan} plan`].filter(Boolean).join(" · ")}</p>
              </div>
              <span className="ml-auto text-xs text-faint">{dateTime(t.createdAt)}</span>
            </div>
            <p className="whitespace-pre-wrap px-4 py-4 text-[14px] leading-6">{t.body}</p>
          </Card>
          <AnalysisCard t={t} />
          <ResponseCard t={t} docs={error ? [] : mem?.knowledge ?? null} />
        </div>
        <div className="space-y-4">
          <SafetyCard t={t} />
          <MemoryCard mem={mem} error={error} />
          <ResolveCard t={t} />
          <EscalationCard t={t} />
          <Timeline t={t} />
        </div>
      </div>
    </>
  );
}
