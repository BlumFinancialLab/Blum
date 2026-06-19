"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import {
  AccuracyOverview,
  BrainStatus,
  DashboardOverview,
  ExecutiveDashboardPayload,
  LiveNewsArticle,
  MacroOverview,
  MarketSentiment,
  PipelineStatus,
  SignalValidationReport,
  SystemStatus
} from "@/lib/types";
import { FinancialBrainStatus } from "@/components/FinancialBrainStatus";
import {
  AssetTable,
  BloombergPanel,
  ConfidenceMeter,
  MarketRegimeBadge,
  MetricCard,
  MiniSparkline,
  NarrativeCard,
  NewsTape,
  SentimentBar,
  TerminalHeader,
  commandIcon,
  toAssetRowsFromOpportunities,
  toAssetRowsFromSignals
} from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";

const POLL_INTERVAL_MS = 30000;

export default function DashboardPage() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [liveNews, setLiveNews] = useState<LiveNewsArticle[]>([]);
  const [marketSentiment, setMarketSentiment] = useState<MarketSentiment | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [brainStatus, setBrainStatus] = useState<BrainStatus | null>(null);
  const [executive, setExecutive] = useState<ExecutiveDashboardPayload | null>(null);
  const [error, setError] = useState("");
  const [liveError, setLiveError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const load = async () => {
    try {
      setError("");
      const overview = await api.overview();
      setData(overview);
      const [newsResult, sentimentResult, statusResult, systemResult, executiveResult, brainResult] = await Promise.allSettled([
        api.liveNews(60),
        api.marketSentiment(48),
        api.pipelineStatus(),
        api.systemStatus(),
        api.executiveDashboard(),
        api.brainStatus()
      ] as const);
      if (newsResult.status === "fulfilled") setLiveNews(newsResult.value);
      if (sentimentResult.status === "fulfilled") setMarketSentiment(sentimentResult.value);
      if (statusResult.status === "fulfilled") setPipelineStatus(statusResult.value);
      if (systemResult.status === "fulfilled") setSystemStatus(systemResult.value);
      if (executiveResult.status === "fulfilled") setExecutive(executiveResult.value);
      if (brainResult.status === "fulfilled") setBrainStatus(brainResult.value);
      setLiveError(
        [
          newsResult.status === "rejected" ? `news ${errorMessage(newsResult.reason)}` : "",
          sentimentResult.status === "rejected" ? `sentiment ${errorMessage(sentimentResult.reason)}` : "",
          statusResult.status === "rejected" ? `status ${errorMessage(statusResult.reason)}` : "",
          systemResult.status === "rejected" ? `system ${errorMessage(systemResult.reason)}` : "",
          executiveResult.status === "rejected" ? `executive ${errorMessage(executiveResult.reason)}` : "",
          brainResult.status === "rejected" ? `brain ${errorMessage(brainResult.reason)}` : ""
        ].filter(Boolean).join(" | ")
      );
      setLastRefresh(new Date().toISOString());
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
    const interval = window.setInterval(load, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  const assetRows = useMemo(() => {
    if (executive?.top_opportunities_today?.length) return toAssetRowsFromOpportunities(executive.top_opportunities_today);
    return toAssetRowsFromSignals(data?.todays_strongest_signals ?? []);
  }, [data?.todays_strongest_signals, executive?.top_opportunities_today]);

  if (error) return <div className="terminal-empty">API error: {error}</div>;
  if (!data) return <LoadingState label="Loading Blum Command Center" />;

  const realtime = pipelineStatus ?? data.realtime;
  const sentimentMix = getSentimentMix(marketSentiment);
  const marketRegime = executive?.market_mood ?? inferRegime(data.market_pulse.average_sentiment, data.market_pulse.signal_count);
  const riskLevel = executive?.risk_level ?? inferRisk(data.market_pulse.average_sentiment, data.market_pulse.signal_count);
  const confidenceScore = brainStatus?.historical_accuracy === null || brainStatus?.historical_accuracy === undefined
    ? data.accuracy?.blum_confidence_score
    : brainStatus.historical_accuracy * 100;
  const breadth = breadthFromSignals(data.todays_strongest_signals);
  const topThemes = marketSentiment?.themes?.length ? marketSentiment.themes : executive?.narrative?.emerging_subthemes ?? [];
  const classificationMix = Object.entries(data.market_pulse.classification_mix ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <TerminalHeader
        eyebrow="Blum Command Center"
        title="Market intelligence operating desk."
        subtitle="A professional evidence layer for monitoring market regime, live news, sentiment, momentum, risk and ranked assets without direct financial advice."
        statusItems={[
          { label: "Worker", value: realtime.running ? "running" : realtime.started ? "online" : "pending", tone: realtime.running ? "attention" : "positive" },
          { label: "Last run", value: formatTime(realtime.last_completed_at), tone: realtime.last_status === "error" ? "negative" : "neutral" },
          { label: "AI model", value: systemStatus?.runtime_flags.financial_brain_model_enabled ? "finance LLM" : "fallback", tone: systemStatus?.runtime_flags.financial_brain_model_enabled ? "positive" : "attention" },
          { label: "Refresh", value: lastRefresh ? formatTime(lastRefresh) : "loading", tone: "info" }
        ]}
      />

      {(realtime.last_error || liveError) && (
        <div className="terminal-empty" style={{ marginBottom: 12 }}>
          {realtime.last_error ? `Realtime worker error: ${realtime.last_error}` : `Live endpoint warning: ${liveError}`}
        </div>
      )}

      <section className="terminal-command-grid">
        <MetricCard label="Market Regime" value={<MarketRegimeBadge regime={marketRegime} />} subvalue={executive?.dominant_narrative?.theme ?? "Narrative pending"} icon={commandIcon("regime")} tone="attention" />
        <MetricCard label="Sentiment Score" value={data.market_pulse.average_sentiment.toFixed(2)} subvalue={`${data.market_pulse.article_count} indexed articles`} icon={commandIcon("sentiment")} tone={data.market_pulse.average_sentiment >= 0 ? "positive" : "negative"} />
        <MetricCard label="Risk Level" value={riskLevel} subvalue="Composite signal and news risk" icon={commandIcon("risk")} tone={riskLevel.toLowerCase().includes("high") ? "negative" : "attention"} />
        <MetricCard label="Momentum Breadth" value={`${breadth}%`} subvalue="Signals above 60 score" icon={commandIcon("momentum")} tone={breadth >= 55 ? "positive" : "info"} />
        <MetricCard label="News 48h" value={marketSentiment?.article_count ?? liveNews.length} subvalue={`${topThemes.length} active themes`} icon={commandIcon("news")} tone="info" />
        <MetricCard label="Signals" value={data.market_pulse.signal_count} subvalue={`${assetRows.length} ranked assets visible`} icon={commandIcon("signals")} tone={data.market_pulse.signal_count ? "positive" : "attention"} />
        <MetricCard label="AI Confidence" value={confidenceScore === undefined ? "Pending" : `${Number(confidenceScore).toFixed(0)}%`} subvalue={brainStatus?.learning_state ?? data.accuracy?.confidence_label ?? "Evidence layer"} icon={commandIcon("ai")} tone="attention" />
        <MetricCard label="Worker Status" value={realtime.last_status} subvalue={realtime.last_job ?? "Startup pipeline"} icon={commandIcon("worker")} tone={realtime.last_status === "error" ? "negative" : "neutral"} />
      </section>

      <section className="market-command-layout">
        <div className="market-pulse-grid">
          <BloombergPanel title="Market Pulse" value="Live evidence" subtitle="Sentiment, narrative volume and signal breadth">
            <div className="pulse-chart-grid">
              <div className="pulse-mini-chart">
                <h3>Sentiment distribution</h3>
                <SentimentBar positive={sentimentMix.positive} neutral={sentimentMix.neutral} negative={sentimentMix.negative} score={marketSentiment?.average_sentiment ?? data.market_pulse.average_sentiment} />
                <MiniSparkline values={topThemes.map((theme: any) => Number(theme.avg_sentiment ?? 0) * 50 + 50).slice(0, 12)} tone="info" />
              </div>
              <div className="pulse-mini-chart">
                <h3>News volume by theme</h3>
                <ThemeVolumeBars themes={topThemes.slice(0, 7)} />
              </div>
              <div className="pulse-mini-chart">
                <h3>Signal mix</h3>
                <ClassificationBars rows={classificationMix} />
              </div>
              <div className="pulse-mini-chart">
                <h3>Risk-on / risk-off</h3>
                <RiskOnOffGauge sentiment={data.market_pulse.average_sentiment} breadth={breadth} risk={riskLevel} />
              </div>
            </div>
          </BloombergPanel>

          <BloombergPanel title="Dominant Narratives" value={executive?.dominant_narrative?.theme ?? "Pending"} subtitle="Semantic themes from public news">
            <div className="professional-grid-2">
              <NarrativeCard
                title={executive?.dominant_narrative?.theme ?? "Market narrative pending"}
                sentiment={executive?.dominant_narrative?.avg_sentiment ?? marketSentiment?.average_sentiment}
                volume={executive?.dominant_narrative?.headline_count ?? marketSentiment?.article_count}
                explanation={executive?.narrative?.operating_summary}
                tickers={executive?.narrative?.linked_assets ?? []}
              />
              {(executive?.narrative?.emerging_subthemes ?? topThemes).slice(0, 3).map((theme: any) => (
                <NarrativeCard
                  key={theme.theme}
                  title={theme.theme}
                  sentiment={theme.avg_sentiment}
                  volume={theme.headline_count}
                  tickers={executive?.narrative?.linked_assets ?? []}
                />
              ))}
            </div>
          </BloombergPanel>
        </div>

        <BloombergPanel title="News Tape" value={`${liveNews.length} latest`} subtitle="Public RSS and web evidence, no generated headlines">
          <NewsTape articles={liveNews} limit={15} />
        </BloombergPanel>
      </section>

      <BloombergPanel
        title="Radar Asset"
        value={`${assetRows.length} ranked`}
        subtitle="Sortable opportunity table with price, sentiment, momentum, risk and AI confidence"
        className="radar-core-panel"
      >
        <AssetTable rows={assetRows} />
      </BloombergPanel>

      <section className="desk-layout" style={{ marginTop: 12 }}>
        <div>
          <FinancialBrainStatus status={brainStatus} />
          <section className="professional-grid-2" style={{ marginTop: 12 }}>
            <AccuracyPanel accuracy={data.accuracy} />
            <MacroValidationPanel macro={data.macro} validation={data.validation} />
          </section>
        </div>
        <BloombergPanel title="Evidence Coverage" value={`${Math.round((data.data_coverage?.coverage_ratio ?? 0) * 100)}%`} subtitle="Historical price memory and provider diagnostics">
          <div className="professional-grid-2">
            <MetricCard label="OHLCV Rows" value={data.readiness.price_row_count} />
            <MetricCard label="News Articles" value={data.readiness.news_article_count} />
            <MetricCard label="Signal Snapshots" value={data.readiness.signal_count} />
            <MetricCard label="Ready Assets" value={`${data.data_coverage?.ready_assets ?? 0}/${data.data_coverage?.asset_count ?? 0}`} />
          </div>
          <p>{data.data_coverage?.data_policy ?? "Evidence policy pending."}</p>
          <SourceDiagnostics result={realtime.last_result} />
        </BloombergPanel>
      </section>
    </>
  );
}

function ThemeVolumeBars({ themes }: { themes: any[] }) {
  const max = Math.max(1, ...themes.map((theme) => Number(theme.headline_count ?? 0)));
  if (!themes.length) return <div className="terminal-empty">Theme volume will appear after news ingestion.</div>;
  return (
    <div className="theme-volume-bars">
      {themes.map((theme) => (
        <div className="theme-volume-row" key={theme.theme}>
          <span>{theme.theme}</span>
          <i style={{ width: `${Math.max(4, (Number(theme.headline_count ?? 0) / max) * 100)}%` }} />
          <strong>{theme.headline_count ?? 0}</strong>
        </div>
      ))}
    </div>
  );
}

function ClassificationBars({ rows }: { rows: Array<[string, number]> }) {
  const max = Math.max(1, ...rows.map(([, value]) => value));
  if (!rows.length) return <div className="terminal-empty">No signal classifications stored yet.</div>;
  return (
    <div className="theme-volume-bars">
      {rows.slice(0, 7).map(([label, value]) => (
        <div className="theme-volume-row" key={label}>
          <span>{label}</span>
          <i style={{ width: `${Math.max(4, (value / max) * 100)}%` }} />
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function RiskOnOffGauge({ sentiment, breadth, risk }: { sentiment: number; breadth: number; risk: string }) {
  const score = Math.max(0, Math.min(100, (sentiment * 35 + 50) * 0.55 + breadth * 0.45));
  return (
    <div>
      <ConfidenceMeter value={score} label="Risk-on proxy" />
      <p style={{ marginTop: 12 }}>
        {risk}. The proxy blends market-wide sentiment and signal breadth; it is a monitoring indicator, not a trading instruction.
      </p>
    </div>
  );
}

function AccuracyPanel({ accuracy }: { accuracy?: AccuracyOverview }) {
  if (!accuracy) {
    return (
      <BloombergPanel title="Confidence Layer" value="Pending">
        <div className="terminal-empty">Waiting for evidence quality audit.</div>
      </BloombergPanel>
    );
  }
  return (
    <BloombergPanel title="Confidence Layer" value={`${accuracy.blum_confidence_score.toFixed(1)} / ${accuracy.confidence_label}`}>
      <ConfidenceMeter value={accuracy.blum_confidence_score} label="Evidence quality" />
      <div className="professional-grid-3" style={{ marginTop: 12 }}>
        <MetricCard label="Assets Audited" value={accuracy.asset_count} />
        <MetricCard label="Ready Assets" value={accuracy.coverage.ready_assets} />
        <MetricCard label="Checks" value={accuracy.accuracy_contract.length} />
      </div>
      <div className="issue-list">
        {Object.entries(accuracy.issue_counts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([code, count]) => (
          <span key={code}>{code.replaceAll("_", " ")} <b>{count}</b></span>
        ))}
      </div>
    </BloombergPanel>
  );
}

function MacroValidationPanel({
  macro,
  validation
}: {
  macro?: MacroOverview;
  validation?: SignalValidationReport;
}) {
  return (
    <BloombergPanel title="Macro and Validation" value={validation?.status ?? "Pending"}>
      <div className="professional-grid-2">
        <MetricCard label="Macro Series" value={macro?.series_count ?? 0} />
        <MetricCard label="Validated Signals" value={validation?.validated_signals ?? 0} />
        <MetricCard label="Validation Score" value={validation?.validation_score?.toFixed(1) ?? "n/a"} />
        <MetricCard label="Confirmed" value={validation?.confirmed_or_strengthening ?? 0} />
      </div>
      <p>{validation?.methodology ?? "Signal validation compares stored signals with later evidence without promising future performance."}</p>
    </BloombergPanel>
  );
}

function SourceDiagnostics({ result }: { result: any }) {
  const news = result?.news_update;
  const market = result?.market_update;
  if (!news && !market) return null;
  return (
    <div className="diagnostic-grid">
      {news && (
        <div>
          <span>News ingestion</span>
          <strong>{news.sources_ok ?? 0}/{news.sources_requested ?? 0} sources ok</strong>
          <p>{news.inserted_articles ?? 0} inserted | {news.duplicate_articles ?? 0} duplicates | {news.linked_assets ?? 0} asset links</p>
        </div>
      )}
      {market && (
        <div>
          <span>Market data</span>
          <strong>{market.updated_assets ?? 0} assets updated</strong>
          <p>{market.price_rows ?? 0} OHLCV rows | period {market.period ?? "n/a"} | {market.data_mode ?? "real data"}</p>
        </div>
      )}
    </div>
  );
}

function getSentimentMix(sentiment: MarketSentiment | null) {
  return {
    positive: sentiment?.label_counts.positive ?? 0,
    neutral: sentiment?.label_counts.neutral ?? 0,
    negative: sentiment?.label_counts.negative ?? 0
  };
}

function breadthFromSignals(signals: DashboardOverview["todays_strongest_signals"]) {
  if (!signals.length) return 0;
  const strong = signals.filter((signal) => signal.blum_score >= 60).length;
  return Math.round((strong / signals.length) * 100);
}

function inferRegime(sentiment: number, signalCount: number) {
  if (signalCount === 0) return "Evidence Building";
  if (sentiment > 0.18) return "Constructive Risk-On";
  if (sentiment < -0.18) return "Defensive Risk-Off";
  return "Selective Rotation";
}

function inferRisk(sentiment: number, signalCount: number) {
  if (signalCount === 0) return "Data Pending";
  if (sentiment < -0.25) return "High";
  if (sentiment > 0.2) return "Moderate";
  return "Balanced";
}

function formatTime(value: string | null) {
  if (!value) return "Pending";
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

function errorMessage(value: any) {
  return value instanceof Error ? value.message : String(value);
}
