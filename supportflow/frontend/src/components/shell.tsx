"use client";

import clsx from "clsx";
import { BarChart3, BookOpen, Check, Gauge, Inbox, RotateCcw, Siren, X } from "lucide-react";
import { useToasts } from "@/lib/toast";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, useWorkspace, useWorkspaceOrNull } from "@/lib/api";
import { initials } from "@/lib/format";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/inbox", label: "Inbox", icon: Inbox, count: "review" as const },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/escalations", label: "Escalations", icon: Siren, count: "escalations" as const },
  { href: "/evaluation", label: "AI evaluation", icon: BarChart3 },
];

/** SupportFlow's mark: the same three bars as the landing page's logo and favicon. */
function StackMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden="true">
      <rect x="2" y="2.5" width="20" height="5.5" rx="2.75" /><rect x="2" y="9.25" width="14" height="5.5" rx="2.75" /><rect x="2" y="16" width="8" height="5.5" rx="2.75" />
    </svg>
  );
}

function ModeBanner() {
  const health = useBackendHealth();
  if (api.mode !== "live") {
    return (
      <div className="rounded-lg bg-warn-soft px-2.5 py-2 text-[11px] leading-4 text-warn">
        <b>Mock mode.</b> Realistic mock data; no backend or LLM connected.
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-ok-soft px-2.5 py-2 text-[11px] leading-4 text-ok">
      <b>Live backend.</b> Classification by {health?.llmConfigured ? health.llmModel : "a fallback (no API key)"}.
      <span className="text-muted"> Drafting and escalation are still mock (steps 3–4).</span>
    </div>
  );
}

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
        <div className="grid size-7 place-items-center rounded-lg bg-accent text-accent-ink"><StackMark /></div>
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
        <ModeBanner />
        <label className="block text-[11px] text-muted">
          Signed in as
          <select value={ws.currentRole} onChange={(e) => api.setRole(e.target.value as "agent" | "manager")}
            className="mt-1 w-full rounded-lg border border-line bg-subtle px-2 py-1.5 text-[13px] text-ink">
            <option value="agent">Alex Rivera · Agent</option>
            <option value="manager">Jordan Lee · Manager</option>
          </select>
        </label>
        {api.mode !== "live" && (
          <button onClick={() => { if (confirm("Reset all demo data to the seed state?")) api.reset(); }}
            className="flex items-center gap-1.5 text-[11px] text-muted hover:text-ink">
            <RotateCcw className="size-3" /> Reset demo data
          </button>
        )}
      </div>
    </aside>
  );
}

type Health = Awaited<ReturnType<typeof api.health>>;

function useBackend() {
  const [state, setState] = useState<{ ready: boolean; error: string | null; health: Health | null }>({ ready: api.mode !== "live", error: null, health: null });
  const connect = useCallback(() => {
    setState((s) => ({ ...s, error: null }));
    Promise.all([api.health(), api.sync()])
      .then(([health]) => setState({ ready: true, error: null, health }))
      .catch((e: Error) => setState({ ready: false, error: e.message, health: null }));
  }, []);
  useEffect(() => { connect(); }, [connect]);
  return { ...state, retry: connect };
}

const BackendContext = createContext<Health | null>(null);
export const useBackendHealth = () => useContext(BackendContext);

export function AppShell({ children }: { children: ReactNode }) {
  const ws = useWorkspaceOrNull();
  const backend = useBackend();
  if (backend.error) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <div className="max-w-md rounded-xl border border-line bg-surface p-5 text-[13px]">
          <p className="font-medium">Can&apos;t reach the SupportFlow backend</p>
          <p className="mt-1 text-muted">{backend.error}. Start it with <code className="font-mono">uvicorn app.main:app --port 8000</code> in <code className="font-mono">supportflow/backend</code>, or run the frontend in mock mode.</p>
          <button onClick={backend.retry} className="mt-3 rounded-lg border border-line px-3 py-1.5 hover:bg-hover">Retry</button>
        </div>
      </div>
    );
  }
  if (!ws || !backend.ready) {
    return <LoadingShell label={api.mode === "live" ? "Connecting to the backend…" : "Loading workspace…"} />;
  }
  return (
    <BackendContext.Provider value={backend.health}>
      <div className="min-h-dvh md:flex">
        <Sidebar />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
      <Toaster />
    </BackendContext.Provider>
  );
}

/** Confirmations for agent actions: bottom-right, announced politely to screen readers. */
function Toaster() {
  const toasts = useToasts();
  return (
    <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-50 flex flex-col items-end gap-2">
      {toasts.map((t) => (
        <div key={t.id} role="status"
          className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] shadow-lg motion-safe:animate-[toast-in_180ms_ease-out]">
          {t.tone === "ok" ? <Check className="size-3.5 text-ok" /> : <X className="size-3.5 text-bad" />}
          {t.text}
        </div>
      ))}
    </div>
  );
}

/** First paint while the workspace (or the backend) loads: the app's own layout, not a bare line of text. */
function LoadingShell({ label }: { label: string }) {
  const bar = "rounded-md bg-subtle motion-safe:animate-pulse";
  return (
    <div className="min-h-dvh md:flex" aria-busy="true">
      <aside className="hidden w-[232px] shrink-0 border-r border-line bg-surface p-4 md:block">
        <div className="flex items-center gap-2"><div className="grid size-7 place-items-center rounded-lg bg-accent text-accent-ink"><StackMark /></div><div className={`${bar} h-3 w-24`} /></div>
        <div className="mt-6 space-y-2">{[0, 1, 2, 3, 4].map((i) => <div key={i} className={`${bar} h-6`} />)}</div>
      </aside>
      <main className="min-w-0 flex-1">
        <div className="border-b border-line bg-surface px-6 py-4"><div className={`${bar} h-5 w-40`} /><p className="mt-2 text-[13px] text-muted">{label}</p></div>
        <div className="grid gap-3 p-6 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <div key={i} className={`${bar} h-20`} />)}</div>
        <div className="space-y-2 px-6">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className={`${bar} h-12`} />)}</div>
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <header className="sf-chrome sticky top-0 z-20 flex flex-wrap items-end justify-between gap-3 px-4 py-4 md:px-6">
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
