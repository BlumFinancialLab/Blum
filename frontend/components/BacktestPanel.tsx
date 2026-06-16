"use client";

export function BacktestPanel({ backtests }: { backtests: Array<Record<string, any>> }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span>Last Backtests</span>
        <strong>{backtests.length}</strong>
      </div>
      <div className="backtest-list">
        {backtests.slice(0, 6).map((item) => (
          <div key={`${item.run_name}-${item.created_at}`}>
            <strong>{item.run_name}</strong>
            <span>20D hit {formatMetric(item.metrics?.hit_rate_20d)} | avg {formatMetric(item.metrics?.average_forward_return_20d)}</span>
          </div>
        ))}
        {!backtests.length && <div className="empty-state">No stored backtests yet. Asset reports can generate similar-case validation.</div>}
      </div>
    </div>
  );
}

function formatMetric(value: unknown) {
  if (value === undefined || value === null) return "n/a";
  return Number(value).toFixed(2);
}

