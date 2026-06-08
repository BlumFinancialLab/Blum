import Link from "next/link";
import { Signal } from "@/lib/types";
import { formatPercent, formatPrice, formatVolume } from "./MarketSnapshotStrip";
import { StatusBadge } from "./StatusBadge";

export function SignalTable({ signals }: { signals: Signal[] }) {
  if (!signals.length) return <div className="empty-state">No signal snapshots are available yet. Run the full intelligence pipeline and review pipeline readiness for price, news and provider diagnostics.</div>;
  return (
    <div className="table-shell">
      <table className="intel-table">
        <thead>
          <tr>
            <th>Asset</th>
            <th>Market</th>
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
                <span>{signal.asset?.name ?? "Name pending"}</span>
                <span>{signal.asset?.asset_type ?? "Asset"} | {signal.asset?.sector ?? "Sector pending"} | {signal.asset?.exchange ?? "Exchange n/a"}</span>
              </td>
              <td>
                <strong>{formatPrice(signal.market_snapshot?.price, signal.market_snapshot?.currency)}</strong>
                <span>{formatPercent(signal.market_snapshot?.perf_1d)} 1D | {formatPercent(signal.market_snapshot?.perf_5d)} 5D</span>
                <span>{signal.market_snapshot?.provider ?? "provider n/a"} | vol {formatVolume(signal.market_snapshot?.volume)}</span>
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
