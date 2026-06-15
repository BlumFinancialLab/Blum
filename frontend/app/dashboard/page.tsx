"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { assetPath } from "@/lib/routes";
import { AccuracyOverview, DashboardOverview, LiveNewsArticle, MacroOverview, MarketSentiment, PipelineStatus, SignalValidationReport, SystemStatus } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { ScoreCard } from "@/components/ScoreCard";
import { SignalTable } from "@/components/SignalTable";

const POLL_INTERVAL_MS = 30000;

export default function DashboardPage() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [liveNews, setLiveNews] = useState<LiveNewsArticle[]>([]);
  const [marketSentiment, setMarketSentiment] = useState<MarketSentiment | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState("");
  const [liveError, setLiveError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<any>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const load = async () => {
    try {
      setError("");
      const overview = await api.overview();
      setData(overview);
      const [newsResult, sentimentResult, statusResult, systemResult] = await Promise.allSettled([
        api.liveNews(48),
        api.marketSentiment(48),
        api.pipelineStatus(),
        api.systemStatus()
      ] as const);
      if (newsResult.status === "fulfilled") setLiveNews(newsResult.value);
      if (sentimentResult.status === "fulfilled") setMarketSentiment(sentimentResult.value);
      if (statusResult.status === "fulfilled") setPipelineStatus(statusResult.value);
      if (systemResult.status === "fulfilled") setSystemStatus(systemResult.value);
      setLiveError(
        [
          newsResult.status === "rejected" ? `news ${errorMessage(newsResult.reason)}` : "",
          sentimentResult.status === "rejected" ? `sentiment ${errorMessage(sentimentResult.reason)}` : "",
          statusResult.status === "rejected" ? `status ${errorMessage(statusResult.reason)}` : "",
          systemResult.status === "rejected" ? `system ${errorMessage(systemResult.reason)}` : ""
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

  const runPipeline = async () => {
    setBusy(true);
    try {
      setPipelineResult(await api.runPipeline());
      await load();
    } finally {
      setBusy(false);
    }
  };

  const runDataRepair = async () => {
    setBusy(true);
    try {
      setPipelineResult(await api.repairData(36));
      await load();
    } finally {
      setBusy(false);
    }
  };

  const runAccuracy = async () => {
    setBusy(true);
    try {
      setPipelineResult(await api.runAccuracy(80));
      await load();
    } finally {
      setBusy(false);
    }
  };

  const refreshMacro = async () => {
    setBusy(true);
    try {
      setPipelineResult(await api.updateMacro());
      await load();
    } finally {
      setBusy(false);
    }
  };

  const refreshFundamentals = async () => {
    setBusy(true);
    try {
      setPipelineResult(await api.updateFundamentals(24));
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!data) return <LoadingState />;

  const realtime = pipelineStatus ?? data.realtime;

  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Live Intelligence Dashboard</div>
          <h1>Market narrative, sentiment and signal engine.</h1>
        </div>
        <button className="button primary" onClick={runPipeline} disabled={busy}>{busy ? "Running pipeline..." : "Run full pipeline"}</button>
      </div>

      <section className="realtime-strip">
        <div>
          <span className={`status-dot ${realtime.running ? "running" : realtime.last_status === "error" ? "error" : "ok"}`} />
          <strong>{realtime.running ? "Live worker running" : realtime.started ? "Live worker online" : "Live worker pending"}</strong>
          <span>{realtime.last_job ? `Last job: ${realtime.last_job}` : "Startup pipeline queued"}</span>
        </div>
        <div>
          <strong>{realtime.last_status.toUpperCase()}</strong>
          <span>{realtime.last_completed_at ? `Completed ${formatTime(realtime.last_completed_at)}` : "No completed job yet"}</span>
        </div>
        <div>
          <strong>{lastRefresh ? formatTime(lastRefresh) : "Loading"}</strong>
          <span>Dashboard refresh cadence 30s</span>
        </div>
      </section>

      {realtime.last_error && <div className="empty-state" style={{ marginBottom: 12 }}>Realtime worker error: {realtime.last_error}</div>}
      {liveError && <div className="empty-state" style={{ marginBottom: 12 }}>Live endpoint warning: {liveError}</div>}
      {systemStatus && (
        <section className="deployment-banner">
          <div>
            <span>Deployment</span>
            <strong>v{systemStatus.app_version} | {systemStatus.feature_set}</strong>
          </div>
          <div>
            <span>Financial Brain</span>
            <strong>{systemStatus.runtime_flags.financial_brain_model_enabled ? "7B finance model enabled" : "fallback mode"}</strong>
          </div>
          <div>
            <span>Configured model</span>
            <strong>{systemStatus.active_models.financial_brain_configured}</strong>
          </div>
        </section>
      )}

      <section className="grid-4 market-metrics">
        <Metric label="Assets" value={data.market_pulse.asset_count} />
        <Metric label="Live News" value={data.market_pulse.article_count} />
        <Metric label="Historical Rows" value={data.market_pulse.price_row_count} />
        <Metric label="Market Sentiment" value={data.market_pulse.average_sentiment.toFixed(2)} />
        <Metric label="Signals" value={data.market_pulse.signal_count} />
      </section>

      <section className="live-grid" style={{ marginTop: 12 }}>
        <MarketSentimentPanel sentiment={marketSentiment} />
        <LiveNewsTape articles={liveNews} />
      </section>

      {data.data_coverage && (
        <section className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head">
            <span>Historical market memory</span>
            <strong>{Math.round(data.data_coverage.coverage_ratio * 100)}% covered</strong>
          </div>
          <div className="grid-4">
            <Metric label="Ready assets" value={`${data.data_coverage.ready_assets}/${data.data_coverage.asset_count}`} />
            <Metric label="Stale assets" value={data.data_coverage.stale_assets} />
            <Metric label="Missing" value={data.data_coverage.missing_assets} />
            <Metric label="Short history" value={data.data_coverage.short_history_assets} />
          </div>
          <p>{data.data_coverage.data_policy}</p>
          {!!data.data_coverage.repair_candidates.length && (
            <p>Repair queue: {data.data_coverage.repair_candidates.slice(0, 14).join(", ")}</p>
          )}
          <div className="control-row" style={{ marginTop: 12, marginBottom: 0 }}>
            <button className="button" onClick={runDataRepair} disabled={busy}>{busy ? "Repairing..." : "Repair data gaps"}</button>
          </div>
        </section>
      )}

      <section className="live-grid" style={{ marginTop: 12 }}>
        <AccuracyPanel accuracy={data.accuracy} busy={busy} onAudit={runAccuracy} />
        <MacroValidationPanel macro={data.macro} validation={data.validation} busy={busy} onMacro={refreshMacro} onFundamentals={refreshFundamentals} />
      </section>

      {data.todays_strongest_signals.length ? (
        <section className="grid-3" style={{ marginTop: 12 }}>
          {data.todays_strongest_signals.slice(0, 6).map((signal) => <ScoreCard signal={signal} key={signal.ticker} />)}
        </section>
      ) : (
        <section className="panel readiness-panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>Signal readiness</span><strong>No scored signals yet</strong></div>
          <p>
            The app is online, but the database does not yet contain enough real OHLCV, news, sentiment and indicator evidence to publish
            a Blum Intelligence Score. This screen shows live worker state and stored public evidence without generated placeholders.
          </p>
          <div className="mini-metrics">
            <div><span>OHLCV rows</span><strong>{data.readiness.price_row_count}</strong></div>
            <div><span>News articles</span><strong>{data.readiness.news_article_count}</strong></div>
            <div><span>Signals</span><strong>{data.readiness.signal_count}</strong></div>
            <div><span>Live status</span><strong>{realtime.last_status}</strong></div>
          </div>
          <div className="control-row" style={{ marginTop: 12, marginBottom: 0 }}>
            <button className="button primary" onClick={runPipeline} disabled={busy}>{busy ? "Running pipeline..." : "Hydrate real data"}</button>
            <button className="button" onClick={runDataRepair} disabled={busy}>{busy ? "Repairing..." : "Repair history"}</button>
            <Link className="button" href="/stock-radar">Open Radar</Link>
            <Link className="button" href="/market-brain">Open Market Brain</Link>
          </div>
        </section>
      )}

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Data and model readiness</span><strong>{pipelineResult?.status ?? "live database state"}</strong></div>
        <div className="grid-4">
          <Metric label="Stored OHLCV rows" value={data.readiness.price_row_count} />
          <Metric label="Stored news" value={data.readiness.news_article_count} />
          <Metric label="Signal snapshots" value={data.readiness.signal_count} />
          <Metric label="Price providers" value={data.readiness.price_providers.length} />
        </div>
        {pipelineResult?.message && <p>{pipelineResult.message}</p>}
        {!!data.readiness.price_providers.length && (
          <p>
            Price providers: {data.readiness.price_providers.map((item) => `${item.provider} ${item.rows} rows`).join(" | ")}
          </p>
        )}
        <SourceDiagnostics result={pipelineResult ?? realtime.last_result} />
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Today&apos;s strongest signals</span></div>
        <SignalTable signals={data.todays_strongest_signals} />
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function MarketSentimentPanel({ sentiment }: { sentiment: MarketSentiment | null }) {
  if (!sentiment) return <div className="panel"><div className="panel-head"><span>Market sentiment</span></div><div className="empty-state">Waiting for live sentiment aggregation.</div></div>;
  const total = Math.max(1, Object.values(sentiment.label_counts).reduce((sum, value) => sum + value, 0));
  const positive = Math.round(((sentiment.label_counts.positive ?? 0) / total) * 100);
  const neutral = Math.round(((sentiment.label_counts.neutral ?? 0) / total) * 100);
  const negative = Math.round(((sentiment.label_counts.negative ?? 0) / total) * 100);

  return (
    <div className="panel sentiment-panel">
      <div className="panel-head">
        <span>Market-wide sentiment</span>
        <strong>{sentiment.article_count} articles / {sentiment.window_hours}h</strong>
      </div>
      <div className="sentiment-score">
        <strong>{sentiment.average_sentiment.toFixed(2)}</strong>
        <span>FinBERT-led aggregate score</span>
      </div>
      <div className="sentiment-stack">
        <i className="positive" style={{ width: `${positive}%` }} />
        <i className="neutral" style={{ width: `${neutral}%` }} />
        <i className="negative" style={{ width: `${negative}%` }} />
      </div>
      <div className="label-grid">
        <LabelMetric label="Positive" value={`${positive}%`} />
        <LabelMetric label="Neutral" value={`${neutral}%`} />
        <LabelMetric label="Negative" value={`${negative}%`} />
      </div>
      <div className="theme-list">
        {sentiment.themes.slice(0, 7).map((theme) => (
          <div key={theme.theme}>
            <strong>{theme.theme}</strong>
            <span>{theme.headline_count} headlines | avg {theme.avg_sentiment.toFixed(2)}</span>
          </div>
        ))}
      </div>
      <p>Models observed: {Object.keys(sentiment.models).map(shortModelName).join(" | ") || "pending"}</p>
    </div>
  );
}

function LiveNewsTape({ articles }: { articles: LiveNewsArticle[] }) {
  return (
    <div className="panel live-news-panel">
      <div className="panel-head">
        <span>Real-time public news tape</span>
        <strong>{articles.length} latest</strong>
      </div>
      {!articles.length && (
        <div className="empty-state">The live tape is waiting for public RSS and web-search sources. No generated headlines are shown.</div>
      )}
      <div className="news-tape">
        {articles.slice(0, 18).map((article) => (
          <a className="tape-row" href={article.url} target="_blank" rel="noreferrer" key={article.id}>
            <div>
              <strong>{article.title}</strong>
              <span>{article.source} | {formatTime(article.published_at)} | quality {article.quality_score.toFixed(1)}</span>
            </div>
            <div className="tape-meta">
              {article.sentiment && <b className={article.sentiment.label}>{article.sentiment.label} {article.sentiment.score.toFixed(2)}</b>}
              {article.theme_tags.events?.slice(0, 1).map((event) => <em key={event}>{event.replaceAll("_", " ")}</em>)}
              {article.theme_tags.themes?.slice(0, 2).map((theme) => <em key={theme}>{theme}</em>)}
              {article.linked_assets.slice(0, 3).map((asset) => <em key={asset.ticker}>{asset.ticker}</em>)}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

function AccuracyPanel({ accuracy, busy, onAudit }: { accuracy?: AccuracyOverview; busy: boolean; onAudit: () => void }) {
  if (!accuracy) {
    return (
      <div className="panel">
        <div className="panel-head"><span>Blum Confidence Layer</span><strong>Loading</strong></div>
        <div className="empty-state">Waiting for accuracy and evidence governance output.</div>
      </div>
    );
  }
  const issueRows = Object.entries(accuracy.issue_counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
  return (
    <div className="panel accuracy-panel">
      <div className="panel-head">
        <span>Blum Confidence Layer</span>
        <strong>{accuracy.blum_confidence_score.toFixed(1)} / {accuracy.confidence_label}</strong>
      </div>
      <div className="confidence-meter">
        <i style={{ width: `${Math.max(2, Math.min(100, accuracy.blum_confidence_score))}%` }} />
      </div>
      <div className="label-grid">
        <LabelMetric label="Assets audited" value={String(accuracy.asset_count)} />
        <LabelMetric label="Contract checks" value={String(accuracy.accuracy_contract.length)} />
        <LabelMetric label="Ready assets" value={String(accuracy.coverage.ready_assets)} />
      </div>
      <div className="quality-lists">
        <div>
          <span>Highest evidence quality</span>
          {accuracy.top_quality_assets.slice(0, 4).map((item) => (
            <Link href={assetPath(item.ticker)} key={item.ticker}>
              <strong>{item.ticker}</strong>
              <em>{item.blum_confidence_score.toFixed(1)}</em>
            </Link>
          ))}
        </div>
        <div>
          <span>Needs evidence repair</span>
          {accuracy.lowest_quality_assets.slice(0, 4).map((item) => (
            <Link href={assetPath(item.ticker)} key={item.ticker}>
              <strong>{item.ticker}</strong>
              <em>{item.confidence_label}</em>
            </Link>
          ))}
        </div>
      </div>
      {!!issueRows.length && (
        <div className="issue-list">
          {issueRows.map(([code, count]) => <span key={code}>{code.replaceAll("_", " ")} <b>{count}</b></span>)}
        </div>
      )}
      <button className="button" onClick={onAudit} disabled={busy}>{busy ? "Auditing..." : "Run 15-point audit"}</button>
    </div>
  );
}

function MacroValidationPanel({
  macro,
  validation,
  busy,
  onMacro,
  onFundamentals
}: {
  macro?: MacroOverview;
  validation?: SignalValidationReport;
  busy: boolean;
  onMacro: () => void;
  onFundamentals: () => void;
}) {
  return (
    <div className="panel macro-panel">
      <div className="panel-head">
        <span>Macro, fundamentals and validation</span>
        <strong>{validation?.status ?? "pending"}</strong>
      </div>
      <div className="grid-4">
        <Metric label="Macro series" value={macro?.series_count ?? 0} />
        <Metric label="Validated signals" value={validation?.validated_signals ?? 0} />
        <Metric label="Validation score" value={validation?.validation_score?.toFixed(1) ?? "n/a"} />
        <Metric label="Confirmed" value={validation?.confirmed_or_strengthening ?? 0} />
      </div>
      <div className="macro-list">
        {(macro?.indicators ?? []).slice(0, 6).map((item) => (
          <div key={item.indicator}>
            <strong>{item.indicator}</strong>
            <span>{item.latest_value ?? "n/a"} | {item.latest_date ?? "no date"}</span>
          </div>
        ))}
      </div>
      <p>{validation?.methodology ?? "The validation layer scores stored signals against lifecycle evidence without claiming future performance."}</p>
      <div className="control-row" style={{ marginTop: 12, marginBottom: 0 }}>
        <button className="button" onClick={onMacro} disabled={busy}>{busy ? "Refreshing..." : "Refresh macro"}</button>
        <button className="button" onClick={onFundamentals} disabled={busy}>{busy ? "Refreshing..." : "Refresh fundamentals"}</button>
      </div>
    </div>
  );
}

function LabelMetric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
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
          {!!news.source_errors?.length && <p>Latest source warnings: {news.source_errors.slice(0, 4).map((item: any) => `${item.name} ${item.status}`).join(" | ")}</p>}
        </div>
      )}
      {market && (
        <div>
          <span>Market data</span>
          <strong>{market.updated_assets ?? 0} assets updated</strong>
          <p>{market.price_rows ?? 0} OHLCV rows | period {market.period ?? "n/a"} | {market.data_mode ?? "real data"}</p>
          {!!market.missing_assets?.length && <p>Missing public prices: {market.missing_assets.slice(0, 12).join(", ")}</p>}
        </div>
      )}
    </div>
  );
}

function formatTime(value: string | null) {
  if (!value) return "Pending";
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

function shortModelName(value: string) {
  return value.split("/").pop() ?? value;
}

function errorMessage(value: any) {
  return value instanceof Error ? value.message : String(value);
}
