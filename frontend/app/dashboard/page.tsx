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
  const [commandSummary, setCommandSummary] = useState<any | null>(null);
  const [executive, setExecutive] = useState<ExecutiveDashboardPayload | null>(null);
  const [error, setError] = useState("");
  const [liveError, setLiveError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const load = async () => {
    try {
      setError("");
      const overview = await api.overview();
      setData(overview);

      const [newsResult, sentimentResult, statusResult, systemResult, executiveResult, brainResult, commandResult] =
        await Promise.allSettled([
          api.liveNews(60),
          api.marketSentiment(48),
          api.pipelineStatus(),
          api.systemStatus(),
          api.executiveDashboard(),
          api.brainStatus(),
          api.brainCommandSummary()
        ] as const);

      if (newsResult.status === "fulfilled") setLiveNews(newsResult.value);
      if (sentimentResult.status === "fulfilled") setMarketSentiment(sentimentResult.value);
      if (statusResult.status === "fulfilled") setPipelineStatus(statusResult.value);
      if (systemResult.status === "fulfilled") setSystemStatus(systemResult.value);
      if (executiveResult.status === "fulfilled") setExecutive(executiveResult.value);
      if (brainResult.status === "fulfilled") setBrainStatus(brainResult.value);
      if (commandResult.status === "fulfilled") setCommandSummary(commandResult.value);

      setLiveError(
        [
          newsResult.status === "rejected" ? `news ${errorMessage(newsResult.reason)}` : "",
          sentimentResult.status === "rejected" ? `sentiment ${errorMessage(sentimentResult.reason)}` : "",
          statusResult.status === "rejected" ? `status ${errorMessage(statusResult.reason)}` : "",
          systemResult.status === "rejected" ? `system ${errorMessage(systemResult.reason)}` : "",
          executiveResult.status === "rejected" ? `executive ${errorMessage(executiveResult.reason)}` : "",
          brainResult.status === "rejected" ? `brain ${errorMessage(brainResult.reason)}` : "",
          commandResult.status === "rejected" ? `command ${errorMessage(commandResult.reason)}` : ""
        ]
          .filter(Boolean)
          .join(" | ")
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
    if (executive?.top_opportunities_today?.length) {
      return toAssetRowsFromOpportunities(executive.top_opportunities_today);
    }
    return toAssetRowsFromSignals(data?.todays_strongest_signals ?? []);
  }, [data?.todays_strongest_signals, executive?.top_opportunities_today]);

  if (error) return <div className="terminal-empty">API error: {error}</div>;
  if (!data) return <LoadingState label="Loading Blum Command Center" />;

  const realtime = pipelineStatus ?? data.realtime;
  const sentimentMix = getSentimentMix(marketSentiment);

  const averageSentiment = safeNumber(data.market_pulse?.average_sentiment);
  const signalCount = safeNumber(data.market_pulse?.signal_count, 0);
  const articleCount = safeNumber(data.market_pulse?.article_count, 0);

  const marketRegime = executive?.market_mood ?? inferRegime(averageSentiment, signalCount);
  const riskLevel = executive?.risk_level ?? inferRisk(averageSentiment, signalCount);

  const confidenceScore =
    brainStatus?.historical_accuracy === null || brainStatus?.historical_accuracy === undefined
      ? data.accuracy?.blum_confidence_score
      : safeNumber(brainStatus.historical_accuracy) * 100;

  const breadth = breadthFromSignals(data.todays_strongest_signals ?? []);
  const topThemes = marketSentiment?.themes?.length
    ? marketSentiment.themes
    : executive?.narrative?.emerging_subthemes ?? [];

  const classificationMix = Object.entries(data.market_pulse?.classification_mix ?? {}).sort(
    (a, b) => safeNumber(b[1]) - safeNumber(a[1])
  );

  return (
    <>
      <TerminalHeader
        eyebrow="Blum Command Center"
        title="Market intelligence operating desk."
        subtitle="A professional evidence layer for monitoring market regime, live news, sentiment, momentum, risk and ranked assets without direct financial advice."
        statusItems={[
          {
            label: "Worker",
            value: realtime?.running ? "running" : realtime?.started ? "online" : "pending",
            tone: realtime?.running ? "attention" : "positive"
          },
          {
            label: "Last run",
            value: formatTime(realtime?.last_completed_at ?? null),
            tone: realtime?.last_status === "error" ? "negative" : "neutral"
          },
          {
            label: "AI model",
            value: systemStatus?.runtime_flags?.financial_brain_model_enabled ? "finance LLM" : "fallback",
            tone: systemStatus?.runtime_flags?.financial_brain_model_enabled ? "positive" : "attention"
          },
          {
            label: "Refresh",
            value: lastRefresh ? formatTime(lastRefresh) : "loading",
            tone: "info"
          }
        ]}
      />

      {(realtime?.last_error || liveError) && (
        <div className="terminal-empty" style={{ marginBottom: 12 }}>
          {realtime?.last_error ? `Realtime worker error: ${realtime.last_error}` : `Live endpoint warning: ${liveError}`}
        </div>
      )}

      <section className="terminal-command-grid">
        <MetricCard
          label="Market Regime"
          value={<MarketRegimeBadge regime={marketRegime} />}
          subvalue={executive?.dominant_narrative?.theme ?? "Narrative pending"}
          icon={commandIcon("regime")}
          tone="attention"
        />

        <MetricCard
          label="Sentiment Score"
          value={formatNumber(averageSentiment, 2)}
          subvalue={`${articleCount} indexed articles`}
          icon={commandIcon("sentiment")}
          tone={averageSentiment >= 0 ? "positive" : "negative"}
        />

        <MetricCard
          label="Risk Level"
          value={riskLevel}
          subvalue="Composite signal and news risk"
          icon={commandIcon("risk")}
          tone={riskLevel.toLowerCase().includes("high") ? "negative" : "attention"}
        />

        <MetricCard
          label="Momentum Breadth"
          value={`${breadth}%`}
          subvalue="Signals above 60 score"
          icon={commandIcon("momentum")}
          tone={breadth >= 55 ? "positive" : "info"}
        />

        <MetricCard
          label="News 48h"
          value={safeNumber(marketSentiment?.article_count, liveNews.length)}
          subvalue={`${topThemes.length} active themes`}
          icon={commandIcon("news")}
          tone="info"
        />

        <MetricCard
          label="Signals"
          value={signalCount}
          subvalue={`${assetRows.length} ranked assets visible`}
          icon={commandIcon("signals")}
          tone={signalCount ? "positive" : "attention"}
        />

        <MetricCard
          label="AI Confidence"
          value={confidenceScore === undefined ? "Pending" : `${formatNumber(confidenceScore, 0)}%`}
          subvalue={brainStatus?.learning_state ?? data.accuracy?.confidence_label ?? "Evidence layer"}
          icon={commandIcon("ai")}
          tone="attention"
        />

        <MetricCard
          label="Worker Status"
          value={realtime?.last_status ?? "pending"}
          subvalue={realtime?.last_job ?? "Startup pipeline"}
          icon={commandIcon("worker")}
          tone={realtime?.last_status === "error" ? "negative" : "neutral"}
        />
      </section>

      <BrainLevelPanel summary={commandSummary} accuracy={data.accuracy} brainStatus={brainStatus} />

      <section className="market-command-layout">
        <div className="market-pulse-grid">
          <BloombergPanel title="Market Pulse" value="Live evidence" subtitle="Sentiment, narrative volume and signal breadth">
            <div className="pulse-chart-grid">
              <div className="pulse-mini-chart">
                <h3>Sentiment distribution</h3>
                <SentimentBar
                  positive={sentimentMix.positive}
                  neutral={sentimentMix.neutral}
                  negative={sentimentMix.negative}
                  score={marketSentiment?.average_sentiment ?? averageSentiment}
                />
                <MiniSparkline
                  values={topThemes.map((theme: any) => safeNumber(theme?.avg_sentiment) * 50 + 50).slice(0, 12)}
                  tone="info"
                />
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
                <RiskOnOffGauge sentiment={averageSentiment} breadth={breadth} risk={riskLevel} />
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
                  key={theme?.theme ?? JSON.stringify(theme)}
                  title={theme?.theme ?? "Unnamed theme"}
                  sentiment={theme?.avg_sentiment}
                  volume={theme?.headline_count}
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

        <BloombergPanel
          title="Evidence Coverage"
          value={`${Math.round(safeNumber(data.data_coverage?.coverage_ratio) * 100)}%`}
          subtitle="Historical price memory and provider diagnostics"
        >
          <div className="professional-grid-2">
            <MetricCard label="OHLCV Rows" value={safeNumber(data.readiness?.price_row_count)} />
            <MetricCard label="News Articles" value={safeNumber(data.readiness?.news_article_count)} />
            <MetricCard label="Signal Snapshots" value={safeNumber(data.readiness?.signal_count)} />
            <MetricCard
              label="Ready Assets"
              value={`${safeNumber(data.data_coverage?.ready_assets)}/${safeNumber(data.data_coverage?.asset_count)}`}
            />
          </div>
          <p>{data.data_coverage?.data_policy ?? "Evidence policy pending."}</p>
          <SourceDiagnostics result={realtime?.last_result} />
        </BloombergPanel>
      </section>
    </>
  );
}

function BrainLevelPanel({ summary, accuracy, brainStatus }: { summary: any; accuracy?: AccuracyOverview; brainStatus: BrainStatus | null }) {
  const learning = summary?.learning_evolution ?? summary ?? {};
  const improvement = summary?.improvement_regression ?? {};
  const benchmarks = Object.entries(summary?.benchmark_truth?.major_benchmarks ?? summary?.benchmark_summary?.major_benchmarks ?? {}).slice(0, 4) as Array<[string, any]>;
  const whatNext = summary?.what_blum_should_learn_next ?? improvement;
  const topWeakness = improvement?.top_weakness ?? summary?.top_weakness;
  const latestLesson = improvement?.latest_lesson ?? summary?.latest_lesson_learned;
  const tradingPower = summary?.brain_capability_score ?? learning?.trading_power_score ?? accuracy?.blum_confidence_score;
  const powerLabel = summary?.brain_classification ?? learning?.trading_power_classification ?? accuracy?.confidence_label ?? "evidence building";
  const evidenceStatus = evidenceLabel(summary);
  const statusStrip = summary?.brain_status_strip ?? {};
  return (
    <BloombergPanel
      title="BLUM Brain Level"
      value={tradingPower == null ? "Evidence pending" : `${formatNumber(tradingPower, 1)}/100`}
      subtitle="Lightweight learning snapshot: decision quality, trading evidence, benchmark pressure and next improvement focus"
      className="brain-level-panel"
    >
      <div className="brain-level-layout">
        <div className="brain-level-score">
          <div className="brain-level-ring" style={{ "--score": `${Math.max(0, Math.min(100, safeNumber(tradingPower))) * 3.6}deg` } as any}>
            <strong>{tradingPower == null ? "n/a" : formatNumber(tradingPower, 0)}</strong>
            <span>{powerLabel}</span>
          </div>
          <div className="brain-level-facts">
            <MetricCard label="Learning status" value={statusStrip?.learning_status ?? learning?.latest_run_status ?? brainStatus?.learning_state ?? "pending"} subvalue={`latest ${formatDateTime(statusStrip?.latest_run_at ?? learning?.latest_run_at)}`} tone="info" />
            <MetricCard label="Win / Expectancy" value={`${formatPct(learning?.win_rate)} / ${formatR(learning?.expectancy_r)}`} subvalue="paper Trading Game evidence" tone="attention" />
            <MetricCard label="Capital progress" value={formatPct(learning?.target_progress)} subvalue={`copy ${statusStrip?.paper_copy_readiness ?? "pending"} | alpha ${statusStrip?.alpha_readiness ?? "pending"}`} tone="positive" />
            <MetricCard label="Evidence level" value={evidenceStatus} subvalue={statusStrip?.trading_game_readiness ?? summary?.live_vs_historical_status ?? "live evidence pending"} tone={evidenceStatus.includes("weak") ? "attention" : "info"} />
          </div>
        </div>

        <div className="brain-level-benchmarks">
          <div className="panel-head"><span>Benchmark pressure</span><strong>{summary?.benchmark_summary?.status ?? "snapshot"}</strong></div>
          {benchmarks.length ? benchmarks.map(([name, payload]) => (
            <BenchmarkBrainBar key={name} name={name} payload={payload} />
          )) : <div className="terminal-empty">Benchmark snapshots are not mature enough yet.</div>}
        </div>

        <div className="brain-level-truth">
          <div className="panel-head"><span>What is changing</span><strong>truth first</strong></div>
          <div className="brain-list dense">
            <div>
              <span className="regime-badge tone-attention">weakness</span>
              <strong>{topWeakness?.main_problem ?? "No major weakness snapshot yet"}</strong>
              <p>{topWeakness?.recommended_action ?? "BLUM is still collecting enough evidence to isolate the next weak point."}</p>
            </div>
            <div>
              <span className="regime-badge tone-info">latest lesson</span>
              <strong>{latestLesson?.observation ?? "No recent learning lesson stored yet"}</strong>
              <p>{latestLesson ? `${latestLesson.ticker} | ${latestLesson.setup_type} | samples ${latestLesson.sample_size}` : "The backend learning loop will populate this from completed cycles."}</p>
            </div>
            <div>
              <span className="regime-badge tone-positive">next focus</span>
              <strong>{whatNext?.next_learning_focus?.target ?? whatNext?.target ?? whatNext?.conclusion?.summary ?? "No active focus priority"}</strong>
              <p>{whatNext?.next_learning_focus?.reason ?? whatNext?.reason ?? "When evidence is sufficient, BLUM will show which factor/module should be studied next."}</p>
            </div>
          </div>
        </div>
      </div>
    </BloombergPanel>
  );
}

function BenchmarkBrainBar({ name, payload }: { name: string; payload: any }) {
  const excess = safeNumber(payload?.excess_return);
  const width = Math.max(4, Math.min(100, Math.abs(excess)));
  const result = String(payload?.result_label ?? "inconclusive").replaceAll("_", " ");
  return (
    <div className="brain-benchmark-row">
      <span>{name}</span>
      <i className={excess >= 0 ? "positive" : "negative"}><b style={{ width: `${width}%` }} /></i>
      <strong className={excess >= 0 ? "positive-text" : "negative-text"}>{formatNumber(excess, 1)}%</strong>
      <em>{result}</em>
    </div>
  );
}

function ThemeVolumeBars({ themes }: { themes: any[] }) {
  const max = Math.max(1, ...themes.map((theme) => safeNumber(theme?.headline_count)));
  if (!themes.length) return <div className="terminal-empty">Theme volume will appear after news ingestion.</div>;

  return (
    <div className="theme-volume-bars">
      {themes.map((theme) => (
        <div className="theme-volume-row" key={theme?.theme ?? JSON.stringify(theme)}>
          <span>{theme?.theme ?? "Unnamed theme"}</span>
          <i style={{ width: `${Math.max(4, (safeNumber(theme?.headline_count) / max) * 100)}%` }} />
          <strong>{safeNumber(theme?.headline_count)}</strong>
        </div>
      ))}
    </div>
  );
}

function ClassificationBars({ rows }: { rows: Array<[string, number]> }) {
  const max = Math.max(1, ...rows.map(([, value]) => safeNumber(value)));
  if (!rows.length) return <div className="terminal-empty">No signal classifications stored yet.</div>;

  return (
    <div className="theme-volume-bars">
      {rows.slice(0, 7).map(([label, value]) => (
        <div className="theme-volume-row" key={label}>
          <span>{label}</span>
          <i style={{ width: `${Math.max(4, (safeNumber(value) / max) * 100)}%` }} />
          <strong>{safeNumber(value)}</strong>
        </div>
      ))}
    </div>
  );
}

function RiskOnOffGauge({ sentiment, breadth, risk }: { sentiment: number; breadth: number; risk: string }) {
  const score = Math.max(0, Math.min(100, (safeNumber(sentiment) * 35 + 50) * 0.55 + safeNumber(breadth) * 0.45));

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
    <BloombergPanel
      title="Confidence Layer"
      value={`${formatNumber(accuracy.blum_confidence_score, 1)} / ${accuracy.confidence_label ?? "Pending"}`}
    >
      <ConfidenceMeter value={safeNumber(accuracy.blum_confidence_score)} label="Evidence quality" />
      <div className="professional-grid-3" style={{ marginTop: 12 }}>
        <MetricCard label="Assets Audited" value={safeNumber(accuracy.asset_count)} />
        <MetricCard label="Ready Assets" value={safeNumber(accuracy.coverage?.ready_assets)} />
        <MetricCard label="Checks" value={accuracy.accuracy_contract?.length ?? 0} />
      </div>

      <div className="issue-list">
        {Object.entries(accuracy.issue_counts ?? {})
          .sort((a, b) => safeNumber(b[1]) - safeNumber(a[1]))
          .slice(0, 5)
          .map(([code, count]) => (
            <span key={code}>
              {code.replaceAll("_", " ")} <b>{safeNumber(count)}</b>
            </span>
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
        <MetricCard label="Macro Series" value={safeNumber(macro?.series_count)} />
        <MetricCard label="Validated Signals" value={safeNumber(validation?.validated_signals)} />
        <MetricCard label="Validation Score" value={formatNumber(validation?.validation_score, 1, "n/a")} />
        <MetricCard label="Confirmed" value={safeNumber(validation?.confirmed_or_strengthening)} />
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
          <strong>
            {safeNumber(news.sources_ok)}/{safeNumber(news.sources_requested)} sources ok
          </strong>
          <p>
            {safeNumber(news.inserted_articles)} inserted | {safeNumber(news.duplicate_articles)} duplicates |{" "}
            {safeNumber(news.linked_assets)} asset links
          </p>
        </div>
      )}

      {market && (
        <div>
          <span>Market data</span>
          <strong>{safeNumber(market.updated_assets)} assets updated</strong>
          <p>
            {safeNumber(market.price_rows)} OHLCV rows | period {market.period ?? "n/a"} | {market.data_mode ?? "real data"}
          </p>
        </div>
      )}
    </div>
  );
}

function getSentimentMix(sentiment: MarketSentiment | null) {
  return {
    positive: safeNumber(sentiment?.label_counts?.positive),
    neutral: safeNumber(sentiment?.label_counts?.neutral),
    negative: safeNumber(sentiment?.label_counts?.negative)
  };
}

function breadthFromSignals(signals: DashboardOverview["todays_strongest_signals"]) {
  if (!signals?.length) return 0;
  const strong = signals.filter((signal) => safeNumber(signal?.blum_score) >= 60).length;
  return Math.round((strong / signals.length) * 100);
}

function inferRegime(sentiment: number, signalCount: number) {
  if (safeNumber(signalCount) === 0) return "Evidence Building";
  if (safeNumber(sentiment) > 0.18) return "Constructive Risk-On";
  if (safeNumber(sentiment) < -0.18) return "Defensive Risk-Off";
  return "Selective Rotation";
}

function inferRisk(sentiment: number, signalCount: number) {
  if (safeNumber(signalCount) === 0) return "Data Pending";
  if (safeNumber(sentiment) < -0.25) return "High";
  if (safeNumber(sentiment) > 0.2) return "Moderate";
  return "Balanced";
}

function formatTime(value: string | null) {
  if (!value) return "Pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Pending";
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "pending";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function formatPct(value: unknown) {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "n/a";
  return `${(n * 100).toFixed(1)}%`;
}

function formatR(value: unknown) {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "n/a";
  return `${n.toFixed(2)}R`;
}

function evidenceLabel(summary: any) {
  if (!summary) return "loading";
  const warnings = summary?.warnings ?? [];
  if (summary?.brain_status_strip?.alpha_readiness === "INSUFFICIENT_EVIDENCE") return "weak evidence";
  if (summary?.brain_capability_score == null && summary?.trading_power_score == null) return "initializing";
  if (summary?.live_vs_historical_status === "missing") return "weak evidence";
  if (warnings.length > 2) return "limited evidence";
  if (summary?.brain_capability_score == null && summary?.trading_power_score == null) return "initializing";
  return "tracked evidence";
}

function errorMessage(value: any) {
  return value instanceof Error ? value.message : String(value);
}

function safeNumber(value: unknown, fallback = 0) {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function formatNumber(value: unknown, digits = 2, fallback = "—") {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : fallback;
}
