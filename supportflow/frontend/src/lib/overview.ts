import type { AuditEvent, Ticket } from "./types";

// Every figure on the Overview is computed here from the workspace's real tickets, analyses and audit trail.
// "vs previous 24h" compares the last 24 hours with the 24 before them; nothing is estimated or invented.

const H = 3_600_000;
const ms = (iso: string) => new Date(iso).getTime();

export type Delta = { text: string; dir: -1 | 0 | 1 } | null;

/** Percentage change, or "+n" when there was nothing to compare against. */
export function delta(cur: number, prev: number): Delta {
  if (prev === 0) return cur === 0 ? { text: "no change", dir: 0 } : { text: `+${cur}`, dir: 1 };
  const p = Math.round(((cur - prev) / prev) * 100);
  return { text: `${p > 0 ? "+" : ""}${p}%`, dir: (Math.sign(p) as -1 | 0 | 1) };
}

/** When a ticket was resolved: its resolution, else the audit event that resolved it (mock mode). */
export function resolvedAt(t: Ticket, audit: AuditEvent[]): number | null {
  if (t.resolution?.at) return ms(t.resolution.at);
  if (t.status !== "resolved") return null;
  const e = audit.filter((a) => a.ticketId === t.id && /resolved/i.test(a.action)).sort((a, b) => b.at.localeCompare(a.at))[0];
  return e ? ms(e.at) : null;
}

const between = (t: number | null, from: number, to: number) => t !== null && t > from && t <= to;

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

export function kpis(tickets: Ticket[], audit: AuditEvent[], now: number) {
  const dayAgo = now - 24 * H;
  const twoDaysAgo = now - 48 * H;
  const res = new Map(tickets.map((t) => [t.id, resolvedAt(t, audit)]));
  const openAt = (when: number) => tickets.filter((t) => ms(t.createdAt) <= when && !((res.get(t.id) ?? Infinity) <= when)).length;

  const review = tickets.filter((t) => t.status === "new" || t.status === "needs_review");
  const oldestReviewH = review.length ? Math.floor((now - Math.min(...review.map((t) => ms(t.createdAt)))) / H) : null;

  // model time only for real model calls (the precheck fallback costs 0 ms and says nothing about the model)
  const lat = (from: number, to: number) => tickets
    .map((t) => t.analysis)
    .filter((a): a is NonNullable<Ticket["analysis"]> => !!a && a.latencyMs > 0 && between(ms(a.analyzedAt), from, to))
    .map((a) => a.latencyMs);
  const latNow = median(lat(dayAgo, now));
  const latPrev = median(lat(twoDaysAgo, dayAgo));
  const latAll = median(tickets.map((t) => t.analysis?.latencyMs ?? 0).filter((v) => v > 0));

  const resolvedCur = tickets.filter((t) => between(res.get(t.id) ?? null, dayAgo, now)).length;
  const resolvedPrev = tickets.filter((t) => between(res.get(t.id) ?? null, twoDaysAgo, dayAgo)).length;

  return {
    open: { value: openAt(now), delta: delta(openAt(now), openAt(dayAgo)) },
    review: { value: review.length, oldestReviewH },
    resolved: { value: resolvedCur, delta: delta(resolvedCur, resolvedPrev) },
    aiTime: { value: latNow ?? latAll, delta: latNow !== null && latPrev !== null ? delta(latNow, latPrev) : null },
  };
}

export type Range = "48h" | "7d";

/** Tickets received and resolved per bucket: 4-hour buckets over 48 hours, or days over a week. */
export function volume(tickets: Ticket[], audit: AuditEvent[], now: number, range: Range) {
  const step = range === "48h" ? 4 * H : 24 * H;
  const count = range === "48h" ? 12 : 7;
  const end = new Date(now);
  if (range === "48h") {
    end.setMinutes(0, 0, 0); // the 4-hour boundary after now, so the current bucket is the last point
    end.setHours(end.getHours() - (end.getHours() % 4) + 4);
  } else {
    end.setHours(24, 0, 0, 0); // midnight tonight: today is the last day
  }
  const starts = Array.from({ length: count }, (_, i) => end.getTime() - (count - i) * step);
  const bucket = (t: number | null) => (t === null ? -1 : starts.findIndex((s) => t >= s && t < s + step));

  const incoming = new Array(count).fill(0);
  const resolved = new Array(count).fill(0);
  for (const t of tickets) {
    const i = bucket(ms(t.createdAt));
    if (i >= 0) incoming[i]++;
    const j = bucket(resolvedAt(t, audit));
    if (j >= 0) resolved[j]++;
  }
  const day = new Intl.DateTimeFormat(undefined, { weekday: "short" });
  const hour = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  const labels = starts.map((s, i) => {
    const d = new Date(s);
    if (range === "7d") return day.format(d);
    const newDay = i === 0 || new Date(starts[i - 1]).getDate() !== d.getDate();
    return newDay ? `${day.format(d)} ${hour.format(d)}` : hour.format(d);
  });
  return { labels, incoming, resolved };
}

/** How often agents kept the AI's classification, counting only real model guesses (not hand-classified fallbacks). */
export function agreement(tickets: Ticket[]) {
  const decided = tickets.filter((t) => t.decision.status !== "pending" && t.analysis);
  const manual = decided.filter((t) => t.analysis!.flags.some((f) => f.type === "manual_review"));
  const judged = decided.filter((t) => !manual.includes(t));
  const accepted = judged.filter((t) => t.decision.status === "accepted"
    || (t.decision.category === t.analysis!.category && t.decision.priority === t.analysis!.priority)).length;
  return { accepted, overridden: judged.length - accepted, manual: manual.length };
}
