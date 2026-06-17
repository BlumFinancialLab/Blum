"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, NarrativeCard, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";

const NARRATIVE_TAXONOMY = ["AI", "Rates", "Geopolitics", "Earnings", "Energy", "Crypto/Fintech", "Market Structure"];

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
      <TerminalHeader
        eyebrow="Themes and Narratives"
        title="Market narrative intelligence."
        subtitle="Semantic clusters, rising themes, linked tickers and source evidence from public financial news."
        statusItems={[
          { label: "Clusters", value: String(themes.length), tone: themes.length ? "positive" : "attention" },
          { label: "Taxonomy", value: String(NARRATIVE_TAXONOMY.length) },
          { label: "Search", value: results.length ? `${results.length} results` : "ready", tone: "info" },
          { label: "Mode", value: "Evidence only" }
        ]}
      />

      <section className="professional-grid-3">
        {NARRATIVE_TAXONOMY.map((label) => {
          const match = themes.find((theme) => String(theme.label).toLowerCase().includes(label.split("/")[0].toLowerCase()));
          return (
            <NarrativeCard
              key={label}
              title={label}
              sentiment={match?.sentiment_score}
              volume={match?.article_count ?? 0}
              explanation={match ? `Active semantic cluster: ${(match.keywords ?? []).slice(0, 4).join(", ") || "keywords pending"}.` : "Strategic narrative taxonomy monitored for future evidence."}
            />
          );
        })}
      </section>

      <BloombergPanel title="Semantic Search" value="Vector evidence" subtitle="Search public news embeddings and narrative clusters" className="radar-core-panel">
        <div className="control-row" style={{ marginBottom: 0 }}>
          <input className="input" value={query} onChange={(event) => setQuery(event.target.value)} />
          <button className="button primary" onClick={search}>Semantic search</button>
        </div>
      </BloombergPanel>

      <section className="professional-grid-3" style={{ marginTop: 12 }}>
        {themes.slice(0, 12).map((theme) => (
          <article className="narrative-card theme-card" key={theme.label} onClick={() => openTheme(theme.label)}>
            <div className="narrative-card-top">
              <strong>{theme.label}</strong>
              <span className="score-badge tone-attention"><strong>{theme.article_count ?? 0}</strong><em>news</em></span>
            </div>
            <p>Keywords: {(theme.keywords ?? []).join(", ") || "semantic cluster"}</p>
            <div className="narrative-card-meta">
              <span>sentiment {Number(theme.sentiment_score ?? 0).toFixed(2)}</span>
              <span>{theme.cluster_method ?? "theme aggregation"}</span>
            </div>
          </article>
        ))}
      </section>
      {themeDetail && (
        <BloombergPanel title="Theme Detail" value={themeDetail.label} className="radar-core-panel">
          <div className="professional-grid-4">
            <Metric label="Articles" value={themeDetail.article_count} />
            <Metric label="Avg Sentiment" value={Number(themeDetail.average_sentiment).toFixed(2)} />
            <Metric label="Sources" value={themeDetail.source_mix.length} />
            <Metric label="Assets" value={themeDetail.linked_assets.length} />
          </div>
          <div className="professional-grid-2" style={{ marginTop: 12 }}>
            <BloombergPanel title="Linked Assets" dense>
              <div className="tag-row">
                {themeDetail.linked_assets.slice(0, 20).map((asset: any) => <span key={asset.ticker}>{asset.ticker} {asset.mentions}</span>)}
              </div>
            </BloombergPanel>
            <BloombergPanel title="Source Mix" dense>
              <div className="tag-row">
                {themeDetail.source_mix.slice(0, 16).map((source: any) => <span key={source.source}>{source.source} {source.count}</span>)}
              </div>
            </BloombergPanel>
          </div>
          <div className="news-list" style={{ marginTop: 12 }}>
            {themeDetail.articles.slice(0, 16).map((article: any) => (
              <a className="news-item" href={article.url} target="_blank" rel="noreferrer" key={article.id}>
                <strong>{article.title}</strong>
                <span>{article.source} | sentiment {article.sentiment?.score?.toFixed?.(2) ?? "n/a"} | assets {(article.linked_assets ?? []).map((asset: any) => asset.ticker).join(" | ")}</span>
              </a>
            ))}
          </div>
        </BloombergPanel>
      )}
      <BloombergPanel title="Semantic Search Results" value={`${results.length} matches`} className="radar-core-panel">
        <div className="news-list">
          {results.map((row) => (
            <a className="news-item" href={row.article.url} target="_blank" rel="noreferrer" key={row.article.id}>
              <strong>{row.article.title}</strong>
              <span>Similarity {Number(row.score).toFixed(3)} | {row.article.source}</span>
            </a>
          ))}
        </div>
      </BloombergPanel>
    </>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <MetricCard label={label} value={value} />;
}
