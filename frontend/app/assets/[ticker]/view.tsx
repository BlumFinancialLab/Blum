"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { AccuracyProfile, PricePoint, RelatedNews, Signal } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { BlumMemoryPanel } from "@/components/BlumMemoryPanel";
import { BreakdownBars } from "@/components/BreakdownBars";
import { ChartAnalystPanel } from "@/components/ChartAnalystPanel";
import { AssetDetailPanel, BloombergPanel, MetricCard, RiskIndicator, ScoreBadge, SignalCard, TerminalHeader } from "@/components/FinancialTerminal";
import { formatPercent, formatPrice, formatVolume } from "@/components/MarketSnapshotStrip";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export function AssetDetailClient({ ticker }: { ticker: string }) {
  const [data, setData] = useState<{ asset: any; market_snapshot?: any; prices: PricePoint[]; latest_signal: Signal | null; related_news: RelatedNews[] } | null>(null);
  const [accuracy, setAccuracy] = useState<AccuracyProfile | null>(null);
  const [fundamentals, setFundamentals] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [brainMemory, setBrainMemory] = useState<any>(null);
  const [insight, setInsight] = useState<any>(null);
  const [insightError, setInsightError] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    setData(null);
    setAccuracy(null);
    setFundamentals(null);
    setReport(null);
    setBrainMemory(null);
    setInsight(null);
    setInsightError("");
    Promise.allSettled([api.asset(ticker), api.assetAccuracy(ticker), api.fundamentals(ticker), api.intelligenceReport(ticker), api.brainAssetMemory(ticker)] as const)
      .then(([assetResult, accuracyResult, fundamentalsResult, reportResult, brainResult]) => {
        if (assetResult.status === "fulfilled") setData(assetResult.value);
        else setError((assetResult.reason as Error).message);
        if (accuracyResult.status === "fulfilled") setAccuracy(accuracyResult.value);
        if (fundamentalsResult.status === "fulfilled") setFundamentals(fundamentalsResult.value);
        if (reportResult.status === "fulfilled") setReport(reportResult.value);
        if (brainResult.status === "fulfilled") setBrainMemory(brainResult.value);
      });
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
  const narrative = insight?.reason ?? signal?.explanation ?? report?.why_in_radar;
  const thesis = insight?.thesis ?? report?.thesis ?? (signal?.narrative_summary as any)?.thesis;
  return (
    <>
      <TerminalHeader
        eyebrow="Asset Intelligence Report"
        title="Security research cockpit."
        subtitle="Price action, sentiment, technical evidence, news quality, Blum memory and AI explanation for a single stock or ETF."
        statusItems={[
          { label: "Ticker", value: data.asset.ticker, tone: "attention" },
          { label: "Exchange", value: data.asset.exchange ?? "n/a" },
          { label: "Provider", value: snapshot?.provider ?? "pending" },
          { label: "Updated", value: snapshot?.date ?? "no price date", tone: snapshot?.price ? "positive" : "attention" }
        ]}
        actions={<button className="button primary" onClick={explain} disabled={insightLoading}>{insightLoading ? "Building evidence..." : "Refresh AI explanation"}</button>}
      />

      <AssetDetailPanel
        ticker={data.asset.ticker}
        name={data.asset.name}
        description={data.asset.description}
        sector={data.asset.sector}
        exchange={data.asset.exchange}
        assetType={data.asset.asset_type}
        price={snapshot?.price}
        currency={snapshot?.currency}
        changePercent={snapshot?.perf_1d}
        blumScore={signal?.blum_score}
        confidence={signal?.confidence_score ?? accuracy?.blum_confidence_score}
        narrative={narrative}
      />

      <section className="terminal-command-grid" style={{ marginTop: 12 }}>
        <MetricCard label="Last Price" value={formatPrice(snapshot?.price, snapshot?.currency)} subvalue={snapshot?.date ?? "price date pending"} />
        <MetricCard label="1D / 5D" value={`${formatPercent(snapshot?.perf_1d)} / ${formatPercent(snapshot?.perf_5d)}`} subvalue={`${formatPercent(snapshot?.perf_1m)} 1M`} tone={(snapshot?.perf_1d ?? 0) >= 0 ? "positive" : "negative"} />
        <MetricCard label="Volume" value={formatVolume(snapshot?.volume)} subvalue="Latest stored market volume" />
        <MetricCard label="Blum Score" value={signal?.blum_score?.toFixed(1) ?? "n/a"} subvalue={signal?.classification ?? "No active signal"} tone="attention" />
        <MetricCard label="Sentiment" value={metric(signal, "sentiment_score")} subvalue="News-linked score" />
        <MetricCard label="Momentum" value={metric(signal, "momentum_score")} subvalue="Price factor" />
        <MetricCard label="Volatility" value={metric(signal, "volatility_score")} subvalue="Risk component" />
        <MetricCard label="AI Confidence" value={signal?.confidence_score?.toFixed(0) ?? accuracy?.blum_confidence_score?.toFixed(0) ?? "Pending"} subvalue={accuracy?.confidence_label ?? "Evidence layer"} />
      </section>

      {signal && <section style={{ marginTop: 12 }}><SignalCard signal={signal} /></section>}

      <ThesisResearchPanel thesis={thesis} fallbackReason={narrative} />

      <section className="grid-2" style={{ marginTop: 12 }}>
        <EvidenceConfidencePanel accuracy={accuracy} />
        <FundamentalContextPanel fundamentals={fundamentals} assetType={data.asset.asset_type} />
      </section>

      {report && <AssetIntelligenceReportPanel report={report} />}

      <BlumMemoryPanel memory={brainMemory} />

      <ChartAnalystPanel ticker={data.asset.ticker} prices={prices} />

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
        <BloombergPanel title="Score Breakdown" value={signal?.score_version ?? "Blum score"}>
          <BreakdownBars breakdown={signal?.score_breakdown ?? {}} />
        </BloombergPanel>
        <BloombergPanel title="Why This Asset Matters Now" value={insight?.evidence_status ? String(insight.evidence_status).replaceAll("_", " ") : "Evidence"}>
          {insightLoading && <div className="loading-state"><div />Building explanation from real market and news evidence.</div>}
          {insightError && <div className="empty-state">{insightError}</div>}
          <p>{insight?.reason ?? signal?.explanation ?? "The backend is collecting verified evidence for this asset."}</p>
          <ul>{(insight?.watch_points ?? signal?.watch_points?.items ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul>
          {insight?.data_diagnostics && <Diagnostics diagnostics={insight.data_diagnostics} />}
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Decision Box" value="Monitor, do not advise">
          <div className="professional-grid-2">
            <MetricCard label="Primary Trigger" value={primaryTrigger(signal)} subvalue="Condition that would increase attention" />
            <MetricCard label="Invalidation" value={invalidation(signal)} subvalue="Condition that weakens the setup" tone="negative" />
            <MetricCard label="Main Risk" value={signal?.risk_level ?? "Evidence pending"} subvalue={report?.risk_review?.[0] ?? "Risk review pending"} />
            <MetricCard label="Confidence" value={signal?.confidence_score?.toFixed(0) ?? accuracy?.blum_confidence_score?.toFixed(0) ?? "Pending"} subvalue="Adaptive confidence layer" />
          </div>
          <div className="issue-list">
            {(insight?.watch_points ?? signal?.watch_points?.items ?? report?.risk_review ?? []).slice(0, 5).map((item: string) => <span key={item}>{item}</span>)}
          </div>
        </BloombergPanel>
        <BloombergPanel title="Risk and Signal State" value={signal ? <RiskIndicator risk={signal.risk_level} score={metricNumber(signal, "volatility_score")} /> : "No signal"}>
          <div className="professional-grid-2">
            <MetricCard label="Classification" value={signal ? <StatusBadge label={signal.classification} /> : "No signal"} />
            <MetricCard label="Time Horizon" value={signal?.time_horizon ?? "n/a"} />
            <MetricCard label="Lifecycle" value={signal?.lifecycle_state ?? "n/a"} />
            <MetricCard label="Evidence" value={<ScoreBadge value={accuracy?.blum_confidence_score} label="Quality" />} />
          </div>
        </BloombergPanel>
      </section>

      <BloombergPanel title="Related News" value={`${data.related_news.length} articles`} subtitle="Sorted by stored relevance and source quality" className="asset-news-panel">
        <div className="news-list">
          {data.related_news.map((item) => (
            <a className="news-item" href={item.url} target="_blank" rel="noreferrer" key={item.id}>
              <strong>{item.title}</strong>
              <span>{item.source} | quality {item.quality_score}</span>
              <span>
                {[...(item.theme_tags.events ?? []), ...(item.theme_tags.themes ?? [])]
                  .slice(0, 4)
                  .map((label) => label.replaceAll("_", " "))
                  .join(" | ") || "event classification pending"}
              </span>
            </a>
          ))}
        </div>
      </BloombergPanel>
    </>
  );
}

function EvidenceConfidencePanel({ accuracy }: { accuracy: AccuracyProfile | null }) {
  if (!accuracy) {
    return (
      <div className="panel">
        <div className="panel-head"><span>Evidence Confidence</span><strong>Pending</strong></div>
        <div className="empty-state">The 15-point accuracy profile is being built for this asset.</div>
      </div>
    );
  }
  const componentRows = Object.entries(accuracy.components)
    .map(([key, value]: [string, any]) => ({ key, score: Number(value?.score ?? 0), issues: value?.issues?.length ?? 0 }))
    .sort((a, b) => a.score - b.score)
    .slice(0, 7);
  return (
    <div className="panel">
      <div className="panel-head">
        <span>Evidence Confidence</span>
        <strong>{accuracy.blum_confidence_score.toFixed(1)} / {accuracy.confidence_label}</strong>
      </div>
      <div className="confidence-meter"><i style={{ width: `${Math.max(2, Math.min(100, accuracy.blum_confidence_score))}%` }} /></div>
      <div className="macro-list">
        {componentRows.map((item) => (
          <div key={item.key}>
            <strong>{item.key.replaceAll("_", " ")}</strong>
            <span>{item.score.toFixed(1)} score | {item.issues} issues</span>
          </div>
        ))}
      </div>
      {!!accuracy.issues.length && (
        <div className="issue-list">
          {accuracy.issues.slice(0, 6).map((item) => <span key={`${item.code}-${item.message}`}>{item.code.replaceAll("_", " ")}</span>)}
        </div>
      )}
    </div>
  );
}

function FundamentalContextPanel({ fundamentals, assetType }: { fundamentals: any; assetType: string }) {
  const snapshot = fundamentals?.latest_snapshot;
  const metrics = snapshot?.metrics ?? {};
  return (
    <div className="panel">
      <div className="panel-head">
        <span>Fundamental Context</span>
        <strong>{assetType === "ETF" ? "ETF not required" : snapshot ? "SEC evidence" : "Pending"}</strong>
      </div>
      {assetType === "ETF" ? (
        <p>ETF confidence is driven by holdings proxy, sector rotation, trend confirmation and macro context. Issuer fundamentals are not required.</p>
      ) : snapshot ? (
        <>
          <div className="grid-4">
            <div className="metric-card"><span>Quality</span><strong>{Number(snapshot.quality_score ?? 0).toFixed(0)}</strong></div>
            <div className="metric-card"><span>Period</span><strong>{snapshot.period_end ?? "n/a"}</strong></div>
            <div className="metric-card"><span>Revenue</span><strong>{compactNumber(factValue(metrics.revenue))}</strong></div>
            <div className="metric-card"><span>Net Income</span><strong>{compactNumber(factValue(metrics.net_income))}</strong></div>
          </div>
          <p>Provider: {snapshot.provider}. This context is sourced from public filings and is used as evidence quality, not as a recommendation.</p>
        </>
      ) : (
        <div className="empty-state">No verified fundamental snapshot is stored yet for this asset.</div>
      )}
    </div>
  );
}

function ThesisResearchPanel({ thesis, fallbackReason }: { thesis: any; fallbackReason?: string }) {
  if (!thesis) {
    return (
      <BloombergPanel
        title="Executive Thesis"
        value="Building"
        subtitle="Every asset requires a structured thesis before it can become a research candidate."
        className="asset-thesis-panel"
      >
        <div className="empty-state">
          Blum is collecting enough signal, news, technical, sentiment and memory evidence to create an explicit thesis. No placeholder thesis is displayed.
        </div>
      </BloombergPanel>
    );
  }
  const conviction = thesis.conviction ?? {};
  const context = thesis.market_context ?? {};
  const narrative = thesis.narrative_analysis ?? {};
  const historical = thesis.historical_similarity ?? {};
  const causal = thesis.causal_reasoning ?? {};
  const components = Object.entries(conviction.components ?? {}).slice(0, 7);
  return (
    <section style={{ marginTop: 12 }}>
      <BloombergPanel
        title="Executive Thesis"
        value={`${display(thesis.conviction_score ?? conviction.score)} conviction`}
        subtitle="Thesis strength, not probability of profit. Evidence, inference and uncertainty are separated."
        className="asset-thesis-panel"
      >
        <p>{thesis.executive_thesis ?? fallbackReason ?? "The thesis is being assembled from stored evidence."}</p>
        <div className="professional-grid-4" style={{ marginTop: 12 }}>
          <MetricCard label="Market Regime" value={context.regime ?? "Sideways"} subvalue={context.signal_regime_adjustment ?? "Context adjustment pending"} />
          <MetricCard label="Narrative Stage" value={narrative.lifecycle ?? "n/a"} subvalue={`Intensity ${display(narrative.intensity)} | crowding ${display(narrative.crowding)}`} />
          <MetricCard label="Historical Cases" value={historical.similar_cases_found ?? 0} subvalue={historical.reliability ?? historical.status ?? "memory pending"} />
          <MetricCard label="Conviction Label" value={conviction.label ?? "n/a"} subvalue={conviction.meaning ?? "Thesis strength score"} tone={(thesis.conviction_score ?? 0) >= 70 ? "positive" : "attention"} />
        </div>
      </BloombergPanel>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="What Is Happening" value="Observed + inferred">
          <p>{thesis.what_is_happening}</p>
          <h3>Causal read</h3>
          <p>{thesis.why_it_may_be_happening}</p>
          <div className="macro-list">
            <div><strong>Price caused sentiment</strong><span>{causal.price_caused_sentiment ?? "not established"}</span></div>
            <div><strong>Sentiment caused price</strong><span>{causal.sentiment_caused_price ?? "not established"}</span></div>
            <div><strong>External event explains both</strong><span>{causal.external_event_explains_both ?? "not observed"}</span></div>
          </div>
        </BloombergPanel>
        <BloombergPanel title="Market Context" value={context.regime ?? "Regime"}>
          <p>{context.interpretation ?? "Market regime context is pending."}</p>
          <ThesisList items={thesis.facts_observed} empty="Observed facts are still being collected." />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Supporting Evidence" value={`${thesisItems(thesis.supporting_evidence).length} items`}>
          <ThesisList items={thesis.supporting_evidence} empty="No strong independent support is available yet." />
        </BloombergPanel>
        <BloombergPanel title="Contradicting Evidence" value={`${thesisItems(thesis.contradicting_evidence).length} items`}>
          <ThesisList items={thesis.contradicting_evidence} empty="No contradiction was found, but this does not prove the thesis." />
        </BloombergPanel>
      </section>

      <section className="professional-grid-3" style={{ marginTop: 12 }}>
        <BloombergPanel title="Narrative Analysis" value={narrative.lifecycle ?? "n/a"} dense>
          <div className="macro-list">
            <div><strong>Growth velocity</strong><span>{display(narrative.growth_velocity)}</span></div>
            <div><strong>Saturation</strong><span>{display(narrative.saturation)}</span></div>
            <div><strong>Most exposed</strong><span>{(narrative.most_exposed_assets ?? []).join(", ") || "n/a"}</span></div>
          </div>
          <p>{narrative.interpretation ?? "Narrative interpretation is pending."}</p>
        </BloombergPanel>
        <BloombergPanel title="Historical Similarity" value={historical.status ?? "memory"} dense>
          <div className="macro-list">
            <div><strong>20D average</strong><span>{display(historical.average_forward_return_20d)}%</span></div>
            <div><strong>Success rate</strong><span>{display(historical.success_rate)}</span></div>
            <div><strong>Drawdown</strong><span>{display(historical.average_drawdown)}%</span></div>
          </div>
          <p>{historical.explanation ?? "No similar historical setup is available yet."}</p>
        </BloombergPanel>
        <BloombergPanel title="Conviction Reducers" value={conviction.label ?? "n/a"} dense>
          <ThesisList items={thesis.conviction_reducers ?? conviction.reducers} empty="No major conviction reducer was detected." />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="What The Market May Be Missing" value="Blind spots">
          <ThesisList items={thesis.what_the_market_may_be_missing} empty="No clear market blind spot is visible." />
        </BloombergPanel>
        <BloombergPanel title="Risks and Invalidation" value="Governance">
          <h3>Risks</h3>
          <ThesisList items={thesis.risks} empty="Risk evidence is still forming." />
          <h3>Invalidation conditions</h3>
          <ThesisList items={thesis.invalidation_conditions} empty="Invalidation conditions are not available yet." />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Final Blum View" value="Research stance">
          <p>{thesis.final_blum_view ?? "Final view pending."}</p>
          <h3>Intellectual honesty</h3>
          <ThesisList items={thesis.intellectual_honesty} empty="No specific limitation was recorded." />
        </BloombergPanel>
        <BloombergPanel title="Conviction Components" value={display(thesis.conviction_score)}>
          <div className="macro-list">
            {components.map(([key, value]) => (
              <div key={key}>
                <strong>{key.replaceAll("_", " ")}</strong>
                <span>{display(value)}</span>
              </div>
            ))}
          </div>
        </BloombergPanel>
      </section>
    </section>
  );
}

function ThesisList({ items, empty }: { items: any; empty: string }) {
  const rows = thesisItems(items);
  if (!rows.length) return <div className="empty-state">{empty}</div>;
  return (
    <ul>
      {rows.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

function thesisItems(items: any): string[] {
  if (!items) return [];
  const rows = Array.isArray(items) ? items : [items];
  return rows
    .map((item) => {
      if (item === null || item === undefined) return "";
      if (typeof item === "string") return item;
      if (typeof item === "number" || typeof item === "boolean") return String(item);
      return item.explanation ?? item.reason ?? item.summary ?? JSON.stringify(item);
    })
    .filter(Boolean);
}

function AssetIntelligenceReportPanel({ report }: { report: any }) {
  const backtest = report.similar_signal_history ?? {};
  return (
    <section className="panel" style={{ marginTop: 12 }}>
      <div className="panel-head">
        <span>Asset Intelligence Report</span>
        <strong>{String(report.data_mode ?? "evidence").replaceAll("_", " ")}</strong>
      </div>
      <div className="grid-2">
        <div>
          <h3>Why it surfaced</h3>
          <p>{report.why_in_radar}</p>
          <h3>Bullish scenario</h3>
          <p>{report.bullish_scenario}</p>
          <h3>Bearish scenario</h3>
          <p>{report.bearish_scenario}</p>
        </div>
        <div className="macro-list">
          <div><strong>Similar cases</strong><span>{backtest.case_count ?? 0} / {backtest.data_mode ?? "n/a"}</span></div>
          <div><strong>5D avg</strong><span>{display(backtest.avg_forward_return_5d)}%</span></div>
          <div><strong>20D avg</strong><span>{display(backtest.avg_forward_return_20d)}%</span></div>
          <div><strong>Positive 20D</strong><span>{display(backtest.positive_outcome_probability_20d)}</span></div>
          <div><strong>Avg drawdown</strong><span>{display(backtest.average_drawdown)}%</span></div>
          <div><strong>Reliability</strong><span>{backtest.statistical_reliability ?? "n/a"}</span></div>
        </div>
      </div>
      <div className="issue-list">
        {(report.risk_review ?? []).slice(0, 5).map((item: string) => <span key={item}>{item}</span>)}
      </div>
      <p><strong>AI conclusion:</strong> {report.ai_conclusion}</p>
      <p>{report.disclaimer}</p>
    </section>
  );
}

function compactNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value));
}

function factValue(value: any): number | null {
  if (typeof value === "number") return value;
  if (value && typeof value.value === "number") return value.value;
  return null;
}

function display(value: any) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(2);
}

function metric(signal: Signal | null, key: string) {
  return signal?.score_breakdown?.[key] === undefined ? "n/a" : Number(signal.score_breakdown[key]).toFixed(0);
}

function metricNumber(signal: Signal | null, key: string) {
  return signal?.score_breakdown?.[key] === undefined ? null : Number(signal.score_breakdown[key]);
}

function primaryTrigger(signal: Signal | null) {
  if (!signal) return "Signal snapshot pending";
  if (signal.classification.toLowerCase().includes("breakout")) return "Confirmed breakout with volume expansion";
  if (signal.classification.toLowerCase().includes("divergence")) return "Sentiment and price alignment";
  return "Sustained score and evidence improvement";
}

function invalidation(signal: Signal | null) {
  if (!signal) return "Missing price, news or signal evidence";
  if (signal.risk_level.toLowerCase().includes("high")) return "Volatility expands while confidence falls";
  return "Momentum decay, negative news reversal or support failure";
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
