"use client";

import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { CATEGORY_LABEL, FLAG_LABEL, SENTIMENT_LABEL } from "@/lib/format";
import { CONFIDENCE_THRESHOLD } from "@/lib/rules";
import type { Category, FlagType, Priority, Sentiment } from "@/lib/types";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-xl border border-line bg-surface", className)}>{children}</div>;
}

export function CardHeader({ title, hint, right }: { title: ReactNode; hint?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div>
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </div>
      {right}
    </div>
  );
}

type Tone = "neutral" | "accent" | "ok" | "warn" | "bad" | "info";
const TONE: Record<Tone, string> = {
  neutral: "bg-subtle text-muted border-line",
  accent: "bg-accent-soft text-accent border-transparent",
  ok: "bg-ok-soft text-ok border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  bad: "bg-bad-soft text-bad border-transparent",
  info: "bg-info-soft text-info border-transparent",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4", TONE[tone], className)}>
      {children}
    </span>
  );
}

export function PriorityBadge({ p }: { p: Priority }) {
  return <Badge tone={p === "P1" ? "bad" : p === "P2" ? "warn" : "neutral"} className="font-mono">{p}</Badge>;
}

export function CategoryBadge({ c }: { c: Category }) {
  return <Badge tone="neutral">{CATEGORY_LABEL[c]}</Badge>;
}

const SENT_TONE: Record<Sentiment, Tone> = { positive: "ok", neutral: "neutral", frustrated: "warn", angry: "bad" };
export function SentimentBadge({ s }: { s: Sentiment }) {
  return <Badge tone={SENT_TONE[s]}>{SENTIMENT_LABEL[s]}</Badge>;
}

const FLAG_TONE: Record<FlagType, Tone> = { manual_review: "warn", senior_agent: "bad", manager_review: "bad" };
export function FlagBadge({ f, reason }: { f: FlagType; reason?: string }) {
  return <Badge tone={FLAG_TONE[f]} title={reason}>{FLAG_LABEL[f]}</Badge>;
}

export function ConfidenceBar({ value, compact }: { value: number; compact?: boolean }) {
  const low = value < CONFIDENCE_THRESHOLD;
  return (
    <div className={clsx("flex items-center gap-2", compact ? "w-24" : "w-full")} title={`Confidence ${value.toFixed(2)} (threshold ${CONFIDENCE_THRESHOLD})`}>
      <div className="relative h-1.5 flex-1 rounded-full bg-subtle">
        <div className={clsx("h-full rounded-full", low ? "bg-warn" : "bg-accent")} style={{ width: `${Math.round(value * 100)}%` }} />
        <div className="absolute -top-1 -bottom-1 w-px bg-ink/40" style={{ left: `${CONFIDENCE_THRESHOLD * 100}%` }} />
      </div>
      <span className={clsx("w-8 text-right font-mono text-[11px] tabular-nums", low ? "text-warn" : "text-muted")}>{value.toFixed(2)}</span>
    </div>
  );
}

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
const BTN: Record<BtnVariant, string> = {
  primary: "bg-accent text-white hover:brightness-110 border-transparent",
  secondary: "bg-surface text-ink border-line hover:bg-hover",
  ghost: "bg-transparent text-muted border-transparent hover:bg-hover hover:text-ink",
  danger: "bg-surface text-bad border-line hover:bg-bad-soft",
};

export function Button({ variant = "secondary", loading, className, children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex h-8 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border px-3 text-[13px] font-medium transition active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
        BTN[variant], className)}
    >
      {loading && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="mt-1 max-w-md text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "bad" | "warn" }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={clsx("mt-1 text-2xl font-semibold tracking-tight tabular-nums", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-faint">{hint}</p>}
    </Card>
  );
}

export function ErrorText({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return <p role="alert" className="mt-2 text-[13px] text-bad">{children}</p>;
}
