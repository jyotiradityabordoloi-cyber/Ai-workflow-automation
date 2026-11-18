"use client";

import { useSyncExternalStore } from "react";

// Tiny toast store: every human decision in the workspace gets a visible confirmation.

export type Toast = { id: number; text: string; tone: "ok" | "bad"; leaving?: boolean };

const VISIBLE_MS = 3200;
const EXIT_MS = 150; // matches the exit transition in <Toaster>: leaving is faster than arriving

let toasts: Toast[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function expire(id: number) {
  // Never let a confirmation run out while nobody can see it: wait for the tab to come back.
  if (typeof document !== "undefined" && document.hidden) {
    setTimeout(() => expire(id), 1000);
    return;
  }
  toasts = toasts.map((t) => (t.id === id ? { ...t, leaving: true } : t));
  emit();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emit();
  }, EXIT_MS);
}

export function toast(text: string, tone: Toast["tone"] = "ok"): void {
  const t = { id: ++seq, text, tone };
  toasts = [...toasts.slice(-2), t];
  emit();
  setTimeout(() => expire(t.id), VISIBLE_MS);
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => toasts,
    () => toasts,
  );
}
