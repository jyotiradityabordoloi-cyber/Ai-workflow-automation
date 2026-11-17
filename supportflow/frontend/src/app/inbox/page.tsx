"use client";

import clsx from "clsx";
import { Inbox as InboxIcon, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { NewTicketButton } from "@/components/new-ticket";
import { PageHeader } from "@/components/shell";
import { Badge, ConfidenceBar, EmptyState, FlagBadge, PriorityBadge, SentimentBadge } from "@/components/ui";
import { useWorkspace } from "@/lib/api";
import { CATEGORIES, CATEGORY_LABEL, FLAG_LABEL, PRIORITIES, STATUS_LABEL, timeAgo, subjectOf } from "@/lib/format";
import type { FlagType, Ticket, TicketStatus } from "@/lib/types";

const TABS: { key: string; label: string; match: (t: Ticket) => boolean }[] = [
  { key: "open", label: "Open", match: (t) => t.status !== "resolved" },
  { key: "review", label: "Needs review", match: (t) => t.status === "new" || t.status === "needs_review" },
  { key: "approval", label: "Awaiting approval", match: (t) => t.status === "awaiting_approval" },
  { key: "escalated", label: "Escalated", match: (t) => t.status === "escalated" },
  { key: "resolved", label: "Resolved", match: (t) => t.status === "resolved" },
  { key: "all", label: "All", match: () => true },
];

const STATUS_DOT: Record<TicketStatus, string> = {
  new: "bg-info", needs_review: "bg-ink", in_progress: "bg-faint", awaiting_approval: "bg-warn", escalated: "bg-bad", resolved: "bg-ok",
};

function InboxView() {
  const ws = useWorkspace();
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") ?? "open";
  const q = params.get("q") ?? "";
  const cat = params.get("category") ?? "";
  const pri = params.get("priority") ?? "";
  const flag = params.get("flag") ?? "";
  const sort = params.get("sort") ?? "priority";

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v); else next.delete(k);
    router.replace(`/inbox?${next.toString()}`, { scroll: false });
  };

  const rows = useMemo(() => {
    const m = TABS.find((x) => x.key === tab) ?? TABS[0];
    const needle = q.toLowerCase();
    const list = ws.tickets.filter((t) => {
      const c = t.decision.category ?? t.analysis?.category;
      const p = t.decision.priority ?? t.analysis?.priority;
      return m.match(t)
        && (!needle || `${t.id} ${subjectOf(t)} ${t.body} ${t.customer.company} ${t.customer.name}`.toLowerCase().includes(needle))
        && (!cat || c === cat) && (!pri || p === pri)
        && (!flag || t.analysis?.flags.some((f) => f.type === flag));
    });
    return list.sort((a, b) => sort === "newest"
      ? b.createdAt.localeCompare(a.createdAt)
      : (a.decision.priority ?? a.analysis?.priority ?? "P9").localeCompare(b.decision.priority ?? b.analysis?.priority ?? "P9") || b.createdAt.localeCompare(a.createdAt));
  }, [ws.tickets, tab, q, cat, pri, flag, sort]);

  const select = "h-8 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink";

  return (
    <>
      <PageHeader title="Inbox" subtitle="Every AI classification waits for an agent to accept or override it." right={<NewTicketButton />} />
      <div className="border-b border-line bg-surface px-4 md:px-6">
        <div className="flex gap-1 overflow-x-auto">
          {TABS.map((t) => {
            const n = ws.tickets.filter(t.match).length;
            return (
              <button key={t.key} onClick={() => set("tab", t.key === "open" ? "" : t.key)}
                className={clsx("whitespace-nowrap border-b-2 px-3 py-2.5 text-[13px] transition", tab === t.key ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
                {t.label} <span className="ml-1 text-xs text-faint tabular-nums">{n}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 md:px-6">
        <label className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-faint" />
          <input value={q} onChange={(e) => set("q", e.target.value)} placeholder="Search tickets, customers, IDs…"
            className="h-8 w-full rounded-lg border border-line bg-surface pr-3 pl-8 text-[13px]" aria-label="Search tickets" />
        </label>
        <select className={select} value={cat} onChange={(e) => set("category", e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
        </select>
        <select className={select} value={pri} onChange={(e) => set("priority", e.target.value)} aria-label="Priority">
          <option value="">All priorities</option>
          {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
        </select>
        <select className={select} value={flag} onChange={(e) => set("flag", e.target.value)} aria-label="Safety flag">
          <option value="">Any flag</option>
          {(Object.keys(FLAG_LABEL) as FlagType[]).map((f) => <option key={f} value={f}>{FLAG_LABEL[f]}</option>)}
        </select>
        <select className={select} value={sort} onChange={(e) => set("sort", e.target.value === "priority" ? "" : e.target.value)} aria-label="Sort">
          <option value="priority">Sort: priority</option>
          <option value="newest">Sort: newest</option>
        </select>
      </div>

      <div className="px-4 pb-6 md:px-6">
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          {rows.length === 0 ? (
            <EmptyState icon={<InboxIcon className="size-6" />} title="No tickets match">Try another tab or clear the filters.</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {rows.map((t) => {
                const a = t.analysis;
                const c = t.decision.category ?? a?.category;
                const p = t.decision.priority ?? a?.priority;
                const manual = a?.flags.some((f) => f.type === "manual_review");
                return (
                  <li key={t.id}>
                    <Link href={`/tickets/${t.id}`} className="grid grid-cols-[34px_1fr] gap-x-3 gap-y-1 px-4 py-3 hover:bg-hover lg:grid-cols-[34px_minmax(0,1fr)_150px_180px_96px_auto_70px] lg:items-center">
                      <div>{p ? <PriorityBadge p={p} /> : <Badge tone="info">New</Badge>}</div>
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium">{subjectOf(t)}</p>
                        <p className="truncate text-xs text-muted">{a && !manual ? a.summary : t.body}</p>
                      </div>
                      <div className="col-start-2 truncate text-xs text-muted lg:col-start-auto">{t.customer.company} <span className="text-faint">· {t.customer.plan}</span></div>
                      <div className="col-start-2 flex gap-1 lg:col-start-auto">
                        {c && !manual && <span className="text-xs text-muted">{CATEGORY_LABEL[c]}</span>}
                        {a && !manual && (a.sentiment === "angry" || a.sentiment === "frustrated") && <SentimentBadge s={a.sentiment} />}
                      </div>
                      <div className="col-start-2 lg:col-start-auto">{a && <ConfidenceBar value={a.confidence} compact />}</div>
                      <div className="col-start-2 flex flex-wrap gap-1 lg:col-start-auto">
                        <span className="inline-flex items-center gap-1.5 text-xs text-muted"><span className={clsx("size-1.5 rounded-full", STATUS_DOT[t.status])} />{STATUS_LABEL[t.status]}</span>
                        {a?.flags.map((f) => <FlagBadge key={f.type} f={f.type} reason={f.reason} />)}
                      </div>
                      <div className="col-start-2 text-xs text-faint lg:col-start-auto lg:text-right">{timeAgo(t.createdAt)}</div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <p className="mt-2 text-xs text-faint">{rows.length} ticket{rows.length === 1 ? "" : "s"} · Category and sentiment are hidden on manual-review tickets, because their AI output is below the confidence threshold.</p>
      </div>
    </>
  );
}

export default function InboxPage() {
  return <Suspense><InboxView /></Suspense>;
}
