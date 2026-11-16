"use client";

import clsx from "clsx";
import { Check, Hash, Siren, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorText, PriorityBadge } from "@/components/ui";
import { api, useWorkspace } from "@/lib/api";
import { dateTime, PRIORITIES, timeAgo } from "@/lib/format";
import type { Escalation, EscalationStatus, Priority } from "@/lib/types";
import { useAction } from "@/lib/use-action";

/** Renders a posted brief the way Slack would display it (the backend posts the same fields as Block Kit). */
function SlackMessage({ e }: { e: Escalation }) {
  return (
    <div className="mt-1 space-y-1.5 text-[13px] leading-5">
      <p className="font-semibold">🚨 [{e.brief.priority}] Escalation {e.ticketId}</p>
      <div><p className="font-semibold">Summary</p><p className="whitespace-pre-line text-muted">{e.brief.summary}</p></div>
      <div><p className="font-semibold">Already tried</p>
        <ul className="list-disc pl-5 text-muted">{e.brief.troubleshooting.map((s) => <li key={s}>{s}</li>)}</ul></div>
      <p><span className="font-semibold">Impact</span> <span className="text-muted">{e.brief.impact}</span></p>
      <a className="text-info hover:underline" href={e.brief.ticketUrl}>{e.brief.ticketUrl.replace("https://", "")}</a>
    </div>
  );
}

function PendingCard({ e }: { e: Escalation }) {
  const [summary, setSummary] = useState(e.brief.summary);
  const [steps, setSteps] = useState(e.brief.troubleshooting.join("\n"));
  const [priority, setPriority] = useState<Priority>(e.brief.priority);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const approve = useAction(async () => {
    await api.updateEscalationBrief(e.id, { ...e.brief, summary: summary.trim(), priority, troubleshooting: steps.split("\n").map((s) => s.trim()).filter(Boolean) });
    await api.approveEscalation(e.id);
  });
  const reject = useAction(api.rejectEscalation);
  const lines = summary.split("\n").filter(Boolean).length;

  return (
    <div className="space-y-3 p-4">
      <label className="block text-xs text-muted">Issue summary <span className={clsx(lines > 2 && "text-warn")}>({lines}/2 lines)</span>
        <textarea value={summary} onChange={(ev) => setSummary(ev.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-line bg-subtle p-2.5 text-[13px] text-ink" />
      </label>
      <label className="block text-xs text-muted">Troubleshooting already done (one per line)
        <textarea value={steps} onChange={(ev) => setSteps(ev.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-line bg-subtle p-2.5 text-[13px] text-ink" />
      </label>
      <div className="flex flex-wrap items-end gap-3 text-xs text-muted">
        <label>Priority<br />
          <select value={priority} onChange={(ev) => setPriority(ev.target.value as Priority)} className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink">
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <span>Ticket link: <a className="text-accent" href={e.brief.ticketUrl}>{e.brief.ticketUrl.replace("https://", "")}</a></span>
        <span>Impact: {e.brief.impact}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <Button variant="primary" loading={approve.loading} disabled={!summary.trim()} onClick={() => approve.run()}><Check className="size-3.5" /> Approve & post to {e.channel}</Button>
        <Button variant="danger" onClick={() => setRejecting((v) => !v)}><X className="size-3.5" /> Reject</Button>
        <span className="text-xs text-faint">Slack is simulated: no credentials configured.</span>
      </div>
      {rejecting && (
        <div className="flex flex-wrap gap-2">
          <input value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="Reason (e.g. support can resolve this)" aria-label="Rejection reason"
            className="h-8 min-w-[240px] flex-1 rounded-lg border border-line bg-surface px-3 text-[13px]" />
          <Button variant="danger" disabled={!reason.trim()} loading={reject.loading} onClick={() => reject.run(e.id, reason.trim())}>Confirm reject</Button>
        </div>
      )}
      <ErrorText>{approve.error ?? reject.error}</ErrorText>
    </div>
  );
}

const TABS: { key: EscalationStatus; label: string }[] = [
  { key: "pending_approval", label: "Awaiting approval" },
  { key: "posted", label: "Posted" },
  { key: "rejected", label: "Rejected" },
];

export default function EscalationsPage() {
  const ws = useWorkspace();
  const [tab, setTab] = useState<EscalationStatus>("pending_approval");
  const list = ws.escalations.filter((e) => e.status === tab).sort((a, b) => b.requestedAt.localeCompare(a.requestedAt));
  const posted = ws.escalations.filter((e) => e.status === "posted").sort((a, b) => (b.decidedAt ?? "").localeCompare(a.decidedAt ?? ""));
  const subject = (id: string) => ws.tickets.find((t) => t.id === id)?.subject ?? id;

  return (
    <>
      <PageHeader title="Escalations" subtitle="AI-written engineering briefs. Nothing is posted until a human approves it." />
      <div className="grid gap-4 p-4 md:p-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <div className="flex gap-1">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={clsx("rounded-lg px-3 py-1.5 text-[13px] transition", tab === t.key ? "bg-hover font-medium" : "text-muted hover:bg-hover hover:text-ink")}>
                {t.label} <span className="text-xs text-faint tabular-nums">{ws.escalations.filter((e) => e.status === t.key).length}</span>
              </button>
            ))}
          </div>
          {list.length === 0 && (
            <Card><EmptyState icon={<Siren className="size-6" />} title="Nothing here">Escalations are requested from a ticket&apos;s workspace.</EmptyState></Card>
          )}
          {list.map((e) => (
            <Card key={e.id} className="scroll-mt-6">
              <div id={e.id} />
              <CardHeader
                title={<span className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-muted">{e.id}</span>
                  <Link href={`/tickets/${e.ticketId}`} className="hover:underline">{subject(e.ticketId)}</Link><PriorityBadge p={e.brief.priority} /></span>}
                hint={`Requested by ${e.requestedBy} · ${timeAgo(e.requestedAt)} · ${e.channel}`}
                right={e.status !== "pending_approval" && <Badge tone={e.status === "posted" ? "ok" : "neutral"}>{e.status === "posted" ? "Posted" : "Rejected"}</Badge>} />
              {e.status === "pending_approval" ? <PendingCard e={e} /> : (
                <div className="space-y-2 p-4 text-[13px]">
                  <p className="whitespace-pre-line">{e.brief.summary}</p>
                  <ul className="list-disc pl-5 text-muted">{e.brief.troubleshooting.map((s) => <li key={s}>{s}</li>)}</ul>
                  <p className="text-xs text-faint">{e.status === "posted" ? "Approved" : "Rejected"} by {e.decidedBy} · {e.decidedAt && dateTime(e.decidedAt)}{e.rejectionReason && ` · “${e.rejectionReason}”`}</p>
                </div>
              )}
            </Card>
          ))}
        </div>

        <Card className="h-fit">
          <CardHeader title={<span className="flex items-center gap-1.5"><Hash className="size-3.5" /> eng-escalations</span>} hint="Simulated Slack channel · shows exactly what was posted" />
          <ul className="space-y-4 p-4">
            {posted.length === 0 && <li className="text-[13px] text-muted">No messages yet.</li>}
            {posted.map((e) => (
              <li key={e.id} className="flex gap-2.5">
                <span className="grid size-7 shrink-0 place-items-center rounded-md bg-accent text-[11px] font-semibold text-white">SF</span>
                <div className="min-w-0">
                  <p className="text-[13px]"><b>SupportFlow</b> <span className="text-xs text-faint">{e.decidedAt && dateTime(e.decidedAt)} · approved by {e.decidedBy}</span></p>
                  <SlackMessage e={e} />
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
