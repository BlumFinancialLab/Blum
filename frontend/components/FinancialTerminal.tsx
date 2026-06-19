"use client";

import type { CSSProperties, ReactNode } from "react";
import { useMemo, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Brain,
  Database,
  Gauge,
  LineChart,
  Newspaper,
  ShieldAlert,
  Zap
} from "lucide-react";
import { assetPath } from "@/lib/routes";
import { LiveNewsArticle, OpportunityRow, Signal } from "@/lib/types";

export type AssetTableRow = {
  ticker: string;
  name: string;
  sector: string;
  assetType?: string;
  price: number | null;
  currency?: string | null;
  changePercent: number | null;
  volumeRelative: number | null;
  sentimentScore: number;
  momentumScore: number;
  trendScore: number;
  newsCount?: number | null;
  newsScore: number;
  confidence: number;
  signalType: string;
  riskScore: number;
  riskLevel: string;
  action: string;
  why: string;
};

type MetricTone = "neutral" | "positive" | "negative" | "attention" | "info";

export function TerminalHeader({
  eyebrow,
  title,
  subtitle,
  statusItems,
  actions
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
  statusItems?: Array<{ label: string; value: string; tone?: MetricTone }>;
  actions?: ReactNode;
}) {
  return (
    <header className="terminal-header">
      <div>
        <div className="terminal-eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="terminal-header-right">
        {!!statusItems?.length && (
          <div className="terminal-status-grid">
            {statusItems.map((item) => (
              <div className={clsx("terminal-status", item.tone && `tone-${item.tone}`)} key={`${item.label}-${item.value}`}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
        )}
        {actions && <div className="terminal-actions">{actions}</div>}
      </div>
    </header>
  );
}

export function BloombergPanel({
  title,
  value,
  subtitle,
  children,
  dense = false,
  className,
  action
}: {
  title: string;
  value?: ReactNode;
  subtitle?: string;
  children: ReactNode;
  dense?: boolean;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={clsx("bloomberg-panel", dense && "dense", className)}>
      <div className="bloomberg-panel-head">
        <div>
          <span>{title}</span>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="bloomberg-panel-value">
          {value}
          {action}
        </div>
      </div>
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  subvalue,
  tone = "neutral",
  icon,
  tooltip
}: {
  label: string;
  value: ReactNode;
  subvalue?: ReactNode;
  tone?: MetricTone;
  icon?: ReactNode;
  tooltip?: string;
}) {
  return (
    <div className={clsx("terminal-metric", `tone-${tone}`)} title={tooltip}>
      <div className="terminal-metric-label">
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      {subvalue && <p>{subvalue}</p>}
    </div>
  );
}

export function MarketRegimeBadge({ regime }: { regime: string }) {
  const normalized = regime.toLowerCase();
  const tone: MetricTone = normalized.includes("risk") || normalized.includes("stress") ? "negative" : normalized.includes("constructive") || normalized.includes("bull") ? "positive" : "attention";
  return <span className={clsx("regime-badge", `tone-${tone}`)}><Activity size={14} />{regime}</span>;
}

export function SentimentBar({
  positive,
  neutral,
  negative,
  score
}: {
  positive: number;
  neutral: number;
  negative: number;
  score?: number;
}) {
  const total = Math.max(1, positive + neutral + negative);
  return (
    <div className="sentiment-bar-wrap">
      <div className="sentiment-bar-labels">
        <span>Negative {Math.round((negative / total) * 100)}%</span>
        <strong>{score === undefined ? "Sentiment mix" : `Score ${score.toFixed(2)}`}</strong>
        <span>Positive {Math.round((positive / total) * 100)}%</span>
      </div>
      <div className="terminal-sentiment-bar">
        <i className="negative" style={{ width: `${Math.max(2, (negative / total) * 100)}%` }} />
        <i className="neutral" style={{ width: `${Math.max(2, (neutral / total) * 100)}%` }} />
        <i className="positive" style={{ width: `${Math.max(2, (positive / total) * 100)}%` }} />
      </div>
    </div>
  );
}

export function ScoreBadge({ value, label }: { value: number | null | undefined; label?: string }) {
  const score = clampScore(value);
  const tone = score >= 75 ? "positive" : score >= 55 ? "attention" : score >= 35 ? "info" : "negative";
  return (
    <span className={clsx("score-badge", `tone-${tone}`)}>
      <strong>{value === null || value === undefined ? "n/a" : score.toFixed(0)}</strong>
      {label && <em>{label}</em>}
    </span>
  );
}

export function RiskIndicator({ risk, score }: { risk: string; score?: number | null }) {
  const normalized = risk.toLowerCase();
  const tone = normalized.includes("high") || normalized.includes("risky") ? "negative" : normalized.includes("low") ? "positive" : "attention";
  return (
    <span className={clsx("risk-indicator", `tone-${tone}`)}>
      <ShieldAlert size={13} />
      {risk || "Not rated"}
      {score !== undefined && score !== null && <b>{Number(score).toFixed(0)}</b>}
    </span>
  );
}

export function ConfidenceMeter({ value, label = "AI confidence" }: { value: number | null | undefined; label?: string }) {
  const score = clampScore(value);
  return (
    <div className="terminal-confidence" title={`${label}: ${score.toFixed(1)}/100`}>
      <div>
        <span>{label}</span>
        <strong>{value === null || value === undefined ? "Pending" : `${score.toFixed(0)}%`}</strong>
      </div>
      <i><b style={{ width: `${Math.max(2, score)}%` }} /></i>
    </div>
  );
}

export function MiniSparkline({ values, tone = "attention" }: { values: number[]; tone?: MetricTone }) {
  const points = useMemo(() => {
    if (values.length < 2) return "";
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values.map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 28 - ((value - min) / span) * 26 + 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  }, [values]);
  return (
    <svg className={clsx("mini-sparkline", `tone-${tone}`)} viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points || "0,24 100,8"} />
    </svg>
  );
}

export function AssetTable({ rows }: { rows: AssetTableRow[] }) {
  const [sortKey, setSortKey] = useState<keyof AssetTableRow>("confidence");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const left = sortableValue(a[sortKey]);
      const right = sortableValue(b[sortKey]);
      const result = left > right ? 1 : left < right ? -1 : 0;
      return direction === "asc" ? result : -result;
    });
  }, [direction, rows, sortKey]);

  const setSort = (key: keyof AssetTableRow) => {
    if (sortKey === key) setDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setDirection("desc");
    }
  };

  if (!rows.length) {
    return (
      <div className="terminal-empty">
        No ranked assets are available yet. The autonomous intelligence engine is hydrating real prices, news, sentiment and signal snapshots.
      </div>
    );
  }

  return (
    <div className="asset-table-shell">
      <table className="asset-terminal-table">
        <thead>
          <tr>
            <SortableHeader label="Ticker" active={sortKey === "ticker"} onClick={() => setSort("ticker")} />
            <SortableHeader label="Company / ETF" active={sortKey === "name"} onClick={() => setSort("name")} />
            <SortableHeader label="Price" active={sortKey === "price"} onClick={() => setSort("price")} />
            <SortableHeader label="Chg %" active={sortKey === "changePercent"} onClick={() => setSort("changePercent")} />
            <SortableHeader label="Rel Vol" active={sortKey === "volumeRelative"} onClick={() => setSort("volumeRelative")} />
            <SortableHeader label="Sentiment" active={sortKey === "sentimentScore"} onClick={() => setSort("sentimentScore")} />
            <SortableHeader label="Momentum" active={sortKey === "momentumScore"} onClick={() => setSort("momentumScore")} />
            <SortableHeader label="Trend" active={sortKey === "trendScore"} onClick={() => setSort("trendScore")} />
            <SortableHeader label="News" active={sortKey === "newsScore"} onClick={() => setSort("newsScore")} />
            <SortableHeader label="AI Conf." active={sortKey === "confidence"} onClick={() => setSort("confidence")} />
            <SortableHeader label="Signal" active={sortKey === "signalType"} onClick={() => setSort("signalType")} />
            <SortableHeader label="Risk" active={sortKey === "riskScore"} onClick={() => setSort("riskScore")} />
            <SortableHeader label="Action" active={sortKey === "action"} onClick={() => setSort("action")} />
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr key={`${row.ticker}-${row.signalType}-${row.action}`}>
              <td>
                <Link className="terminal-ticker" href={assetPath(row.ticker)}>{row.ticker}</Link>
                <span>{row.assetType ?? "Asset"}</span>
              </td>
              <td className="asset-name-cell">
                <strong>{row.name}</strong>
                <span>{row.sector}</span>
                <p>{row.why}</p>
              </td>
              <td><strong>{formatPrice(row.price, row.currency)}</strong></td>
              <td><MarketMove value={row.changePercent} /></td>
              <td>{row.volumeRelative === null ? "n/a" : `${row.volumeRelative.toFixed(2)}x`}</td>
              <td><ScoreBadge value={row.sentimentScore} /></td>
              <td><ScoreBadge value={row.momentumScore} /></td>
              <td><ScoreBadge value={row.trendScore} /></td>
              <td><ScoreBadge value={row.newsScore} label={row.newsCount === null || row.newsCount === undefined ? undefined : `${row.newsCount}`} /></td>
              <td><ConfidenceMeter value={row.confidence} label="Confidence" /></td>
              <td><span className="terminal-signal">{row.signalType}</span></td>
              <td><RiskIndicator risk={row.riskLevel} score={row.riskScore} /></td>
              <td><span className={clsx("action-pill", actionTone(row.action))}>{row.action}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AssetDetailPanel({
  ticker,
  name,
  description,
  sector,
  exchange,
  assetType,
  price,
  currency,
  changePercent,
  blumScore,
  confidence,
  narrative
}: {
  ticker: string;
  name: string;
  description?: string;
  sector: string;
  exchange: string;
  assetType: string;
  price: number | null | undefined;
  currency?: string | null;
  changePercent?: number | null;
  blumScore?: number | null;
  confidence?: number | null;
  narrative?: string;
}) {
  return (
    <section className="asset-command-card">
      <div>
        <div className="terminal-eyebrow">Security Intelligence</div>
        <h1>{ticker}<span>{name}</span></h1>
        <p>{description || "Institutional asset profile from stored market, signal and news evidence."}</p>
        <div className="tag-row">
          <span>{assetType}</span>
          <span>{sector}</span>
          <span>{exchange}</span>
        </div>
      </div>
      <div className="asset-command-pricing">
        <span>Last price</span>
        <strong>{formatPrice(price ?? null, currency)}</strong>
        <MarketMove value={changePercent ?? null} />
        <div className="asset-command-scores">
          <ScoreBadge value={blumScore ?? null} label="Blum" />
          <ConfidenceMeter value={confidence ?? null} />
        </div>
      </div>
      {narrative && <div className="asset-command-narrative"><span>Main narrative</span><strong>{narrative}</strong></div>}
    </section>
  );
}

export function SignalCard({ signal }: { signal: Signal }) {
  const watchPoints = signal.watch_points?.items ?? [];
  return (
    <article className="signal-note-card">
      <div className="signal-note-head">
        <div>
          <Link href={assetPath(signal.ticker)}>{signal.ticker}</Link>
          <span>{signal.asset?.name ?? "Asset metadata pending"}</span>
        </div>
        <ScoreBadge value={signal.blum_score} label="Blum" />
      </div>
      <div className="signal-note-grid">
        <div><span>Signal</span><strong>{signal.classification}</strong></div>
        <div><span>Confidence</span><strong>{Number(signal.confidence_score ?? 0).toFixed(0)}</strong></div>
        <div><span>Risk</span><strong>{signal.risk_level}</strong></div>
        <div><span>Horizon</span><strong>{signal.time_horizon}</strong></div>
      </div>
      <p>{signal.explanation}</p>
      <div className="evidence-stack">
        <EvidencePill label="Momentum" value={signal.score_breakdown?.momentum_score} />
        <EvidencePill label="Trend" value={signal.score_breakdown?.trend_score} />
        <EvidencePill label="Sentiment" value={signal.score_breakdown?.sentiment_score} />
        <EvidencePill label="Risk Adj." value={signal.score_breakdown?.risk_adjustment} />
      </div>
      {!!watchPoints.length && (
        <ul>
          {watchPoints.slice(0, 3).map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </article>
  );
}

export function NarrativeCard({
  title,
  sentiment,
  volume,
  explanation,
  tickers = []
}: {
  title: string;
  sentiment?: number | null;
  volume?: number | null;
  explanation?: string;
  tickers?: string[];
}) {
  return (
    <article className="narrative-card">
      <div className="narrative-card-top">
        <strong>{title}</strong>
        <ScoreBadge value={sentiment === null || sentiment === undefined ? null : sentiment * 50 + 50} label="Sent" />
      </div>
      <p>{explanation || "Narrative cluster built from public news, semantic themes and linked asset evidence."}</p>
      <div className="narrative-card-meta">
        <span><Newspaper size={12} />{volume ?? 0} news</span>
        {tickers.slice(0, 5).map((ticker) => <Link href={assetPath(ticker)} key={ticker}>{ticker}</Link>)}
      </div>
    </article>
  );
}

export function NewsTape({ articles, limit = 12 }: { articles: LiveNewsArticle[]; limit?: number }) {
  return (
    <div className="terminal-news-tape">
      {!articles.length && <div className="terminal-empty">No live public news is stored yet. The tape will fill after RSS/web ingestion completes.</div>}
      {articles.slice(0, limit).map((article) => (
        <a href={article.url} target="_blank" rel="noreferrer" className="terminal-news-row" key={article.id}>
          <div>
            <strong>{article.title}</strong>
            <span>{article.source} | {formatTime(article.published_at)} | quality {Number(article.quality_score ?? 0).toFixed(1)}</span>
          </div>
          <div className="terminal-news-tags">
            {article.sentiment && <b className={article.sentiment.label}>{article.sentiment.label} {article.sentiment.score.toFixed(2)}</b>}
            {article.linked_assets.slice(0, 3).map((asset) => <em key={asset.ticker}>{asset.ticker}</em>)}
            {(article.theme_tags.themes ?? []).slice(0, 2).map((theme) => <em key={theme}>{theme}</em>)}
          </div>
        </a>
      ))}
    </div>
  );
}

export function toAssetRowsFromOpportunities(rows: OpportunityRow[]): AssetTableRow[] {
  return rows.map((row) => ({
    ticker: row.ticker,
    name: row.name,
    sector: row.sector,
    assetType: row.asset_type,
    price: row.last_price,
    currency: row.currency,
    changePercent: row.change_percent,
    volumeRelative: row.volume_relative,
    sentimentScore: row.sentiment_score,
    momentumScore: row.momentum_score,
    trendScore: row.trend_score,
    newsScore: row.news_score,
    confidence: confidenceFromOpportunity(row),
    signalType: row.classification || row.status_label,
    riskScore: row.risk_score,
    riskLevel: row.risk_level,
    action: actionFromScores(row.opportunity_score, row.risk_score, row.risk_level),
    why: row.why_today
  }));
}

export function toAssetRowsFromSignals(signals: Signal[]): AssetTableRow[] {
  return signals.map((signal) => ({
    ticker: signal.ticker,
    name: signal.asset?.name ?? "Name pending",
    sector: signal.asset?.sector ?? "Sector pending",
    assetType: signal.asset?.asset_type,
    price: signal.market_snapshot?.price ?? null,
    currency: signal.market_snapshot?.currency,
    changePercent: signal.market_snapshot?.perf_1d ?? null,
    volumeRelative: null,
    sentimentScore: Number(signal.score_breakdown?.sentiment_score ?? 0),
    momentumScore: Number(signal.score_breakdown?.momentum_score ?? 0),
    trendScore: Number(signal.score_breakdown?.trend_score ?? 0),
    newsScore: Number(signal.score_breakdown?.semantic_trend_score ?? signal.score_breakdown?.news_score ?? 0),
    confidence: Number(signal.confidence_score ?? signal.accuracy?.blum_confidence_score ?? 0),
    signalType: signal.classification,
    riskScore: Number(signal.score_breakdown?.volatility_score ?? signal.score_breakdown?.risk_adjustment ?? 0),
    riskLevel: signal.risk_level,
    action: actionFromScores(signal.blum_score, Number(signal.score_breakdown?.risk_adjustment ?? 50), signal.risk_level),
    why: signal.explanation
  }));
}

export function commandIcon(name: "regime" | "sentiment" | "risk" | "momentum" | "news" | "signals" | "ai" | "worker") {
  const icons = {
    regime: <Activity size={15} />,
    sentiment: <Gauge size={15} />,
    risk: <ShieldAlert size={15} />,
    momentum: <LineChart size={15} />,
    news: <Newspaper size={15} />,
    signals: <Zap size={15} />,
    ai: <Brain size={15} />,
    worker: <Database size={15} />
  };
  return icons[name];
}

function SortableHeader({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <th>
      <button className={clsx("sortable-head", active && "active")} onClick={onClick}>{label}</button>
    </th>
  );
}

function MarketMove({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="market-move neutral">n/a</span>;
  const positive = value >= 0;
  return (
    <span className={clsx("market-move", positive ? "positive" : "negative")}>
      {positive ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
      {positive ? "+" : ""}{Number(value).toFixed(2)}%
    </span>
  );
}

function EvidencePill({ label, value }: { label: string; value?: number }) {
  return (
    <span>
      {label}
      <b>{value === undefined || value === null ? "n/a" : Number(value).toFixed(0)}</b>
    </span>
  );
}

function actionFromScores(score: number, riskScore: number, riskLevel: string) {
  if (riskLevel.toLowerCase().includes("high") && score < 72) return "Avoid";
  if (score >= 84) return "Strong Attention";
  if (score >= 68) return "Watch";
  return "Monitor";
}

function actionTone(action: string) {
  if (action === "Strong Attention") return "attention";
  if (action === "Watch") return "positive";
  if (action === "Avoid") return "negative";
  return "neutral";
}

function confidenceFromOpportunity(row: OpportunityRow) {
  return clampScore((row.opportunity_score * 0.45) + (row.trend_score * 0.2) + (row.sentiment_score * 0.15) + (Math.max(0, 100 - row.risk_score) * 0.2));
}

function sortableValue(value: unknown) {
  if (typeof value === "number") return value;
  if (value === null || value === undefined) return -Infinity;
  return String(value).toLowerCase();
}

function clampScore(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0;
  return Math.max(0, Math.min(100, Number(value)));
}

function formatPrice(value: number | null, currency?: string | null) {
  if (value === null || value === undefined) return "n/a";
  const formatted = new Intl.NumberFormat("en", { maximumFractionDigits: value > 1000 ? 0 : 2 }).format(value);
  return `${currency ?? "USD"} ${formatted}`;
}

function formatTime(value: string | null) {
  if (!value) return "pending";
  return new Intl.DateTimeFormat("en", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
