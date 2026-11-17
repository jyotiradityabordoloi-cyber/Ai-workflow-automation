"use client";

import { AlertTriangle, Bot, ShieldAlert, User } from "lucide-react";
import Link from "next/link";
import { Avatar, PageHeader } from "@/components/shell";
import { Card, CardHeader, FlagBadge, PriorityBadge, Stat } from "@/components/ui";
import { useWorkspace } from "@/lib/api";
import { CATEGORIES, CATEGORY_LABEL, PRIORITIES, timeAgo, subjectOf } from "@/lib/format";
import type { Ticket } from "@/lib/types";

const open = (t: Ticket) => t.status !== "resolved";

function Bars({ rows }: { rows: { label: string; value: number; tone?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2.5 p-4">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[110px_1fr_28px] items-center gap-3 text-[13px]">
          <span className="truncate text-muted">{r.label}</span>
          <div className="h-2 rounded-full bg-subtle">
            <div className={`h-full rounded-full ${r.tone ?? "bg-accent"}`} style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
          <span className="text-right font-mono text-xs tabular-nums">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function Overview() {
  const ws = useWorkspace();
  const openT = ws.tickets.filter(open);
  const flagged = openT.filter((t) => t.analysis?.flags.length);
  const pendingDrafts = ws.drafts.filter((d) => d.status === "generated" || d.status === "edited");
  const pendingEsc = ws.escalations.filter((e) => e.status === "pending_approval");
  const review = ws.tickets.filter((t) => t.status === "new" || t.status === "needs_review");
  const cat = (t: Ticket) => t.decision.category ?? t.analysis?.category;
  const pri = (t: Ticket) => t.decision.priority ?? t.analysis?.priority;

  const attention = [...openT]
    .filter((t) => t.analysis?.flags.length || pri(t) === "P1" || t.status === "new")
    .sort((a, b) => (b.analysis?.flags.length ?? 0) - (a.analysis?.flags.length ?? 0) || (pri(a) ?? "P9").localeCompare(pri(b) ?? "P9"))
    .slice(0, 7);

  const decisions = ws.tickets.filter((t) => t.decision.status !== "pending");
  const decidedDrafts = ws.drafts.filter((d) => d.status === "approved" || d.status === "rejected");
  const recent = [...ws.audit].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 8);

  return (
    <>
      <PageHeader title="Overview" subtitle={`Good to see you, ${ws.currentAgent.split(" ")[0]}. Here's what needs a human today.`} />
      <div className="space-y-4 p-4 md:p-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label="Open tickets" value={openT.length} hint={`${ws.tickets.length} in workspace`} />
          <Stat label="Waiting for your review" value={review.length} hint="New or unconfirmed classification" />
          <Stat label="P1 open" value={openT.filter((t) => pri(t) === "P1").length} tone="bad" />
          <Stat label="Safety flags open" value={flagged.length} tone={flagged.length ? "warn" : undefined} hint="Manual, senior or manager review" />
          <Stat label="Awaiting human approval" value={pendingDrafts.length + pendingEsc.length} hint={`${pendingDrafts.length} replies · ${pendingEsc.length} escalations`} />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader title="Needs attention" hint="Flagged, P1 or not yet analysed" right={<Link href="/inbox" className="text-xs text-accent hover:underline">Open inbox</Link>} />
            <ul className="divide-y divide-line">
              {attention.map((t) => (
                <li key={t.id}>
                  <Link href={`/tickets/${t.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-hover">
                    {pri(t) ? <PriorityBadge p={pri(t)!} /> : <span className="w-[26px] text-center text-[11px] text-faint">—</span>}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium">{subjectOf(t)}</p>
                      <p className="truncate text-xs text-muted">{t.customer.company} · {t.id} · {timeAgo(t.createdAt)}</p>
                    </div>
                    <div className="hidden gap-1 sm:flex">
                      {t.status === "new" && <span className="text-xs text-muted">Not analysed</span>}
                      {t.analysis?.flags.map((f) => <FlagBadge key={f.type} f={f.type} reason={f.reason} />)}
                    </div>
                  </Link>
                </li>
              ))}
              {attention.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted">Nothing urgent. Nice.</li>}
            </ul>
          </Card>

          <Card>
            <CardHeader title="Human-in-the-loop decisions" hint="What agents did with AI output in this workspace" />
            <dl className="grid grid-cols-2 gap-px bg-line text-[13px]">
              {[
                ["Classifications accepted", decisions.filter((t) => t.decision.status === "accepted").length],
                ["Classifications overridden", decisions.filter((t) => t.decision.status === "overridden").length],
                ["Replies approved", decidedDrafts.filter((d) => d.status === "approved").length],
                ["Replies rejected", decidedDrafts.filter((d) => d.status === "rejected").length],
                ["Escalations posted", ws.escalations.filter((e) => e.status === "posted").length],
                ["Escalations rejected", ws.escalations.filter((e) => e.status === "rejected").length],
              ].map(([k, v]) => (
                <div key={k} className="bg-surface px-4 py-3">
                  <dt className="text-xs text-muted">{k}</dt>
                  <dd className="mt-0.5 text-lg font-semibold tabular-nums">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="px-4 py-3 text-xs text-faint">Activity counts, not accuracy. Accuracy is measured on the AI evaluation page once evaluation runs exist.</p>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardHeader title="Open tickets by category" />
            <Bars rows={CATEGORIES.map((c) => ({ label: CATEGORY_LABEL[c], value: openT.filter((t) => cat(t) === c).length }))} />
          </Card>
          <Card>
            <CardHeader title="Open tickets by priority" />
            <Bars rows={PRIORITIES.map((p) => ({ label: p, value: openT.filter((t) => pri(t) === p).length, tone: p === "P1" ? "bg-bad" : p === "P2" ? "bg-warn" : "bg-faint" }))} />
          </Card>
          <Card>
            <CardHeader title="Recent activity" />
            <ul className="space-y-2.5 p-4">
              {recent.map((e) => (
                <li key={e.id} className="flex gap-2.5 text-[13px]">
                  <span className="mt-0.5 text-faint">{e.actor === "ai" ? <Bot className="size-3.5" /> : e.actor === "system" ? <ShieldAlert className="size-3.5" /> : <User className="size-3.5" />}</span>
                  <div className="min-w-0">
                    <p className="truncate"><Link href={`/tickets/${e.ticketId}`} className="font-mono text-xs text-muted hover:text-ink">{e.ticketId}</Link> {e.action}</p>
                    {e.detail && <p className="truncate text-xs text-muted">{e.detail}</p>}
                  </div>
                  <span className="ml-auto shrink-0 text-xs text-faint">{timeAgo(e.at)}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {flagged.some((t) => t.analysis?.flags.some((f) => f.type === "senior_agent") && !t.assignee?.includes("Senior")) && (
          <div className="flex items-center gap-2 rounded-xl border border-line bg-bad-soft px-4 py-3 text-[13px] text-bad">
            <AlertTriangle className="size-4" /> Angry P1 customers are waiting for a senior agent.
            <Link href="/inbox?flag=senior_agent" className="ml-auto font-medium underline">Review</Link>
          </div>
        )}
        <p className="flex items-center gap-2 text-xs text-faint"><Avatar name={ws.currentAgent} /> Signed in as {ws.currentAgent} ({ws.currentRole})</p>
      </div>
    </>
  );
}
