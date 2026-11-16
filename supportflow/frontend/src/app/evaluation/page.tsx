"use client";

import { FlaskConical } from "lucide-react";
import { PageHeader } from "@/components/shell";
import { Card, CardHeader, Stat } from "@/components/ui";
import { useWorkspace } from "@/lib/api";
import { CONFIDENCE_THRESHOLD, hasFlag } from "@/lib/rules";

const PLANNED = [
  ["Per-field accuracy", "Category, priority and sentiment on a labelled, held-out test set, each next to the always-guess-the-most-common-answer baseline."],
  ["Macro F1 + confusion matrix", "Which categories get confused with which, so errors can be traced to labels or prompts."],
  ["Calibration", "Accuracy above vs. below the 0.7 confidence threshold, to check the threshold actually separates good and bad outputs."],
  ["Safety-rule recall", "Share of tickets that should hit manual, senior or manager review and actually did."],
  ["Draft quality", "Approve / edit / reject rates and how much agents change drafts before approving."],
  ["Latency", "p50 / p95 per pipeline step (classify, retrieve, draft)."],
];

export default function EvaluationPage() {
  const ws = useWorkspace();
  const analysed = ws.tickets.filter((t) => t.analysis);
  const decided = ws.tickets.filter((t) => t.decision.status !== "pending" && t.analysis && !hasFlag(t.analysis.flags, "manual_review"));
  const overridden = decided.filter((t) => t.decision.status === "overridden");
  const drafts = ws.drafts.filter((d) => d.status === "approved" || d.status === "rejected");
  const edited = drafts.filter((d) => d.status === "approved" && d.body !== d.originalBody);
  const buckets = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].map((lo) => ({
    lo, n: analysed.filter((t) => t.analysis!.confidence >= lo && (lo === 0.9 ? t.analysis!.confidence <= 1 : t.analysis!.confidence < lo + 0.1)).length,
  }));
  const max = Math.max(1, ...buckets.map((b) => b.n));
  const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");

  return (
    <>
      <PageHeader title="AI evaluation" subtitle="Accuracy is only shown after it has been measured." />
      <div className="space-y-4 p-4 md:p-6">
        <Card className="flex items-start gap-3 p-4">
          <FlaskConical className="mt-0.5 size-5 text-accent" />
          <div className="text-[13px]">
            <p className="font-medium">No evaluation has been run yet.</p>
            <p className="mt-0.5 text-muted">
              The classifier isn&apos;t connected (frontend step 1, mock data). Accuracy will appear here once the evaluation suite has run
              against a labelled, held-out test set. Until then this page shows only how agents treat AI output in this workspace.
            </p>
          </div>
        </Card>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Tickets analysed" value={analysed.length} />
          <Stat label="Routed to manual review" value={pct(analysed.filter((t) => hasFlag(t.analysis!.flags, "manual_review")).length, analysed.length)} hint={`Confidence below ${CONFIDENCE_THRESHOLD} or unsupported input`} />
          <Stat label="Agent override rate" value={pct(overridden.length, decided.length)} hint={`${overridden.length} of ${decided.length} confirmed classifications`} />
          <Stat label="Drafts edited before approval" value={pct(edited.length, drafts.filter((d) => d.status === "approved").length)} hint={`${drafts.length} drafts decided`} />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title="Confidence distribution" hint="Mock-data values; the bar marks the manual-review threshold" />
            <div className="flex h-44 items-end gap-1.5 p-4">
              {buckets.map((b) => (
                <div key={b.lo} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-[11px] tabular-nums text-muted">{b.n || ""}</span>
                  <div className={`w-full rounded-t ${b.lo < CONFIDENCE_THRESHOLD ? "bg-warn/70" : "bg-accent/80"}`} style={{ height: `${(b.n / max) * 110}px`, minHeight: b.n ? 3 : 0 }} />
                  <span className="text-[10px] tabular-nums text-faint">{b.lo.toFixed(1)}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="What step 5 will measure" />
            <ul className="divide-y divide-line">
              {PLANNED.map(([k, v]) => (
                <li key={k} className="px-4 py-2.5 text-[13px]"><p className="font-medium">{k}</p><p className="text-muted">{v}</p></li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
