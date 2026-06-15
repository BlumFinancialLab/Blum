"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { IPORadar, IPORadarRow } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

const SECTIONS = [
  ["highest_opportunity", "Highest Opportunity"],
  ["final_prospectus_watch", "Final Prospectus"],
  ["advanced_filing_watch", "Advanced Filing"],
  ["narrative_watch", "Narrative Watch"],
  ["early_filing_watch", "Early Filing"],
] as const;

export default function IPORadarPage() {
  const [radar, setRadar] = useState<IPORadar | null>(null);
  const [selectedSection, setSelectedSection] = useState<string>("highest_opportunity");
  const [search, setSearch] = useState("");
  const [classification, setClassification] = useState("");
  const [busy, setBusy] = useState(false);
  const [secBusy, setSecBusy] = useState("");
  const [error, setError] = useState("");
  const [updateResult, setUpdateResult] = useState<any>(null);
  const [secResult, setSecResult] = useState<any>(null);

  const load = async () => {
    setError("");
    try {
      setRadar(await api.ipoRadar(120));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => { load(); }, []);

  const runUpdate = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.updateIpoRadar(70);
      setUpdateResult(result);
      setRadar(result.radar);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const loadSecSubmissions = async (row: IPORadarRow, persist: boolean) => {
    if (!row.company.cik) return;
    setSecBusy(row.company.cik);
    setError("");
    try {
      const result = await api.secSubmissions(row.company.cik, persist);
      setSecResult(result);
      if (persist) await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSecBusy("");
    }
  };

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    const base = radar?.sections?.[selectedSection] ?? radar?.rows ?? [];
    return base.filter((row) =>
      (!classification || row.score.classification === classification) &&
      (!query || `${row.company.name} ${row.company.cik ?? ""} ${row.latest_filing?.form_type ?? ""}`.toLowerCase().includes(query))
    );
  }, [radar, selectedSection, search, classification]);

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!radar) return <LoadingState label="Loading IPO Radar" />;

  const classifications = Array.from(new Set(radar.rows.map((row) => row.score.classification))).sort();
  const plotted = radar.rows.slice(0, 36);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">IPO Radar</div>
          <h1>SEC filing and pre-listing intelligence.</h1>
        </div>
        <button className="button primary" onClick={runUpdate} disabled={busy}>{busy ? "Scanning SEC..." : "Refresh SEC filings"}</button>
      </div>

      <section className="grid-4">
        <Metric label="Companies" value={radar.summary.companies_observed} />
        <Metric label="Filings" value={radar.summary.filings_observed} />
        <Metric label="Scored" value={radar.summary.scored_companies} />
        <Metric label="Top Score" value={radar.summary.top_opportunity_score.toFixed(1)} />
      </section>

      {!radar.rows.length && (
        <section className="panel readiness-panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>SEC readiness</span><strong>No IPO rows yet</strong></div>
          <p>
            IPO Radar only displays observed SEC filings and public pre-listing narratives. Refresh SEC filings to hydrate the table;
            no listing dates, valuations or tickers are generated.
          </p>
        </section>
      )}

      {updateResult && (
        <section className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>SEC update diagnostics</span><strong>{updateResult.status}</strong></div>
          <div className="diagnostic-grid">
            <div>
              <span>SEC forms</span>
              <strong>{updateResult.forms_requested?.join(" | ")}</strong>
              <p>{updateResult.inserted_filings ?? 0} inserted | {updateResult.duplicate_filings ?? 0} duplicates | {updateResult.companies_touched ?? 0} companies touched</p>
            </div>
            <div>
              <span>Source errors</span>
              <strong>{updateResult.source_errors?.length ?? 0}</strong>
              <p>{(updateResult.source_errors ?? []).slice(0, 3).map((item: any) => `${item.form_type}: ${item.status}`).join(" | ") || "No source warnings"}</p>
            </div>
          </div>
        </section>
      )}

      <section className="radar-tabs" style={{ marginTop: 12 }}>
        {SECTIONS.map(([key, label]) => (
          <button className={selectedSection === key ? "active" : ""} onClick={() => setSelectedSection(key)} key={key}>
            {label}<span>{radar.sections[key]?.length ?? 0}</span>
          </button>
        ))}
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="IPO Opportunity Score"
          data={[{
            x: plotted.map((row) => row.score.opportunity_score),
            y: plotted.map((row) => row.company.name.slice(0, 32)),
            type: "bar",
            orientation: "h",
            marker: { color: "#ffb000" },
          }]}
          layout={{ xaxis: { range: [0, 100] } }}
          emptyMessage="IPO opportunity scores appear after SEC filing rows are stored."
        />
        <PlotPanel
          title="Readiness vs Listing Probability"
          data={[{
            x: plotted.map((row) => row.score.readiness_score),
            y: plotted.map((row) => row.score.listing_probability_score),
            text: plotted.map((row) => row.company.name),
            type: "scatter",
            mode: "markers+text",
            marker: { size: plotted.map((row) => Math.max(9, row.score.opportunity_score / 5)), color: "#4dd8ff" },
          }]}
          layout={{ xaxis: { range: [0, 100], title: "Readiness" }, yaxis: { range: [0, 100], title: "Listing probability proxy" } }}
          emptyMessage="Readiness/listing probability requires scored SEC filing evidence."
        />
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        {rows.slice(0, 6).map((row) => (
          <IPORadarCard
            row={row}
            key={`${row.company.id}-${row.latest_filing?.accession_number ?? row.company.name}`}
            onLoadSec={(persist) => loadSecSubmissions(row, persist)}
            secBusy={secBusy === row.company.cik}
          />
        ))}
      </section>

      {secResult && (
        <section className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>SEC company submissions</span><strong>{secResult.name ?? secResult.cik}</strong></div>
          <div className="diagnostic-grid">
            <div>
              <span>Official filing history</span>
              <strong>{secResult.filing_count} filings | {secResult.ipo_related_filing_count} IPO-related</strong>
              <p>{(secResult.tickers ?? []).join(" | ") || "No public ticker in SEC payload"} | {(secResult.exchanges ?? []).join(" | ") || "No exchange in SEC payload"}</p>
            </div>
            <div>
              <span>Persistence</span>
              <strong>{secResult.persisted_new_ipo_filings ?? 0} new filings stored</strong>
              <p>{secResult.data_policy}</p>
            </div>
          </div>
          <div className="table-shell" style={{ marginTop: 12 }}>
            <table className="intel-table">
              <thead><tr><th>Form</th><th>Date</th><th>Description</th><th>Document</th></tr></thead>
              <tbody>
                {(secResult.ipo_related_filings ?? []).slice(0, 20).map((filing: any) => (
                  <tr key={filing.accession_number}>
                    <td><strong>{filing.form_type}</strong></td>
                    <td><span>{formatTime(filing.filing_date)}</span></td>
                    <td><span>{filing.description ?? "n/a"}</span></td>
                    <td>{filing.url ? <a className="asset-link" href={filing.url} target="_blank" rel="noreferrer">Open</a> : <span>n/a</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>IPO radar table</span><strong>{rows.length} companies</strong></div>
        <div className="control-row">
          <input className="input" placeholder="Search company, CIK, form" value={search} onChange={(event) => setSearch(event.target.value)} />
          <select className="input" value={classification} onChange={(event) => setClassification(event.target.value)}>
            <option value="">All classifications</option>
            {classifications.map((item) => <option key={item}>{item}</option>)}
          </select>
        </div>
        <IPORadarTable rows={rows} />
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Public pre-listing narratives</span><strong>{radar.prelisting_narratives.length}</strong></div>
        {!radar.prelisting_narratives.length && <div className="empty-state">No IPO/listing headlines are stored yet from the public news tape.</div>}
        <div className="news-list">
          {radar.prelisting_narratives.slice(0, 12).map((article) => (
            <a className="news-item" href={article.url} target="_blank" rel="noreferrer" key={article.id}>
              <strong>{article.title}</strong>
              <span>{article.source} | {formatTime(article.published_at)} | quality {article.quality_score.toFixed(1)}</span>
            </a>
          ))}
        </div>
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Source policy</span><strong>{radar.data_mode}</strong></div>
        <p>{radar.source_diagnostics.data_policy}</p>
        <p>Tracked forms: {(radar.source_diagnostics.forms_tracked ?? []).join(" | ")}</p>
      </section>
    </>
  );
}

function IPORadarCard({ row, onLoadSec, secBusy }: { row: IPORadarRow; onLoadSec: (persist: boolean) => void; secBusy: boolean }) {
  return (
    <article className="score-card ipo-card">
      <div className="score-card-top">
        <div>
          <span>{row.latest_filing?.form_type ?? "SEC filing"} | {formatTime(row.latest_filing?.filing_date ?? null)}</span>
          <h3>{row.company.name}</h3>
          <p className="asset-subtitle">CIK {row.company.cik ?? "n/a"} | {row.company.sector}</p>
        </div>
        <div className="score-ring" style={{ "--score": row.score.opportunity_score } as any}>
          <strong>{Math.round(row.score.opportunity_score)}</strong>
        </div>
      </div>
      <StatusBadge label={row.score.classification} />
      <p>{row.score.explanation}</p>
      <div className="mini-metrics">
        <div><span>Readiness</span><strong>{row.score.readiness_score.toFixed(0)}</strong></div>
        <div><span>Listing proxy</span><strong>{row.score.listing_probability_score.toFixed(0)}</strong></div>
        <div><span>Narrative</span><strong>{row.score.narrative_heat_score.toFixed(0)}</strong></div>
        <div><span>Risk terms</span><strong>{row.score.valuation_risk_score.toFixed(0)}</strong></div>
      </div>
      <div className="control-row" style={{ marginTop: 12, marginBottom: 0 }}>
        {row.latest_filing?.url && <a className="button" href={row.latest_filing.url} target="_blank" rel="noreferrer">Open SEC filing</a>}
        {row.company.cik && <button className="button" onClick={() => onLoadSec(false)} disabled={secBusy}>{secBusy ? "Loading SEC..." : "SEC history"}</button>}
        {row.company.cik && <button className="button" onClick={() => onLoadSec(true)} disabled={secBusy}>{secBusy ? "Syncing..." : "Sync filings"}</button>}
      </div>
    </article>
  );
}

function IPORadarTable({ rows }: { rows: IPORadarRow[] }) {
  if (!rows.length) return <div className="empty-state">No IPO radar rows match the current filters.</div>;
  return (
    <div className="table-shell">
      <table className="intel-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Filing</th>
            <th>Classification</th>
            <th>Scores</th>
            <th>Evidence</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.company.id}-${row.score.created_at}`}>
              <td>
                <strong>{row.company.name}</strong>
                <span>CIK {row.company.cik ?? "n/a"} | {row.company.sector} | {row.company.country}</span>
              </td>
              <td>
                {row.latest_filing?.url ? <a className="asset-link" href={row.latest_filing.url} target="_blank" rel="noreferrer">{row.latest_filing.form_type}</a> : <strong>n/a</strong>}
                <span>{formatTime(row.latest_filing?.filing_date ?? null)}</span>
                <span>{row.latest_filing?.accession_number ?? "accession n/a"}</span>
              </td>
              <td>
                <StatusBadge label={row.score.classification} />
                <span>{row.score.time_horizon}</span>
              </td>
              <td>
                <strong className="score-number">{row.score.opportunity_score.toFixed(1)}</strong>
                <span>Ready {row.score.readiness_score.toFixed(0)} | Prob {row.score.listing_probability_score.toFixed(0)}</span>
                <span>Narr {row.score.narrative_heat_score.toFixed(0)} | Quality {row.score.quality_score.toFixed(0)} | Risk {row.score.valuation_risk_score.toFixed(0)}</span>
              </td>
              <td>
                <span>Forms {(row.score.evidence.forms_observed ?? []).join(" | ")}</span>
                <span>Filings {row.score.evidence.filing_count ?? 0} | Amendments {row.score.evidence.amendment_count ?? 0}</span>
                <span>Themes {(row.score.evidence.themes ?? []).join(" | ") || "n/a"}</span>
              </td>
              <td className="why">{row.score.explanation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function formatTime(value: string | null) {
  if (!value) return "Pending";
  return new Intl.DateTimeFormat("en", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
