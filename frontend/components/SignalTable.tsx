import Link from "next/link";
import { Signal } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

export function SignalTable({ signals }: { signals: Signal[] }) {
  if (!signals.length) return <div className="empty-state">No signals yet. Run market update, news update and signal run.</div>;
  return (
    <div className="table-shell">
      <table className="intel-table">
        <thead>
          <tr>
            <th>Asset</th>
            <th>Score</th>
            <th>Classification</th>
            <th>Risk</th>
            <th>Momentum</th>
            <th>Trend</th>
            <th>Sentiment</th>
            <th>Why it surfaced</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((signal) => (
            <tr key={`${signal.ticker}-${signal.created_at}`}>
              <td>
                <Link href={`/assets/${signal.ticker}`} className="asset-link">{signal.ticker}</Link>
                <span>{signal.asset?.sector ?? signal.time_horizon}</span>
              </td>
              <td><strong className="score-number">{signal.blum_score.toFixed(1)}</strong></td>
              <td><StatusBadge label={signal.classification} /></td>
              <td>{signal.risk_level}</td>
              <td>{metric(signal, "momentum_score")}</td>
              <td>{metric(signal, "trend_score")}</td>
              <td>{metric(signal, "sentiment_score")}</td>
              <td className="why">{signal.explanation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function metric(signal: Signal, key: string) {
  const value = signal.score_breakdown?.[key] ?? 0;
  return <span className="metric-pill">{Number(value).toFixed(0)}</span>;
}

