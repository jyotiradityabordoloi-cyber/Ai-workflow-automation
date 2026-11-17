"use client";

import { useSyncExternalStore } from "react";
import { seedWorkspace } from "../mock/seed";
import type { Workspace } from "../types";

// Client-side store for the mock phase, persisted to localStorage so actions survive reloads.
// From step 2 the same hooks read server state from the FastAPI backend instead.

const KEY = `supportflow.${process.env.NEXT_PUBLIC_API_MODE === "live" ? "live" : "mock"}.v1`;
let state: Workspace | null = null;
const listeners = new Set<() => void>();

function load(): Workspace {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Workspace;
  } catch {
    /* storage unavailable: fall back to fresh seed */
  }
  return seedWorkspace();
}

export function getState(): Workspace {
  if (!state) state = load();
  return state;
}

export function setState(update: (s: Workspace) => Workspace): void {
  state = update(getState());
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* ignore quota / private mode */
  }
  listeners.forEach((l) => l());
}

export function resetState(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  state = seedWorkspace();
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Null during server render and hydration; the workspace afterwards. */
export function useWorkspaceOrNull(): Workspace | null {
  return useSyncExternalStore(subscribe, getState, () => null);
}

/** Use inside <WorkspaceGate>, which guarantees the workspace is loaded. */
export function useWorkspace(): Workspace {
  return useSyncExternalStore(subscribe, getState, getState);
}
