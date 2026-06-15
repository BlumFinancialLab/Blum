import type { CSSProperties } from "react";
import { Signal } from "@/lib/types";
import { formatVolume, MarketSnapshotStrip } from "./MarketSnapshotStrip";
import { StatusBadge } from "./StatusBadge";

export function ScoreCard({ signal }: { signal: Signal }) {
  const scoreStyle = { "--score": signal.blum_score } as CSSProperties;
  return (
    <article className="score-card">
      <div className="score-card-top">
        <div>
          <span>{signal.asset?.asset_type ?? "Asset"} | {signal.asset?.sector ?? "Sector pending"}</span>
          <h3>{signal.ticker}</h3>
          <p className="asset-subtitle">{signal.asset?.name ?? "Instrument metadata pending"}</p>
        </div>
        <div className="score-ring" style={scoreStyle}>
          <strong>{Math.round(signal.blum_score)}</strong>
        </div>
      </div>
      <StatusBadge label={signal.classification} />
      <MarketSnapshotStrip snapshot={signal.market_snapshot} compact />
      <p>{signal.explanation}</p>
      <div className="mini-metrics">
        <div><span>Risk</span><strong>{signal.risk_level}</strong></div>
        <div><span>Confidence</span><strong>{Number(signal.confidence_score ?? 0).toFixed(0)}</strong></div>
        <div><span>Lifecycle</span><strong>{signal.lifecycle_state ?? "active"}</strong></div>
        <div><span>Volume</span><strong>{formatVolume(signal.market_snapshot?.volume)}</strong></div>
      </div>
    </article>
  );
}
