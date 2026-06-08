"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LoadingState } from "@/components/LoadingState";

export default function ThemeExplorerPage() {
  const [themes, setThemes] = useState<any[] | null>(null);
  const [query, setQuery] = useState("AI infrastructure guidance");
  const [results, setResults] = useState<any[]>([]);
  useEffect(() => { api.themes().then(setThemes); }, []);
  const search = async () => setResults(await api.semanticSearch(query));
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
          <article className="panel" key={theme.label}>
            <div className="panel-head"><span>{theme.label}</span><strong>{theme.article_count ?? 0} articles</strong></div>
            <p>Keywords: {(theme.keywords ?? []).join(", ") || "semantic cluster"}</p>
          </article>
        ))}
      </section>
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

