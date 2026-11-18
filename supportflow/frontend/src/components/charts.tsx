"use client";

import { useEffect, useId, useRef, useState } from "react";

/** Size of an element, kept current with a ResizeObserver, so SVG charts draw at real pixels (crisp text). */
function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.round(e.contentRect.width), h: Math.round(e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

/** A round axis maximum split into `ticks` equal integer steps (1, 2, 5 x 10^n). */
function niceMax(max: number, ticks = 4) {
  const raw = Math.max(1, max) / ticks;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  return Math.max(ticks, Math.ceil(step) * ticks);
}

export type Series = { key: string; label: string; color: string; values: number[] };

/**
 * Two-series line chart. Seen dozens of times a day, so nothing animates: lines draw at rest and the tooltip
 * follows the pointer instantly. Hover, or focus and use ← →, to read a point. It fills its container's height
 * (give the container one, e.g. flex-1), never less than `minHeight`.
 */
export function LineChart({ labels, series, minHeight = 240, describe }: { labels: string[]; series: Series[]; minHeight?: number; describe: string }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const gradient = useId();
  const w = size.w || 600;
  const height = Math.max(minHeight, size.h);
  const pad = { l: 34, r: 14, t: 14, b: 30 };
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values)));
  const n = labels.length;
  const x = (i: number) => pad.l + (n === 1 ? (w - pad.l - pad.r) / 2 : (i * (w - pad.l - pad.r)) / (n - 1));
  const y = (v: number) => pad.t + (1 - v / max) * (height - pad.t - pad.b);
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((w - pad.l - pad.r) / 64))));
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = (vals: number[]) => `${path(vals)}L${x(n - 1).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z`;

  const pick = (clientX: number) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || n === 0) return;
    const rel = ((clientX - box.left - pad.l) / (w - pad.l - pad.r)) * (n - 1);
    setActive(Math.min(n - 1, Math.max(0, Math.round(rel))));
  };

  return (
    <div ref={ref} className="relative h-full select-none" style={{ minHeight }}
      onPointerMove={(e) => pick(e.clientX)} onPointerLeave={() => setActive(null)}>
      <svg width={w} height={height} role="img" aria-label={describe} tabIndex={0}
        className="absolute inset-0 block rounded-lg outline-offset-4"
        onFocus={() => setActive((a) => a ?? n - 1)} onBlur={() => setActive(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? n) - 1));
          if (e.key === "ArrowRight") setActive((a) => Math.min(n - 1, (a ?? -1) + 1));
        }}>
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={series[0]?.color} stopOpacity="0.16" />
            <stop offset="100%" stopColor={series[0]?.color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3, 4].map((i) => {
          const v = (max / 4) * i;
          return (
            <g key={i}>
              <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeDasharray={i ? "3 4" : undefined} />
              <text x={pad.l - 8} y={y(v)} dy="0.32em" textAnchor="end" fill="var(--faint)" fontSize="11" className="tabular-nums">{v}</text>
            </g>
          );
        })}
        {/* labels counted back from the newest point, so the latest is always labelled and none collide */}
        {labels.map((l, i) => (n - 1 - i) % every === 0 && (
          <text key={i} x={x(i)} y={height - 8} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} fill="var(--faint)" fontSize="11">{l}</text>
        ))}
        {series[0] && <path d={area(series[0].values)} fill={`url(#${gradient})`} />}
        {active !== null && <line x1={x(active)} x2={x(active)} y1={pad.t} y2={y(0)} stroke="var(--ink)" strokeOpacity="0.55" />}
        {series.map((s) => (
          <g key={s.key}>
            <path d={path(s.values)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {s.values.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r={i === active ? 4.5 : n <= 16 ? 3 : 0} fill="var(--surface)" stroke={s.color} strokeWidth="2" />
            ))}
          </g>
        ))}
      </svg>
      {active !== null && (
        <div className="pointer-events-none absolute top-2 z-10 min-w-36 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg"
          style={x(active) > w / 2 ? { right: w - x(active) + 12 } : { left: x(active) + 12 }}>
          <p className="mb-1 font-medium tracking-wide text-faint uppercase">{labels[active]}</p>
          {series.map((s) => (
            <p key={s.key} className="flex items-center gap-2">
              <span className="size-2 rounded-full" style={{ background: s.color }} />
              <span className="text-muted">{s.label}</span>
              <span className="ml-auto pl-3 font-mono font-medium tabular-nums">{s.values[active]}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/** Two-part ring: `a` of `a + b`, with the share of `a` in the middle. */
export function Donut({ a, b, colorA, colorB, label, size = 136 }: { a: number; b: number; colorA: string; colorB: string; label: string; size?: number }) {
  const stroke = 14;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const total = a + b;
  const gap = total && a && b ? 4 : 0; // a hairline of ground between the two parts
  const lenA = total ? (a / total) * c : 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--subtle)" strokeWidth={stroke} />
      {total > 0 && (
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colorA} strokeWidth={stroke}
            strokeDasharray={`${Math.max(0, lenA - gap)} ${c}`} />
          {b > 0 && (
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colorB} strokeWidth={stroke}
              strokeDasharray={`${Math.max(0, c - lenA - gap)} ${c}`} strokeDashoffset={-lenA} />
          )}
        </g>
      )}
      <text x="50%" y="50%" dy="0.35em" textAnchor="middle" fill="var(--ink)" fontSize="26" fontWeight="600" className="tabular-nums">
        {total ? `${Math.round((a / total) * 100)}%` : "–"}
      </text>
    </svg>
  );
}
