"use client";

import type { ReactNode } from "react";

export function AsyncPanel({
  title,
  loading,
  error,
  stale,
  updatedAt,
  onRetry,
  children,
  fallback = "Loading panel"
}: {
  title: string;
  loading?: boolean;
  error?: string;
  stale?: boolean;
  updatedAt?: string | null;
  onRetry?: () => void;
  children: ReactNode;
  fallback?: string;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <span>{title}</span>
        <strong>{stale ? "stale" : updatedAt ? new Date(updatedAt).toLocaleTimeString() : loading ? "loading" : "ready"}</strong>
      </div>
      {loading && <div className="empty-state compact">{fallback}</div>}
      {error && (
        <div className="empty-state compact">
          {error}
          {onRetry && <button className="button compact" onClick={onRetry}>Retry</button>}
        </div>
      )}
      {!loading && !error && children}
    </section>
  );
}
