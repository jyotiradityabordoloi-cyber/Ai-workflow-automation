"use client";

import clsx from "clsx";
import { BarChart3, BookOpen, Gauge, Inbox, RotateCcw, Siren, Workflow } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { api, useWorkspace, useWorkspaceOrNull } from "@/lib/api";
import { initials } from "@/lib/format";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/inbox", label: "Inbox", icon: Inbox, count: "review" as const },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/escalations", label: "Escalations", icon: Siren, count: "escalations" as const },
  { href: "/evaluation", label: "AI evaluation", icon: BarChart3 },
];

function Sidebar() {
  const ws = useWorkspace();
  const path = usePathname();
  const counts = {
    review: ws.tickets.filter((t) => t.status === "new" || t.status === "needs_review").length,
    escalations: ws.escalations.filter((e) => e.status === "pending_approval").length,
  };
  return (
    <aside className="flex shrink-0 flex-col border-line bg-surface md:sticky md:top-0 md:h-dvh md:w-[232px] md:border-r">
      <div className="flex items-center gap-2 px-4 py-3.5">
        <div className="grid size-7 place-items-center rounded-lg bg-accent text-white"><Workflow className="size-4" /></div>
        <div className="leading-tight">
          <p className="text-[13px] font-semibold">SupportFlow AI</p>
          <p className="text-[11px] text-muted">Agent workspace</p>
        </div>
      </div>
      <nav className="flex gap-0.5 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
        {NAV.map(({ href, label, icon: Icon, count }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href) || (href === "/inbox" && path.startsWith("/tickets"));
          const n = count ? counts[count] : 0;
          return (
            <Link key={href} href={href}
              className={clsx("flex items-center gap-2.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[13px] transition",
                active ? "bg-hover font-medium text-ink" : "text-muted hover:bg-hover hover:text-ink")}>
              <Icon className="size-4" />
              <span className="flex-1">{label}</span>
              {n > 0 && <span className="rounded-md bg-accent-soft px-1.5 text-[11px] font-medium text-accent tabular-nums">{n}</span>}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto hidden space-y-3 border-t border-line p-3 md:block">
        <div className="rounded-lg bg-warn-soft px-2.5 py-2 text-[11px] leading-4 text-warn">
          <b>Mock mode.</b> Frontend step 1: realistic mock data, no LLM or backend connected yet.
        </div>
        <label className="block text-[11px] text-muted">
          Signed in as
          <select value={ws.currentRole} onChange={(e) => api.setRole(e.target.value as "agent" | "manager")}
            className="mt-1 w-full rounded-lg border border-line bg-subtle px-2 py-1.5 text-[13px] text-ink">
            <option value="agent">Alex Rivera · Agent</option>
            <option value="manager">Jordan Lee · Manager</option>
          </select>
        </label>
        <button onClick={() => { if (confirm("Reset all demo data to the seed state?")) api.reset(); }}
          className="flex items-center gap-1.5 text-[11px] text-muted hover:text-ink">
          <RotateCcw className="size-3" /> Reset demo data
        </button>
      </div>
    </aside>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const ws = useWorkspaceOrNull();
  if (!ws) {
    return <div className="grid min-h-dvh place-items-center text-sm text-muted">Loading workspace…</div>;
  }
  return (
    <div className="min-h-dvh md:flex">
      <Sidebar />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line bg-surface/60 px-4 py-4 backdrop-blur md:px-6">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}

export function Avatar({ name }: { name: string }) {
  return <span className="grid size-6 shrink-0 place-items-center rounded-full bg-subtle text-[10px] font-semibold text-muted">{initials(name)}</span>;
}
