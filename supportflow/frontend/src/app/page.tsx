"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowRight, CircleCheck, Clock3, Cpu, Inbox, Minus, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Donut, LineChart } from "@/components/charts";
import { PageHeader } from "@/components/shell";
import { Card, CardHeader, FlagBadge, PriorityBadge } from "@/components/ui";
import { useWorkspace } from "@/lib/api";
import { CATEGORIES, CATEGORY_LABEL, customerLabel, PRIORITIES, STATUS_LABEL, subjectOf, timeAgo } from "@/lib/format";
import { agreement, kpis, volume, type Delta, type Range } from "@/lib/overview";
import type { Ticket, TicketStatus } from "@/lib/types";

/** The current time, refreshed every minute so "last 24 hours" stays true while the page is open. */
function useNow() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

// ---------------------------------------------------------------- KPI cards
function DeltaPill({ d, good }: { d: Delta; good: "up" | "down" | "none" }) {
  if (!d) return null;
  const better = good !== "none" && d.dir !== 0 && (d.dir > 0) === (good === "up");
  const worse = good !== "none" && d.dir !== 0 && !better;
  const Icon = d.dir > 0 ? TrendingUp : d.dir < 0 ? TrendingDown : Minus;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium tabular-nums",
      better ? "bg-c2-soft text-c2" : worse ? "bg-bad-soft text-bad" : "bg-subtle text-muted")}>
      <Icon className="size-3" />{d.text}
    </span>
  );
}

function Kpi({ label, value, icon, tone = "c1", foot }: { label: string; value: ReactNode; icon: ReactNode; tone?: "c1" | "c2"; foot: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] text-muted">{label}</p>
          <p className="mt-1 text-[28px] leading-none font-semibold tracking-tight tabular-nums">{value}</p>
        </div>
        <span className={clsx("grid size-9 shrink-0 place-items-center rounded-full", tone === "c1" ? "bg-c1-soft text-c1" : "bg-c2-soft text-c2")}>{icon}</span>
      </div>
      <div className="mt-3 flex min-h-5 items-center gap-2 text-xs text-faint">{foot}</div>
    </Card>
  );
}

// ---------------------------------------------------------------- volume chart
function VolumeCard({ tickets, audit, now }: { tickets: Ticket[]; audit: ReturnType<typeof useWorkspace>["audit"]; now: number }) {
  const [range, setRange] = useState<Range>("48h");
  const v = useMemo(() => volume(tickets, audit, now, range), [tickets, audit, now, range]);
  const inTotal = v.incoming.reduce((a, b) => a + b, 0);
  const outTotal = v.resolved.reduce((a, b) => a + b, 0);
  return (
    <Card className="flex min-w-0 flex-col xl:col-span-2">
      <CardHeader title="Ticket volume" hint={`Received and resolved over the last ${range === "48h" ? "48 hours" : "7 days"}`}
        right={
          <div className="flex rounded-lg bg-subtle p-0.5 text-xs" role="group" aria-label="Time range">
            {(["48h", "7d"] as const).map((r) => (
              <button key={r} onClick={() => setRange(r)} aria-pressed={range === r}
                className={clsx("rounded-md px-2.5 py-1 font-medium transition-colors duration-150",
                  range === r ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink")}>
                {r === "48h" ? "48 hours" : "7 days"}
              </button>
            ))}
          </div>
        } />
      <div className="flex flex-wrap gap-x-5 gap-y-1 px-4 pt-2 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-c1" />Received <b className="font-semibold text-ink tabular-nums">{inTotal}</b></span>
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-c2" />Resolved <b className="font-semibold text-ink tabular-nums">{outTotal}</b></span>
      </div>
      <div className="min-h-[240px] flex-1 px-2 pt-1 pb-2">
        <LineChart labels={v.labels}
          series={[
            { key: "in", label: "Received", color: "var(--c1)", values: v.incoming },
            { key: "out", label: "Resolved", color: "var(--c2)", values: v.resolved },
          ]}
          describe={`Ticket volume over the last ${range === "48h" ? "48 hours" : "7 days"}: ${inTotal} received, ${outTotal} resolved.`} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- AI activity
function AiActivity({ audit }: { audit: ReturnType<typeof useWorkspace>["audit"] }) {
  const items = [...audit].filter((e) => e.actor !== "agent").sort((a, b) => b.at.localeCompare(a.at)).slice(0, 3);
  return (
    <div className="min-w-0 rounded-2xl bg-c1-strong p-4 text-white">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 text-[13px] font-semibold"><Sparkles className="size-4" />AI activity</p>
        <Link href="/inbox?tab=review" className="inline-flex items-center gap-1 rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium transition-[background-color,scale] duration-150 ease-[var(--ease-out)] hover:bg-white/25 active:scale-[.97]">
          Review queue <ArrowRight className="size-3" />
        </Link>
      </div>
      <ul className="mt-3 space-y-2">
        {items.length === 0 && <li className="rounded-xl bg-white/10 px-3 py-2.5 text-[13px] text-white/80">No AI activity yet.</li>}
        {items.map((e) => (
          <li key={e.id}>
            <Link href={`/tickets/${e.ticketId}`} className="flex items-start gap-2.5 rounded-xl bg-white/10 px-3 py-2.5 transition-colors duration-150 hover:bg-white/15">
              <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-white/15">
                {e.actor === "ai" ? <Sparkles className="size-3" /> : <AlertTriangle className="size-3" />}
              </span>
              <span className="min-w-0 flex-1 text-[13px] leading-5">
                <span className="font-medium">{e.action}</span> <span className="font-mono text-xs text-white/70">{e.ticketId}</span>
                {e.detail && <span className="block truncate text-xs text-white/70">{e.detail}</span>}
              </span>
              <span className="shrink-0 text-[11px] text-white/60">{timeAgo(e.at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- categories and priorities
const PRI_COLOR = { P1: "bg-bad", P2: "bg-warn", P3: "bg-faint" } as const;

function CategoryCard({ open }: { open: Ticket[] }) {
  const cat = (t: Ticket) => t.decision.category ?? t.analysis?.category;
  const pri = (t: Ticket) => t.decision.priority ?? t.analysis?.priority;
  const rows = CATEGORIES.map((c) => ({ c, n: open.filter((t) => cat(t) === c).length })).sort((a, b) => b.n - a.n);
  const max = Math.max(1, ...rows.map((r) => r.n));
  const byPri = PRIORITIES.map((p) => ({ p, n: open.filter((t) => pri(t) === p).length }));
  const priTotal = Math.max(1, byPri.reduce((a, b) => a + b.n, 0));
  return (
    <Card className="min-w-0">
      <CardHeader title="Open tickets by category" hint="Agent's classification, else the AI's" />
      <div className="space-y-3 px-4 pt-3 pb-4">
        {rows.map(({ c, n }) => (
          <Link key={c} href={`/inbox?category=${c}`} className="group grid grid-cols-[118px_minmax(0,1fr)_28px] items-center gap-3 text-[13px]">
            <span className="truncate text-muted transition-colors duration-150 group-hover:text-ink">{CATEGORY_LABEL[c]}</span>
            <span className="h-2 rounded-full bg-subtle"><span className="block h-full rounded-full bg-c1" style={{ width: `${(n / max) * 100}%` }} /></span>
            <span className="text-right font-mono text-xs tabular-nums">{n}</span>
          </Link>
        ))}
        <div className="border-t border-line pt-3">
          <p className="mb-2 text-xs text-muted">By priority</p>
          <div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-subtle" role="img"
            aria-label={byPri.map(({ p, n }) => `${p}: ${n}`).join(", ")}>
            {byPri.map(({ p, n }) => n > 0 && <span key={p} className={PRI_COLOR[p]} style={{ width: `${(n / priTotal) * 100}%` }} />)}
          </div>
          <div className="mt-2 flex gap-4 text-xs text-muted">
            {byPri.map(({ p, n }) => (
              <Link key={p} href={`/inbox?priority=${p}`} className="flex items-center gap-1.5 hover:text-ink">
                <span className={clsx("size-2 rounded-full", PRI_COLOR[p])} />{p} <b className="font-semibold text-ink tabular-nums">{n}</b>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- needs attention
const STATUS_PILL: Record<TicketStatus, string> = {
  new: "bg-info-soft text-info", needs_review: "bg-c1-soft text-c1", in_progress: "bg-subtle text-muted",
  awaiting_approval: "bg-warn-soft text-warn", escalated: "bg-bad-soft text-bad", resolved: "bg-c2-soft text-c2",
};

function AttentionCard({ open }: { open: Ticket[] }) {
  const pri = (t: Ticket) => t.decision.priority ?? t.analysis?.priority;
  const rows = [...open]
    .filter((t) => t.analysis?.flags.length || pri(t) === "P1" || t.status === "new")
    .sort((a, b) => (b.analysis?.flags.length ?? 0) - (a.analysis?.flags.length ?? 0) || (pri(a) ?? "P9").localeCompare(pri(b) ?? "P9"))
    .slice(0, 6);
  return (
    <Card className="min-w-0 xl:col-span-2">
      <CardHeader title="Needs attention" hint="Flagged, P1 or not yet analysed"
        right={<Link href="/inbox" className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-xs font-medium transition-[background-color,scale] duration-150 ease-[var(--ease-out)] hover:bg-hover active:scale-[.97]">View inbox <ArrowRight className="size-3" /></Link>} />
      <div className="overflow-x-auto px-4 pt-3 pb-4">
        {rows.length === 0 ? <p className="py-8 text-center text-sm text-muted">Nothing urgent right now.</p> : (
          <table className="w-full min-w-[560px] text-[13px]">
            <thead>
              <tr className="text-left text-xs text-muted">
                {["Customer", "Ticket", "Safety flag", "Status", "Received"].map((h, i) => (
                  <th key={h} className={clsx("bg-subtle px-3 py-2 font-medium", i === 0 && "rounded-l-lg", i === 4 && "rounded-r-lg text-right")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const flags = t.analysis?.flags ?? [];
                const p = pri(t);
                return (
                  <tr key={t.id} className="group border-b border-line last:border-0">
                    <td className="max-w-40 truncate px-3 py-2.5 text-muted">{customerLabel(t.customer)}</td>
                    <td className="max-w-0 px-3 py-2.5">
                      <Link href={`/tickets/${t.id}`} className="flex min-w-0 items-center gap-2 font-medium group-hover:underline">
                        {p ? <PriorityBadge p={p} /> : null}<span className="truncate">{subjectOf(t)}</span>
                      </Link>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {flags[0] ? <span className="inline-flex items-center gap-1"><FlagBadge f={flags[0].type} reason={flags[0].reason} />{flags.length > 1 && <span className="text-xs text-faint">+{flags.length - 1}</span>}</span> : <span className="text-faint">–</span>}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap"><span className={clsx("rounded-md px-2 py-0.5 text-xs font-medium", STATUS_PILL[t.status])}>{STATUS_LABEL[t.status]}</span></td>
                    <td className="px-3 py-2.5 text-right whitespace-nowrap text-faint tabular-nums">{timeAgo(t.createdAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- agreement donut
function AgreementCard({ tickets, replies, escalations }: { tickets: Ticket[]; replies: number; escalations: number }) {
  const a = agreement(tickets);
  const judged = a.accepted + a.overridden;
  return (
    <Card className="min-w-0">
      <CardHeader title="Agents agree with the AI" hint="Share of AI classifications kept as they were" />
      <div className="flex items-center gap-5 px-4 pt-3 pb-4">
        <Donut a={a.accepted} b={a.overridden} colorA="var(--c2)" colorB="var(--c1)"
          label={judged ? `${Math.round((a.accepted / judged) * 100)} percent of ${judged} AI classifications kept` : "No decisions yet"} />
        <dl className="min-w-0 flex-1 space-y-2.5 text-[13px]">
          {[
            ["Kept as suggested", a.accepted, "bg-c2"],
            ["Changed by an agent", a.overridden, "bg-c1"],
            ["Classified by hand", a.manual, "bg-faint"],
          ].map(([k, v, dot]) => (
            <div key={k as string} className="flex items-center gap-2">
              <span className={clsx("size-2 shrink-0 rounded-full", dot as string)} />
              <dt className="min-w-0 flex-1 truncate text-muted">{k}</dt>
              <dd className="font-semibold tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-faint">
        {judged ? `From ${judged} decided ticket${judged === 1 ? "" : "s"}. ` : "Fills in as agents decide tickets. "}
        Replies approved {replies} · escalations posted {escalations}. Accuracy against labelled tickets is on the <Link href="/evaluation" className="underline hover:text-ink">AI evaluation</Link> page.
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------- page
export default function Overview() {
  const ws = useWorkspace();
  const now = useNow();
  const open = ws.tickets.filter((t) => t.status !== "resolved");
  const k = useMemo(() => kpis(ws.tickets, ws.audit, now), [ws.tickets, ws.audit, now]);
  const hour = new Date(now).getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const seniorWaiting = open.some((t) => t.analysis?.flags.some((f) => f.type === "senior_agent") && !t.assignee?.includes("Senior"));

  return (
    <>
      <PageHeader title={`${greeting}, ${ws.currentAgent.split(" ")[0]}`} subtitle="Here's what's happening in your support queue." />
      <div className="space-y-4 p-4 md:p-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi label="Open tickets" value={k.open.value} icon={<Inbox className="size-4" />}
            foot={<><DeltaPill d={k.open.delta} good="down" />vs 24 hours ago</>} />
          <Kpi label="Waiting for review" value={k.review.value} icon={<Clock3 className="size-4" />}
            foot={k.review.oldestReviewH !== null ? <>Oldest waiting {k.review.oldestReviewH < 1 ? "under an hour" : `${k.review.oldestReviewH}h`}</> : "Nothing waiting"} />
          <Kpi label="Resolved, last 24h" value={k.resolved.value} tone="c2" icon={<CircleCheck className="size-4" />}
            foot={<><DeltaPill d={k.resolved.delta} good="up" />vs previous 24h</>} />
          <Kpi label="Median AI time" value={k.aiTime.value !== null ? <>{k.aiTime.value}<span className="ml-0.5 text-base font-medium text-muted">ms</span></> : "–"} icon={<Cpu className="size-4" />}
            foot={k.aiTime.delta ? <><DeltaPill d={k.aiTime.delta} good="down" />vs previous 24h</> : "Per classification, model only"} />
        </div>

        {seniorWaiting && (
          <div className="flex items-center gap-2 rounded-xl border border-bad/20 bg-bad-soft px-4 py-3 text-[13px] text-bad">
            <AlertTriangle className="size-4 shrink-0" /> Angry P1 customers are waiting for a senior agent.
            <Link href="/inbox?flag=senior_agent" className="ml-auto font-medium underline">Review</Link>
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-3">
          <VolumeCard tickets={ws.tickets} audit={ws.audit} now={now} />
          <div className="grid min-w-0 content-start gap-4 md:grid-cols-2 xl:grid-cols-1">
            <AiActivity audit={ws.audit} />
            <CategoryCard open={open} />
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <AttentionCard open={open} />
          <AgreementCard tickets={ws.tickets}
            replies={ws.drafts.filter((d) => d.status === "approved").length}
            escalations={ws.escalations.filter((e) => e.status === "posted").length} />
        </div>
      </div>
    </>
  );
}
