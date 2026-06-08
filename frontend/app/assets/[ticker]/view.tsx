"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PricePoint, RelatedNews, Signal } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { BreakdownBars } from "@/components/BreakdownBars";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export function AssetDetailClient({ ticker }: { ticker: string }) {
  const [data, setData] = useState<{ asset: any; prices: PricePoint[]; latest_signal: Signal | null; related_news: RelatedNews[] } | null>(null);
  const [insight, setInsight] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.asset(ticker).then(setData).catch((err) => setError((err as Error).message));
  }, [ticker]);

  const explain = async () => setInsight(await api.explain(ticker));

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!data) return <LoadingState label={`Loading ${ticker}`} />;

  const signal = data.latest_signal;
  const prices = data.prices ?? [];
  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Asset Detail</div>
          <h1>{data.asset.ticker} <span style={{ color: "var(--muted)" }}>{data.asset.name}</span></h1>
          <p>{data.asset.description}</p>
        </div>
        <button className="button primary" onClick={explain}>Generate AI explanation</button>
      </div>

      <section className="grid-3">
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
          <div className="panel-head"><span>AI Explanation</span></div>
          <p>{insight?.reason ?? signal?.explanation ?? "No explanation available yet."}</p>
          <ul>{(insight?.watch_points ?? signal?.watch_points?.items ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul>
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

