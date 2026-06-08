import type { CSSProperties } from "react";
import { Signal } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

export function ScoreCard({ signal }: { signal: Signal }) {
  const scoreStyle = { "--score": signal.blum_score } as CSSProperties;
  return (
    <article className="score-card">
      <div className="score-card-top">
        <div>
          <span>{signal.asset?.sector ?? "Asset"}</span>
          <h3>{signal.ticker}</h3>
        </div>
        <div className="score-ring" style={scoreStyle}>
          <strong>{Math.round(signal.blum_score)}</strong>
        </div>
      </div>
      <StatusBadge label={signal.classification} />
      <p>{signal.explanation}</p>
      <div className="mini-metrics">
        <div><span>Risk</span><strong>{signal.risk_level}</strong></div>
        <div><span>Horizon</span><strong>{signal.time_horizon}</strong></div>
      </div>
    </article>
  );
}
