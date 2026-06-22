"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, Crosshair, Target } from "lucide-react";
import { api } from "@/lib/api";
import { assetPath } from "@/lib/routes";
import { BloombergPanel, MetricCard, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export default function SniperPage() {
  const [payload, setPayload] = useState<any | null>(null);
  const [metrics, setMetrics] = useState<any | null>(null);
  const [lessons, setLessons] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function load() {
      setError("");
      const [candidateResult, metricsResult, lessonsResult] = await Promise.allSettled([
        api.sniperCandidates(48),
        api.sniperMetrics(),
        api.sniperLessons(24)
      ] as const);
      if (!mounted) return;
      if (candidateResult.status === "fulfilled") setPayload(candidateResult.value);
      if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value);
      if (lessonsResult.status === "fulfilled") setLessons(lessonsResult.value);
      const failed = [candidateResult, metricsResult, lessonsResult].find((item) => item.status === "rejected") as PromiseRejectedResult | undefined;
      if (failed) setError((failed.reason as Error).message);
    }
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const candidates = payload?.candidates ?? [];
  const summary = payload?.summary ?? {};
  const regime = payload?.market_regime ?? {};
  const sections = payload?.sections ?? {};
  const scoreChart = useMemo(() => [{
    x: candidates.slice(0, 18).map((item: any) => item.ticker),
    y: candidates.slice(0, 18).map((item: any) => item.sniper_score ?? 0),
    type: "bar",
    marker: { color: candidates.slice(0, 18).map((item: any) => colorForAction(item.actionability)) }
  }], [candidates]);
  const rRows = metrics?.r_multiple ?? [];
  const rChart = useMemo(() => [{
    x: rRows.slice(0, 14).map((item: any) => item.setup_type),
    y: rRows.slice(0, 14).map((item: any) => item.expectancy_r ?? 0),
    type: "bar",
    marker: { color: rRows.slice(0, 14).map((item: any) => Number(item.expectancy_r ?? 0) >= 0 ? "#20e070" : "#ff4d5e") }
  }], [rRows]);

  if (!payload && error) return <div className="empty-state">API error: {error}</div>;
  if (!payload) return <LoadingState label="Loading BLUM Market Sniper Engine" />;

  return (
    <>
      <TerminalHeader
        eyebrow="Market Sniper Engine"
        title="Actionability, not generic attractiveness."
        subtitle="Conditional entry logic, invalidation, target zones, R-multiple learning, no-trade intelligence and exit discipline. Research only."
        statusItems={[
          { label: "Regime", value: regime.regime_primary ?? "n/a", tone: regime.regime_primary === "risk_off" ? "negative" : "attention" },
          { label: "Candidates", value: String(summary.candidate_count ?? candidates.length) },
          { label: "Avg Sniper", value: formatNumber(summary.average_sniper_score), tone: "info" },
          { label: "Top Sniper", value: formatNumber(summary.top_sniper_score), tone: "positive" }
        ]}
        actions={<StatusBadge label="Informational scenarios only" />}
      />

      {error && <div className="empty-state" style={{ marginBottom: 12 }}>API warning: {error}</div>}

      <section className="terminal-command-grid">
        <MetricCard label="Risk Appetite" value={formatNumber(regime.risk_appetite_score)} subvalue={regime.breadth_state ?? "breadth n/a"} tone="attention" />
        <MetricCard label="Rotation Score" value={formatNumber(regime.sector_rotation_score)} subvalue={regime.regime_secondary ?? "secondary regime"} />
        <MetricCard label="Active Setups" value={sections.active_setups?.length ?? 0} subvalue="confirmed conditional" tone="positive" />
        <MetricCard label="Wait For Trigger" value={sections.wait_for_trigger?.length ?? 0} subvalue="interesting, not active" tone="attention" />
        <MetricCard label="Avoid" value={sections.avoid_list?.length ?? 0} subvalue="no-trade filter" tone="negative" />
        <MetricCard label="R-Metric Rows" value={rRows.length} subvalue="R-multiple memory" />
        <MetricCard label="Lessons" value={lessons.length} subvalue="recent reliability notes" />
        <MetricCard label="Policy" value="Wait > weak entry" subvalue="selective by design" />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="Sniper Score Distribution"
          data={scoreChart as any}
          layout={{ yaxis: { range: [0, 100], title: "Sniper Score" }, xaxis: { title: "Candidate" } }}
          emptyMessage="No Sniper candidates available yet."
        />
        <PlotPanel
          title="Expectancy by Setup Type"
          data={rChart as any}
          layout={{ yaxis: { title: "Expectancy in R" }, xaxis: { title: "Setup" } }}
          emptyMessage="R-multiple metrics appear after historical execution simulations."
        />
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        {candidates.slice(0, 9).map((item: any) => <SniperCard key={item.ticker} item={item} />)}
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <SniperList title="Active Setups" icon={<Crosshair size={17} />} rows={sections.active_setups ?? []} empty="No active conditional setup. BLUM prefers patience." />
        <SniperList title="Wait For Trigger" icon={<Target size={17} />} rows={sections.wait_for_trigger ?? []} empty="No wait-for-trigger setups." />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <SniperList title="Avoid List" icon={<AlertTriangle size={17} />} rows={sections.avoid_list ?? []} empty="No hard no-trade decisions in the current candidate set." />
        <BloombergPanel title="Recent Learning Lessons" value={`${lessons.length} notes`}>
          <div className="brain-list dense">
            {lessons.map((item: any, index) => (
              <div key={`${item.lesson}-${index}`}>
                <StatusBadge label={item.severity ?? "Info"} />
                <strong>{item.lesson}</strong>
                <p>Sample count: {item.sample_count ?? 0}. Reliability remains conditional and non-predictive.</p>
              </div>
            ))}
            {!lessons.length && <div className="empty-state">No Sniper lessons yet. Execution simulations will populate this panel.</div>}
          </div>
        </BloombergPanel>
      </section>

      <section style={{ marginTop: 12 }}>
        <BloombergPanel title="Execution Plan Matrix" value={`${candidates.length} candidates`} subtitle="Entry, trigger, invalidation, targets, risk/reward and no-trade reasons" className="radar-core-panel">
          <div className="table-shell">
            <table className="intel-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Actionability</th>
                  <th>Setup</th>
                  <th>Entry / Trigger</th>
                  <th>Risk</th>
                  <th>Targets</th>
                  <th>No-Trade</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((item: any) => {
                  const plan = item.trade_plan ?? {};
                  const setup = item.setup ?? {};
                  const risk = item.risk ?? {};
                  const entry = plan.entry_zone ?? {};
                  return (
                    <tr key={`plan-${item.ticker}`}>
                      <td>
                        <Link className="asset-link" href={assetPath(item.ticker)}>{item.ticker}</Link>
                        <span>{item.asset?.name}</span>
                      </td>
                      <td>
                        <StatusBadge label={item.actionability} />
                        <span>Sniper {formatNumber(item.sniper_score)}/100</span>
                      </td>
                      <td>
                        <strong>{setup.setup_type}</strong>
                        <span>Quality {formatNumber(setup.setup_quality_score)} | Reliability {formatNumber(setup.historical_reliability)}</span>
                      </td>
                      <td>
                        <strong>{entry.low ?? "n/a"} - {entry.high ?? "n/a"}</strong>
                        <span>{plan.entry_trigger}</span>
                      </td>
                      <td>
                        <strong>Invalidation {plan.invalidation_level ?? "n/a"}</strong>
                        <span>{risk.position_risk_class} | RR {plan.risk_reward_estimate?.reward_to_risk ?? "n/a"}R</span>
                      </td>
                      <td>
                        <strong>{plan.target_1 ?? "n/a"} / {plan.target_2 ?? "n/a"}</strong>
                        <span>{plan.trailing_exit_logic}</span>
                      </td>
                      <td>
                        <span>{item.no_trade_reasons?.[0]?.reason ?? "No hard block; trigger still required."}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </BloombergPanel>
      </section>
    </>
  );
}

function SniperCard({ item }: { item: any }) {
  const plan = item.trade_plan ?? {};
  const setup = item.setup ?? {};
  const risk = item.risk ?? {};
  return (
    <article className="score-card stock-radar-card">
      <div className="score-card-top">
        <div>
          <span>{item.asset?.sector ?? "Unknown"} | {setup.setup_type}</span>
          <h3>{item.ticker}</h3>
          <p className="asset-subtitle">{item.asset?.name}</p>
        </div>
        <div className="score-ring" style={{ "--score": item.sniper_score ?? 0 } as any}>
          <strong>{Math.round(item.sniper_score ?? 0)}</strong>
        </div>
      </div>
      <StatusBadge label={item.actionability} />
      <p>{item.explanation}</p>
      <div className="mini-metrics">
        <div><span>Entry</span><strong>{plan.entry_zone?.low ?? "n/a"}-{plan.entry_zone?.high ?? "n/a"}</strong></div>
        <div><span>Invalidation</span><strong>{plan.invalidation_level ?? "n/a"}</strong></div>
        <div><span>RR</span><strong>{plan.risk_reward_estimate?.reward_to_risk ?? "n/a"}R</strong></div>
        <div><span>Risk</span><strong>{risk.position_risk_class ?? "n/a"}</strong></div>
      </div>
    </article>
  );
}

function SniperList({ title, icon, rows, empty }: { title: string; icon: ReactNode; rows: any[]; empty: string }) {
  return (
    <BloombergPanel title={title} value={`${rows.length} names`}>
      <div className="brain-list dense">
        {rows.slice(0, 12).map((item) => (
          <div key={`${title}-${item.ticker}`}>
            <div className="opportunity-line">
              <strong>{icon}{item.ticker}</strong>
              <StatusBadge label={item.actionability} />
            </div>
            <p>{item.explanation}</p>
            <div className="mini-metrics">
              <div><span>Score</span><strong>{formatNumber(item.sniper_score)}</strong></div>
              <div><span>Setup</span><strong>{item.setup?.setup_type}</strong></div>
              <div><span>RR</span><strong>{item.trade_plan?.risk_reward_estimate?.reward_to_risk ?? "n/a"}R</strong></div>
              <div><span>Invalidation</span><strong>{item.trade_plan?.invalidation_level ?? "n/a"}</strong></div>
            </div>
          </div>
        ))}
        {!rows.length && <div className="empty-state">{empty}</div>}
      </div>
    </BloombergPanel>
  );
}

function colorForAction(action: string) {
  if (action === "active_setup") return "#20e070";
  if (action === "actionable_if_confirmed" || action === "wait_for_trigger") return "#ffb000";
  if (action === "avoid") return "#ff4d5e";
  return "#55aaff";
}

function formatNumber(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(1);
}
