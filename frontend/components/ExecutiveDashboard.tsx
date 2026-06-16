"use client";

import { ExecutiveDashboardPayload } from "@/lib/types";
import { BacktestPanel } from "./BacktestPanel";
import { MarketNarrative } from "./MarketNarrative";
import { OpportunityRadar } from "./OpportunityRadar";
import { PortfolioScenario } from "./PortfolioScenario";
import { SentimentTrends } from "./SentimentTrends";
import { Watchlist } from "./Watchlist";

export function ExecutiveDashboard({
  data,
  onAddWatch
}: {
  data: ExecutiveDashboardPayload;
  onAddWatch?: (ticker: string) => void;
}) {
  return (
    <section className="executive-dashboard">
      <div className="executive-hero">
        <div>
          <div className="kicker">AI Market Intelligence Officer</div>
          <h1>What to monitor today, why it matters, and which risks limit conviction.</h1>
          <p>{data.narrative.operating_summary}</p>
        </div>
        <div className="executive-command">
          <div><span>Market mood</span><strong>{data.market_mood}</strong></div>
          <div><span>Dominant narrative</span><strong>{data.dominant_narrative.theme}</strong></div>
          <div><span>Risk level</span><strong>{data.risk_level}</strong></div>
          <div><span>Data mode</span><strong>{data.data_mode.replaceAll("_", " ")}</strong></div>
        </div>
      </div>

      <div className="executive-grid">
        <MarketNarrative narrative={data.narrative} />
        <PortfolioScenario scenario={data.portfolio_scenario} />
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head">
          <span>Top Opportunities Today</span>
          <strong>{data.top_opportunities_today.length}</strong>
        </div>
        <OpportunityRadar rows={data.top_opportunities_today} onAdd={onAddWatch} />
      </div>

      <div className="executive-grid" style={{ marginTop: 12 }}>
        <SentimentTrends sentiment={data.community_sentiment} />
        <Watchlist watchlist={{ status: "ready", items: [], alerts: data.watchlist_alerts, suggested_items: data.top_opportunities_today, disclaimer: data.disclaimer }} />
      </div>

      <div className="executive-grid" style={{ marginTop: 12 }}>
        <BacktestPanel backtests={data.last_backtests} />
        <div className="panel">
          <div className="panel-head"><span>Best AI Reports</span><strong>{data.best_ai_reports.length}</strong></div>
          <div className="backtest-list">
            {data.best_ai_reports.map((report) => (
              <div key={`${report.ticker}-${report.created_at}`}>
                <strong>{report.title}</strong>
                <span>{report.summary}</span>
              </div>
            ))}
            {!data.best_ai_reports.length && <div className="empty-state">No persisted reports yet. Open an asset detail or request a report to build history.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

