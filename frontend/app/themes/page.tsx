"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, NarrativeCard, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";

const NARRATIVE_TAXONOMY = ["AI", "Rates", "Geopolitics", "Earnings", "Energy", "Crypto/Fintech", "Market Structure"];

type ThemeRow = {
  label?: string;
  article_count?: number;
  sentiment_score?: number;
  keywords?: string[];
  cluster_method?: string;
};

export default function ThemeExplorerPage() {
  const [themes, setThemes] = useState<ThemeRow[] | null>(null);
  const [themeDetail, setThemeDetail] = useState<any | null>(null);
  const [query, setQuery] = useState("AI infrastructure guidance");
  const [results, setResults] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [searchError, setSearchError] = useState("");
  const [searching, setSearching] = useState(false);
  const [openingTheme, setOpeningTheme] = useState("");

  useEffect(() => {
    let active = true;
    api.themes()
      .then((payload) => {
        if (!active) return;
        setThemes(Array.isArray(payload) ? payload : []);
        setError("");
      })
      .catch((err) => {
        if (!active) return;
        setThemes([]);
        setError((err as Error).message);
      });
    return () => { active = false; };
  }, []);

  const totals = useMemo(() => {
    const rows = themes ?? [];
    const articleCount = rows.reduce((sum, theme) => sum + numberValue(theme.article_count), 0);
    const averageSentiment = rows.length
      ? rows.reduce((sum, theme) => sum + numberValue(theme.sentiment_score), 0) / rows.length
      : 0;
    return { articleCount, averageSentiment };
  }, [themes]);

  const search = async () => {
    setSearching(true);
    setSearchError("");
    try {
      const payload = await api.semanticSearch(query);
      setResults(Array.isArray(payload) ? payload : []);
    } catch (err) {
      setResults([]);
      setSearchError((err as Error).message);
    } finally {
      setSearching(false);
    }
  };

  const openTheme = async (label: string) => {
    if (!label) return;
    setOpeningTheme(label);
    setDetailError("");
    try {
      setThemeDetail(await api.themeDetail(label));
    } catch (err) {
      setThemeDetail(null);
      setDetailError((err as Error).message);
    } finally {
      setOpeningTheme("");
    }
  };

  if (themes === null) return <LoadingState label="Loading semantic themes" />;

  return (
    <>
      <TerminalHeader
        eyebrow="Themes and Narratives"
        title="Market narrative intelligence."
        subtitle="Semantic clusters, rising themes, linked tickers and source evidence from public financial news."
        statusItems={[
          { label: "Clusters", value: String(themes.length), tone: themes.length ? "positive" : "attention" },
          { label: "Articles", value: String(totals.articleCount), tone: totals.articleCount ? "info" : "attention" },
          { label: "Avg sentiment", value: totals.averageSentiment.toFixed(2), tone: totals.averageSentiment >= 0 ? "positive" : "negative" },
          { label: "Mode", value: "Evidence only" }
        ]}
      />

      {error && (
        <div className="terminal-empty" style={{ marginBottom: 12 }}>
          Narratives endpoint warning: {error}. The autonomous engine will keep rebuilding semantic clusters as evidence arrives.
        </div>
      )}

      <section className="professional-grid-3">
        {NARRATIVE_TAXONOMY.map((label) => {
          const token = label.split("/")[0].toLowerCase();
          const match = themes.find((theme) => String(theme.label ?? "").toLowerCase().includes(token));
          return (
            <NarrativeCard
              key={label}
              title={label}
              sentiment={match?.sentiment_score}
              volume={match?.article_count ?? 0}
              explanation={match ? `Active semantic cluster: ${safeList(match.keywords).slice(0, 4).join(", ") || "keywords pending"}.` : "Strategic narrative taxonomy monitored for future evidence."}
            />
          );
        })}
      </section>

      <BloombergPanel title="Semantic Search" value="Vector evidence" subtitle="Search public news embeddings and narrative clusters" className="radar-core-panel">
        <div className="control-row" style={{ marginBottom: 0 }}>
          <input className="input" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Semantic search query" />
          <button className="button primary" onClick={search} disabled={searching || query.trim().length < 3}>
            {searching ? "Searching..." : "Semantic search"}
          </button>
        </div>
        {searchError && <div className="terminal-empty compact" style={{ marginTop: 10 }}>Search warning: {searchError}</div>}
      </BloombergPanel>

      <section className="professional-grid-3" style={{ marginTop: 12 }}>
        {themes.slice(0, 12).map((theme, index) => {
          const label = String(theme.label ?? `Theme ${index + 1}`);
          return (
            <article className="narrative-card theme-card" key={`${label}-${index}`} onClick={() => openTheme(label)}>
              <div className="narrative-card-top">
                <strong>{label}</strong>
                <span className="score-badge tone-attention"><strong>{numberValue(theme.article_count)}</strong><em>news</em></span>
              </div>
              <p>Keywords: {safeList(theme.keywords).join(", ") || "semantic cluster"}</p>
              <div className="narrative-card-meta">
                <span>sentiment {numberValue(theme.sentiment_score).toFixed(2)}</span>
                <span>{openingTheme === label ? "loading detail" : theme.cluster_method ?? "theme aggregation"}</span>
              </div>
            </article>
          );
        })}
      </section>

      {!themes.length && !error && (
        <BloombergPanel title="Narrative Coverage" value="Building" className="radar-core-panel">
          <div className="terminal-empty">
            No semantic clusters are stored yet. The autonomous engine is hydrating news, embeddings and theme memory in the background.
          </div>
        </BloombergPanel>
      )}

      {detailError && <div className="terminal-empty" style={{ marginTop: 12 }}>Theme detail warning: {detailError}</div>}

      {themeDetail && <ThemeDetailPanel detail={themeDetail} />}

      <BloombergPanel title="Semantic Search Results" value={`${results.length} matches`} className="radar-core-panel">
        <div className="news-list">
          {results.length === 0 && <div className="terminal-empty compact">Search results will appear here after a query is submitted.</div>}
          {results.map((row, index) => {
            const article = row.article ?? {};
            return (
              <a className="news-item" href={article.url ?? "#"} target="_blank" rel="noreferrer" key={`${article.id ?? article.url ?? "result"}-${index}`}>
                <strong>{article.title ?? "Untitled evidence item"}</strong>
                <span>Similarity {numberValue(row.score).toFixed(3)} | {article.source ?? "unknown source"}</span>
              </a>
            );
          })}
        </div>
      </BloombergPanel>
    </>
  );
}

function ThemeDetailPanel({ detail }: { detail: any }) {
  const sources = safeList(detail.source_mix);
  const assets = safeList(detail.linked_assets);
  const articles = safeList(detail.articles);
  return (
    <BloombergPanel title="Theme Detail" value={detail.label ?? "Narrative"} className="radar-core-panel">
      <div className="professional-grid-4">
        <Metric label="Articles" value={numberValue(detail.article_count)} />
        <Metric label="Avg Sentiment" value={numberValue(detail.average_sentiment).toFixed(2)} />
        <Metric label="Sources" value={sources.length} />
        <Metric label="Assets" value={assets.length} />
      </div>
      <div className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Linked Assets" dense>
          <div className="tag-row">
            {assets.length === 0 && <span>No linked tickers yet</span>}
            {assets.slice(0, 20).map((asset: any, index) => <span key={`${asset.ticker ?? "asset"}-${index}`}>{asset.ticker ?? "Asset"} {asset.mentions ?? 0}</span>)}
          </div>
        </BloombergPanel>
        <BloombergPanel title="Source Mix" dense>
          <div className="tag-row">
            {sources.length === 0 && <span>No source concentration yet</span>}
            {sources.slice(0, 16).map((source: any, index) => <span key={`${source.source ?? "source"}-${index}`}>{source.source ?? "Source"} {source.count ?? 0}</span>)}
          </div>
        </BloombergPanel>
      </div>
      <div className="news-list" style={{ marginTop: 12 }}>
        {articles.length === 0 && <div className="terminal-empty compact">No articles are linked to this theme yet.</div>}
        {articles.slice(0, 16).map((article: any, index) => (
          <a className="news-item" href={article.url ?? "#"} target="_blank" rel="noreferrer" key={`${article.id ?? article.url ?? "article"}-${index}`}>
            <strong>{article.title ?? "Untitled article"}</strong>
            <span>{article.source ?? "unknown"} | sentiment {numberValue(article.sentiment?.score).toFixed(2)} | assets {safeList(article.linked_assets).map((asset: any) => asset.ticker).filter(Boolean).join(" | ") || "n/a"}</span>
          </a>
        ))}
      </div>
    </BloombergPanel>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <MetricCard label={label} value={value} />;
}

function safeList<T = any>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function numberValue(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}
