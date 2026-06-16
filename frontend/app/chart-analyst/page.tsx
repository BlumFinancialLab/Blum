"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Asset, PricePoint } from "@/lib/types";
import { ChartAnalystPanel } from "@/components/ChartAnalystPanel";
import { LoadingState } from "@/components/LoadingState";

export default function ChartAnalystPage() {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [ticker, setTicker] = useState("NVDA");
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.assets()
      .then((rows) => {
        setAssets(rows);
        if (!rows.some((asset) => asset.ticker === ticker) && rows[0]) setTicker(rows[0].ticker);
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  useEffect(() => {
    if (!ticker) return;
    api.asset(ticker)
      .then((payload) => setPrices(payload.prices ?? []))
      .catch(() => setPrices([]));
  }, [ticker]);

  const selected = useMemo(() => assets?.find((asset) => asset.ticker === ticker), [assets, ticker]);

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!assets) return <LoadingState label="Loading chart analyst" />;

  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Chart Analyst</div>
          <h1>Institutional technical chart intelligence.</h1>
          <p>Hybrid analysis from deterministic OHLCV indicators, optional Qwen3-VL chart vision, sentiment context and Blum memory.</p>
        </div>
        <select className="input" value={ticker} onChange={(event) => setTicker(event.target.value)}>
          {assets.map((asset) => <option key={asset.ticker} value={asset.ticker}>{asset.ticker} | {asset.name}</option>)}
        </select>
      </div>
      {selected && (
        <section className="instrument-card" style={{ marginBottom: 12 }}>
          <div>
            <span>Instrument</span>
            <strong>{selected.ticker} | {selected.sector}</strong>
            <p>{selected.name} | {selected.asset_type} | {selected.exchange} | {selected.country}</p>
          </div>
          <div className="market-strip compact">
            <div><span>Price</span><strong>{selected.market_snapshot?.price ?? "n/a"}</strong></div>
            <div><span>1D</span><strong>{selected.market_snapshot?.perf_1d ?? "n/a"}%</strong></div>
            <div><span>Provider</span><strong>{selected.market_snapshot?.provider ?? "pending"}</strong></div>
          </div>
        </section>
      )}
      <ChartAnalystPanel ticker={ticker} prices={prices} />
    </>
  );
}
