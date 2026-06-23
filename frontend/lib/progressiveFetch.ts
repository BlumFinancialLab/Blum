"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useProgressiveFetch<T>(loader: () => Promise<T>, options: { timeoutMs?: number; immediate?: boolean } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(options.immediate));
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const abortRef = useRef(false);

  const run = useCallback(async () => {
    abortRef.current = false;
    setLoading(true);
    setError("");
    let timeout: ReturnType<typeof setTimeout> | null = null;
    try {
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error("Request timed out")), options.timeoutMs ?? 12000);
      });
      const value = await Promise.race([loader(), timeoutPromise]);
      if (!abortRef.current) {
        setData(value);
        setUpdatedAt(new Date().toISOString());
      }
    } catch (err) {
      if (!abortRef.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (timeout) clearTimeout(timeout);
      if (!abortRef.current) setLoading(false);
    }
  }, [loader, options.timeoutMs]);

  useEffect(() => {
    if (options.immediate) run();
    return () => {
      abortRef.current = true;
    };
  }, [options.immediate, run]);

  return { data, loading, error, updatedAt, retry: run };
}

export function useVisibilityFetch<T>(loader: () => Promise<T>, enabled: boolean, options: { timeoutMs?: number } = {}) {
  return useProgressiveFetch(loader, { ...options, immediate: enabled });
}
