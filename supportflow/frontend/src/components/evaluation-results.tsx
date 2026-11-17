"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { EvaluationSummary } from "@/lib/types";
import { Card, CardHeader } from "./ui";

/** Measured classifier results from the latest backend evaluation run. Renders nothing until one exists. */
export function EvaluationResults({ fallback }: { fallback: React.ReactNode }) {
  const [ev, setEv] = useState<EvaluationSummary | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.latestEvaluation().then(setEv).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <Card className="p-4 text-[13px] text-bad">Couldn&apos;t load evaluation results: {error}</Card>;
  if (ev === undefined) return null;
  if (ev === null) return <>{fallback}</>;

  const rows: [string, EvaluationSummary["fields"]["category"]][] = [
    ["Category", ev.fields.category], ["Priority", ev.fields.priority], ["Sentiment", ev.fields.sentiment],
  ];
  const c = ev.calibration;
  return (
    <Card>
      <CardHeader title={`Measured: ${ev.split} set · ${ev.n} labelled tickets`}
        hint={`${ev.model} · ${ev.dataset} · run ${dateTime(ev.run_at)} · ${ev.llm_failures} LLM failures`} />
      {ev.split !== "test" && (
        <div className="flex gap-2 border-b border-line bg-warn-soft px-4 py-2.5 text-[13px] text-warn">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <p>Development split: the prompt&apos;s definitions were written while looking at these tickets, so these numbers are optimistic. A held-out test set is scored in step 5.</p>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="px-4 py-2 font-medium">Field</th>
              <th className="px-4 py-2 text-right font-medium">AI accuracy</th>
              <th className="px-4 py-2 text-right font-medium">Always most common</th>
              <th className="px-4 py-2 font-medium">Errors (label → AI)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map(([name, f]) => (
              <tr key={name}>
                <td className="px-4 py-2.5">{name}{f.macro_f1 != null && <span className="ml-1 text-xs text-muted">· macro-F1 {f.macro_f1}%</span>}</td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums">{f.accuracy_pct}%</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">{f.majority_baseline_pct}% <span className="text-xs">({f.majority_label})</span></td>
                <td className="px-4 py-2.5 text-muted">{Object.entries(f.errors).map(([k, v]) => `${k.replace("->", " → ")} ×${v}`).join(", ") || "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="grid gap-px border-t border-line bg-line text-[13px] sm:grid-cols-3">
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-muted">Manual-review routing</dt>
          <dd className="mt-0.5">{ev.manual_review.caught}/{ev.manual_review.expected} expected caught · {ev.manual_review.extra.length} unexpected</dd>
        </div>
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-muted">Calibration (threshold {c.threshold})</dt>
          <dd className="mt-0.5">≥ {c.threshold}: {c.above_n} tickets, {c.above_accuracy_pct ?? "—"}% correct · below: {c.below_n}</dd>
          <dd className="mt-0.5 text-xs text-muted">Model confidences seen: {Object.keys(c.confidence_values).join(", ")}</dd>
        </div>
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-muted">Model latency</dt>
          <dd className="mt-0.5">p50 {ev.latency_ms.p50 ?? "—"} ms · p95 {ev.latency_ms.p95 ?? "—"} ms</dd>
        </div>
      </dl>
    </Card>
  );
}
