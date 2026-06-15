"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LoadingState } from "@/components/LoadingState";

export default function ThemeExplorerPage() {
  const [themes, setThemes] = useState<any[] | null>(null);
  const [themeDetail, setThemeDetail] = useState<any | null>(null);
  const [query, setQuery] = useState("AI infrastructure guidance");
  const [results, setResults] = useState<any[]>([]);
  useEffect(() => { api.themes().then(setThemes); }, []);
  const search = async () => setResults(await api.semanticSearch(query));
  const openTheme = async (label: string) => setThemeDetail(await api.themeDetail(label));
  if (!themes) return <LoadingState label="Loading semantic themes" />;
  return (
    <>
      <div className="page-header">
        <div><div className="kicker">Theme Explorer</div><h1>Semantic narratives emerging from public news.</h1></div>
      </div>
      <div className="control-row">
        <input className="input" value={query} onChange={(event) => setQuery(event.target.value)} />
        <button className="button primary" onClick={search}>Semantic search</button>
      </div>
      <section className="grid-3">
        {themes.slice(0, 12).map((theme) => (
          <article className="panel theme-card" key={theme.label} onClick={() => openTheme(theme.label)}>
            <div className="panel-head"><span>{theme.label}</span><strong>{theme.article_count ?? 0} articles</strong></div>
            <p>Keywords: {(theme.keywords ?? []).join(", ") || "semantic cluster"}</p>
            <div className="tag-row">
              <span>sentiment {Number(theme.sentiment_score ?? 0).toFixed(2)}</span>
              <span>{theme.cluster_method ?? "theme aggregation"}</span>
            </div>
          </article>
        ))}
      </section>
      {themeDetail && (
        <section className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>Theme detail</span><strong>{themeDetail.label}</strong></div>
          <div className="grid-4">
            <Metric label="Articles" value={themeDetail.article_count} />
            <Metric label="Avg Sentiment" value={Number(themeDetail.average_sentiment).toFixed(2)} />
            <Metric label="Sources" value={themeDetail.source_mix.length} />
            <Metric label="Assets" value={themeDetail.linked_assets.length} />
          </div>
          <div className="grid-2" style={{ marginTop: 12 }}>
            <div className="observed-model-panel">
              <div className="panel-head"><span>Linked assets</span></div>
              <div className="tag-row">
                {themeDetail.linked_assets.slice(0, 20).map((asset: any) => <span key={asset.ticker}>{asset.ticker} {asset.mentions}</span>)}
              </div>
            </div>
            <div className="observed-model-panel">
              <div className="panel-head"><span>Source mix</span></div>
              <div className="tag-row">
                {themeDetail.source_mix.slice(0, 16).map((source: any) => <span key={source.source}>{source.source} {source.count}</span>)}
              </div>
            </div>
          </div>
          <div className="news-list" style={{ marginTop: 12 }}>
            {themeDetail.articles.slice(0, 16).map((article: any) => (
              <a className="news-item" href={article.url} target="_blank" rel="noreferrer" key={article.id}>
                <strong>{article.title}</strong>
                <span>{article.source} | sentiment {article.sentiment?.score?.toFixed?.(2) ?? "n/a"} | assets {(article.linked_assets ?? []).map((asset: any) => asset.ticker).join(" | ")}</span>
              </a>
            ))}
          </div>
        </section>
      )}
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Semantic Search Results</span></div>
        <div className="news-list">
          {results.map((row) => (
            <a className="news-item" href={row.article.url} target="_blank" rel="noreferrer" key={row.article.id}>
              <strong>{row.article.title}</strong>
              <span>Similarity {Number(row.score).toFixed(3)} | {row.article.source}</span>
            </a>
          ))}
        </div>
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}
