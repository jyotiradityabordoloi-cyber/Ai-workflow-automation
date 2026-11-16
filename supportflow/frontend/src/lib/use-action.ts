"use client";

import { useCallback, useState } from "react";

/** Run an async API call with loading + error state, so every button reports what happened. */
export function useAction<A extends unknown[]>(fn: (...args: A) => Promise<unknown>) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (...args: A) => {
    setLoading(true);
    setError(null);
    try {
      await fn(...args);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      return false;
    } finally {
      setLoading(false);
    }
  }, [fn]);
  return { run, loading, error, clearError: () => setError(null) };
}
