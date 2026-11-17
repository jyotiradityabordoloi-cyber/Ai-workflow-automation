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
import { CATEGORIES, CATEGORY_LABEL, customerLabel, FLAG_LABEL, PRIORITIES, STATUS_LABEL, timeAgo, subjectOf } from "@/lib/format";
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

/** One column template for the header and every row, so columns line up whatever a row contains (wide screens).
 *  Below xl the same markup collapses to a three-line card: title + age, summary, then the details in one wrapping line. */
const COLS = "xl:grid-cols-[34px_minmax(0,1fr)_160px_136px_100px_224px_64px]";
const HEAD = ["", "Ticket", "Customer", "Category", "Confidence", "Status", "Received"];

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

  // 40px tall on touch screens (tap targets), 32px from sm up where a pointer is likely
  const select = "h-10 w-full rounded-lg border border-line bg-surface px-2 text-[13px] text-ink sm:h-8 sm:w-auto";

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
      <div className="grid grid-cols-2 gap-2 px-4 py-3 sm:flex sm:flex-wrap sm:items-center md:px-6">
        <label className="relative col-span-2 min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint" />
          <input value={q} onChange={(e) => set("q", e.target.value)} placeholder="Search tickets, customers, IDs…"
            className="h-10 w-full rounded-lg border border-line bg-surface pr-3 pl-8 text-[13px] sm:h-8" aria-label="Search tickets" />
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
            <>
              <div className={clsx("hidden gap-x-3 border-b border-line px-4 py-2 text-[11px] font-medium tracking-wider text-faint uppercase xl:grid", COLS)} aria-hidden="true">
                {HEAD.map((h, i) => <span key={i} className={i === HEAD.length - 1 ? "text-right" : undefined}>{h}</span>)}
              </div>
              <ul className="divide-y divide-line">
                {rows.map((t) => {
                  const a = t.analysis;
                  const c = t.decision.category ?? a?.category;
                  const p = t.decision.priority ?? a?.priority;
                  const manual = a?.flags.some((f) => f.type === "manual_review");
                  const upset = a && !manual && (a.sentiment === "angry" || a.sentiment === "frustrated");
                  return (
                    <li key={t.id}>
                      <Link href={`/tickets/${t.id}`}
                        className={clsx("grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 gap-y-1.5 px-4 py-3 transition-colors hover:bg-hover focus-visible:bg-hover xl:items-center", COLS)}>
                        <div className="row-span-2 pt-px xl:row-span-1 xl:pt-0">{p ? <PriorityBadge p={p} /> : <Badge tone="info">New</Badge>}</div>
                        <div className="min-w-0">
                          <div className="flex items-baseline gap-3">
                            <p className="min-w-0 flex-1 truncate text-[13px] font-medium">{subjectOf(t)}</p>
                            <span className="shrink-0 text-xs text-faint tabular-nums xl:hidden">{timeAgo(t.createdAt)}</span>
                          </div>
                          <p className="truncate text-xs text-muted">{a && !manual ? a.summary : t.body}</p>
                        </div>
                        {/* one wrapping line on small screens; separate aligned cells on xl (display: contents) */}
                        <div className="col-start-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 xl:contents">
                          <span className="min-w-0 truncate text-xs text-muted">
                            {customerLabel(t.customer)}<span className="hidden text-faint xl:inline"> · {t.customer.plan}</span>
                          </span>
                          <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
                            {c && !manual ? CATEGORY_LABEL[c] : <span className="text-faint" title="Hidden until an agent classifies this ticket">–</span>}
                            {upset && a && <SentimentBadge s={a.sentiment} />}
                          </span>
                          <span className="min-w-0">{a ? <ConfidenceBar value={a.confidence} compact /> : <span className="text-xs text-faint">Not analysed</span>}</span>
                          <span className="flex min-w-0 flex-wrap items-center gap-1">
                            <span className="mr-1 inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-muted"><span className={clsx("size-1.5 rounded-full", STATUS_DOT[t.status])} />{STATUS_LABEL[t.status]}</span>
                            {a?.flags.map((f) => <FlagBadge key={f.type} f={f.type} reason={f.reason} />)}
                          </span>
                          <span className="hidden text-right text-xs text-faint tabular-nums xl:block">{timeAgo(t.createdAt)}</span>
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </>
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
