"use client";

import clsx from "clsx";
import { ArrowLeft, Bot, Check, FileSearch, Pencil, RefreshCw, ShieldAlert, ShieldCheck, Siren, Sparkles, User, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Avatar, PageHeader } from "@/components/shell";
import {
  Badge, Button, Card, CardHeader, CategoryBadge, ConfidenceBar, EmptyState, ErrorText, FlagBadge, PriorityBadge, SentimentBadge,
} from "@/components/ui";
import { api, useWorkspace } from "@/lib/api";
import { CATEGORIES, CATEGORY_LABEL, dateTime, PRIORITIES, STATUS_LABEL, timeAgo } from "@/lib/format";
import { CONFIDENCE_THRESHOLD, hasFlag } from "@/lib/rules";
import type { Category, Priority, RetrievedDoc, Ticket } from "@/lib/types";
import { useAction } from "@/lib/use-action";

const select = "h-8 rounded-lg border border-line bg-surface px-2 text-[13px]";

function ClassifyForm({ ticket, onDone, submitLabel }: { ticket: Ticket; onDone?: () => void; submitLabel: string }) {
  // On manual-review tickets the AI's guess is hidden, so the form must not pre-fill it either.
  const hideAi = hasFlag(ticket.analysis?.flags, "manual_review");
  const [category, setCategory] = useState<Category | "">(ticket.decision.category ?? (hideAi ? "" : ticket.analysis?.category ?? ""));
  const [priority, setPriority] = useState<Priority | "">(ticket.decision.priority ?? (hideAi ? "" : ticket.analysis?.priority ?? ""));
  const save = useAction(api.decideClassification);
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
  const analyze = useAction(api.analyzeTicket);
  const accept = useAction(api.decideClassification);
  const [overriding, setOverriding] = useState(false);
  const a = t.analysis;
  const manual = hasFlag(a?.flags, "manual_review");

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="size-3.5 text-accent" /> AI analysis</span>}
        hint="Module 1 · classification is a suggestion until an agent accepts it"
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

function ResponseCard({ t }: { t: Ticket }) {
  const ws = useWorkspace();
  const [docs, setDocs] = useState<RetrievedDoc[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const gen = useAction(api.generateDraft);
  const approve = useAction(api.approveDraft);
  const reject = useAction(api.rejectDraft);

  useEffect(() => {
    let live = true;
    api.retrieve(t.id).then((r) => live && setDocs(r));
    return () => { live = false; };
  }, [t.id]);

  const drafts = ws.drafts.filter((d) => d.ticketId === t.id);
  const active = [...drafts].reverse().find((d) => d.status === "generated" || d.status === "edited");
  const history = drafts.filter((d) => d !== active).reverse();
  const undecided = t.decision.status === "pending";
  const managerBlock = hasFlag(t.analysis?.flags, "manager_review") && !t.managerApproval;

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><FileSearch className="size-3.5 text-accent" /> Response assistant</span>}
        hint="Module 2 · drafts grounded in the 3 most similar resolved tickets; never sent automatically" />
      <div className="space-y-4 p-4">
        <div>
          <p className="mb-2 text-xs text-muted">Retrieved context <span className="text-faint">· mock TF-IDF retrieval, vector search arrives in step 3</span></p>
          {docs === null ? <p className="text-[13px] text-muted">Retrieving…</p> : docs.length === 0 ? (
            <p className="text-[13px] text-muted">No similar resolved tickets found.</p>
          ) : (
            <ul className="space-y-1.5">
              {docs.map((r) => (
                <li key={r.doc.id} className="rounded-lg border border-line">
                  <button className="flex w-full items-center gap-3 px-3 py-2 text-left" onClick={() => setOpen(open === r.doc.id ? null : r.doc.id)} aria-expanded={open === r.doc.id}>
                    <span className="font-mono text-xs text-muted">{r.doc.id}</span>
                    <span className="min-w-0 flex-1 truncate text-[13px]">{r.doc.subject}</span>
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
  const senior = useAction(api.assignSenior);
  const mgr = useAction(api.recordManagerApproval);
  const flags = t.analysis?.flags ?? [];
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><ShieldAlert className="size-3.5" /> Safety & routing</span>} hint="Module 4 · rules the AI cannot bypass" />
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
  const req = useAction(api.requestEscalation);
  const escs = ws.escalations.filter((e) => e.ticketId === t.id);
  const pending = escs.find((e) => e.status === "pending_approval");
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><Siren className="size-3.5" /> Escalation</span>} hint="Module 3 · brief for engineering, posted only after approval" />
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
  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-2"><Link href="/inbox" className="text-muted hover:text-ink" aria-label="Back to inbox"><ArrowLeft className="size-4" /></Link>{t.subject}</span>}
        subtitle={<>{t.id} · {STATUS_LABEL[t.status]} · {t.channel.replace("_", " ")} · {timeAgo(t.createdAt)}{t.assignee && ` · assigned to ${t.assignee}`}</>}
      />
      <div className="grid gap-4 p-4 md:p-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <div className="flex items-center gap-3 border-b border-line px-4 py-3">
              <Avatar name={t.customer.name} />
              <div className="min-w-0 text-[13px]">
                <p className="font-medium">{t.customer.name} <span className="font-normal text-muted">· {t.customer.company}</span></p>
                <p className="text-xs text-muted">{t.customer.email} · {t.customer.plan} plan</p>
              </div>
              <span className="ml-auto text-xs text-faint">{dateTime(t.createdAt)}</span>
            </div>
            <p className="whitespace-pre-wrap px-4 py-4 text-[14px] leading-6">{t.body}</p>
          </Card>
          <AnalysisCard t={t} />
          <ResponseCard t={t} />
        </div>
        <div className="space-y-4">
          <SafetyCard t={t} />
          <EscalationCard t={t} />
          <Timeline t={t} />
        </div>
      </div>
    </>
  );
}
