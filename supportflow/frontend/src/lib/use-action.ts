"use client";

import { useCallback, useState } from "react";
import { toast } from "./toast";

/** Run an async API call with loading + error state, so every button reports what happened.
 *  `success` (optional) is shown as a toast when the call succeeds. */
export function useAction<A extends unknown[]>(fn: (...args: A) => Promise<unknown>, success?: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (...args: A) => {
    setLoading(true);
    setError(null);
    try {
      await fn(...args);
      if (success) toast(success);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      return false;
    } finally {
      setLoading(false);
    }
  }, [fn, success]);
  return { run, loading, error, clearError: () => setError(null) };
}
