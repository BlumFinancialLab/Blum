"use client";

import Link from "next/link";
import { OpportunityRow } from "@/lib/types";
import { assetPath } from "@/lib/routes";

export function OpportunityRadar({ rows, onAdd }: { rows: OpportunityRow[]; onAdd?: (ticker: string) => void }) {
  if (!rows.length) return <div className="empty-state">No opportunity rankings are available yet. Run the full intelligence pipeline to hydrate real evidence.</div>;
  return (
    <div className="opportunity-radar">
      {rows.slice(0, 12).map((row) => (
        <article className="opportunity-card" key={`${row.rank}-${row.ticker}`}>
          <div className="opportunity-rank">#{row.rank}</div>
          <div className="opportunity-main">
            <div className="opportunity-title">
              <Link href={assetPath(row.ticker)}>{row.ticker}</Link>
              <span>{row.name}</span>
            </div>
            <p>{row.why_today}</p>
            <div className="tag-row">
              <span>{row.status_label}</span>
              <span>{row.sector}</span>
              <span>{row.risk_level}</span>
            </div>
          </div>
          <div className="score-stack">
            <Score label="Opportunity" value={row.opportunity_score} />
            <Score label="Trend" value={row.trend_score} />
            <Score label="Momentum" value={row.momentum_score} />
            <Score label="Sentiment" value={row.sentiment_score} />
            <Score label="News" value={row.news_score} />
            <Score label="Risk" value={row.risk_score} />
          </div>
          <div className="opportunity-market">
            <strong>{formatPrice(row.last_price, row.currency)}</strong>
            <span>{formatPercent(row.change_percent)} 1D</span>
            <span>{row.volume_relative.toFixed(2)}x rel vol</span>
            {onAdd && <button className="button compact" onClick={() => onAdd(row.ticker)}>Watch</button>}
          </div>
        </article>
      ))}
    </div>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{Number(value ?? 0).toFixed(0)}</strong>
      <i style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
    </div>
  );
}

function formatPrice(value: number | null, currency?: string | null) {
  if (value === null || value === undefined) return "n/a";
  return `${currency ?? "USD"} ${Number(value).toFixed(2)}`;
}

function formatPercent(value: number | null) {
  if (value === null || value === undefined) return "n/a";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

