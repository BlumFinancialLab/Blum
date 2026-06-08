"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PricePoint, RelatedNews, Signal } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { BreakdownBars } from "@/components/BreakdownBars";
import { formatPercent, formatPrice, formatVolume, MarketSnapshotStrip } from "@/components/MarketSnapshotStrip";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export function AssetDetailClient({ ticker }: { ticker: string }) {
  const [data, setData] = useState<{ asset: any; market_snapshot?: any; prices: PricePoint[]; latest_signal: Signal | null; related_news: RelatedNews[] } | null>(null);
  const [insight, setInsight] = useState<any>(null);
  const [insightError, setInsightError] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.asset(ticker).then(setData).catch((err) => setError((err as Error).message));
  }, [ticker]);

  const explain = async () => {
    setInsightError("");
    setInsightLoading(true);
    try {
      const nextInsight = await api.explain(ticker);
      setInsight(nextInsight);
      setData(await api.asset(ticker));
    } catch (err) {
      setInsightError(`AI explanation endpoint warning: ${(err as Error).message}`);
    } finally {
      setInsightLoading(false);
    }
  };

  useEffect(() => {
    explain();
  }, [ticker]);

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!data) return <LoadingState label={`Loading ${ticker}`} />;

  const signal = data.latest_signal;
  const prices = data.prices ?? [];
  const snapshot = data.market_snapshot ?? signal?.market_snapshot ?? data.asset?.market_snapshot;
  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Asset Detail</div>
          <h1>{data.asset.ticker} <span style={{ color: "var(--muted)" }}>{data.asset.name}</span></h1>
          <p>{data.asset.description}</p>
        </div>
        <button className="button primary" onClick={explain} disabled={insightLoading}>{insightLoading ? "Building evidence..." : "Refresh AI explanation"}</button>
      </div>

      <section className="instrument-card">
        <div>
          <span>Instrument</span>
          <strong>{data.asset.asset_type} | {data.asset.sector}</strong>
          <p>{data.asset.category} | {data.asset.industry} | {data.asset.exchange} | {data.asset.country}</p>
        </div>
        <MarketSnapshotStrip snapshot={snapshot} />
      </section>

      <section className="grid-4" style={{ marginTop: 12 }}>
        <div className="metric-card"><span>Last Price</span><strong>{formatPrice(snapshot?.price, snapshot?.currency)}</strong></div>
        <div className="metric-card"><span>1D / 5D</span><strong>{formatPercent(snapshot?.perf_1d)} / {formatPercent(snapshot?.perf_5d)}</strong></div>
        <div className="metric-card"><span>Volume</span><strong>{formatVolume(snapshot?.volume)}</strong></div>
        <div className="metric-card"><span>Data Source</span><strong>{snapshot?.provider ?? "n/a"}</strong></div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="metric-card"><span>Classification</span><strong>{signal ? <StatusBadge label={signal.classification} /> : "No signal"}</strong></div>
        <div className="metric-card"><span>Blum Score</span><strong>{signal?.blum_score?.toFixed(1) ?? "n/a"}</strong></div>
        <div className="metric-card"><span>Risk Level</span><strong>{signal?.risk_level ?? "n/a"}</strong></div>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="Historical Price"
          data={[{ x: prices.map((p) => p.date), y: prices.map((p) => p.close), type: "scatter", mode: "lines", name: ticker, line: { color: "#ffb000", width: 2 } }]}
        />
        <PlotPanel
          title="Volume"
          data={[{ x: prices.map((p) => p.date), y: prices.map((p) => p.volume ?? 0), type: "bar", name: "Volume", marker: { color: "#4dd8ff" } }]}
        />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Score Breakdown</span></div>
          <BreakdownBars breakdown={signal?.score_breakdown ?? {}} />
        </div>
        <div className="panel">
          <div className="panel-head">
            <span>AI Explanation</span>
            {insight?.evidence_status && <strong>{String(insight.evidence_status).replaceAll("_", " ")}</strong>}
          </div>
          {insightLoading && <div className="loading-state"><div />Building explanation from real market and news evidence.</div>}
          {insightError && <div className="empty-state">{insightError}</div>}
          <p>{insight?.reason ?? signal?.explanation ?? "The backend is collecting verified evidence for this asset."}</p>
          <ul>{(insight?.watch_points ?? signal?.watch_points?.items ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul>
          {insight?.data_diagnostics && <Diagnostics diagnostics={insight.data_diagnostics} />}
        </div>
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Related News</span></div>
        <div className="news-list">
          {data.related_news.map((item) => (
            <a className="news-item" href={item.url} target="_blank" rel="noreferrer" key={item.id}>
              <strong>{item.title}</strong>
              <span>{item.source} | quality {item.quality_score}</span>
            </a>
          ))}
        </div>
      </section>
    </>
  );
}

function Diagnostics({ diagnostics }: { diagnostics: any }) {
  const market = diagnostics.market_update ?? {};
  const news = diagnostics.news_update ?? {};
  return (
    <div className="diagnostic-grid">
      <div>
        <span>Market evidence</span>
        <strong>{diagnostics.price_rows ?? 0} stored rows</strong>
        <p>{market.updated_assets ?? 0} assets updated | {market.price_rows ?? 0} rows fetched</p>
        {!!market.missing_assets?.length && <p>Missing public prices: {market.missing_assets.slice(0, 6).join(", ")}</p>}
      </div>
      <div>
        <span>News evidence</span>
        <strong>{diagnostics.linked_news ?? 0} linked articles</strong>
        <p>{news.sources_ok ?? 0}/{news.sources_requested ?? 0} public sources ok | {news.linked_assets ?? 0} asset links</p>
      </div>
    </div>
  );
}
