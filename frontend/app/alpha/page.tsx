"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BarChart3, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, MiniSparkline, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";

export default function AlphaPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    api.traderAlpha()
      .then((payload) => mounted && setData(payload))
      .catch((err) => mounted && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  const spark = useMemo(() => {
    const values = [
      Number(data?.historical?.average_excess_return),
      Number(data?.walk_forward?.average_excess_return),
      Number(data?.paper_forward?.average_excess_return),
      Number(data?.live_forward?.average_excess_return),
    ].filter(Number.isFinite);
    return values.length > 1 ? values : [0, Number(data?.alpha) || 0];
  }, [data]);

  if (error) return <div className="terminal-empty">Alpha error: {error}</div>;
  if (!data) return <LoadingState label="Loading Alpha Evidence" />;

  const alphaTone = Number(data.alpha) > 0 ? "positive" : Number(data.alpha) < 0 ? "negative" : "attention";

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Alpha"
        title="Is BLUM beating the market?"
        subtitle="Nothing else belongs here. Alpha is benchmark-relative, sample-size aware and allowed to be negative."
        statusItems={[
          { label: "Status", value: data.status ?? "unknown", tone: data.status === "READY" ? "positive" : "attention" },
          { label: "Evidence", value: data.evidence_grade ?? "unknown", tone: evidenceTone(data.evidence_grade) },
          { label: "Sample", value: String(data.sample_size ?? 0), tone: data.sample_size >= 100 ? "positive" : "attention" },
          { label: "Policy", value: "truth first", tone: "info" },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="BLUM Return" value={formatPct(data.blum_return)} subvalue="Paper/research evidence" icon={<TrendingUp size={15} />} tone={Number(data.blum_return) > 0 ? "positive" : "negative"} />
        <MetricCard label="Benchmark Return" value={formatPct(data.benchmark_return)} subvalue="Comparable stored benchmark" icon={<BarChart3 size={15} />} tone="info" />
        <MetricCard label="Alpha" value={formatPct(data.alpha)} subvalue="Average excess return" icon={Number(data.alpha) >= 0 ? <TrendingUp size={15} /> : <TrendingDown size={15} />} tone={alphaTone} />
        <MetricCard label="Drawdown" value={formatPct(data.drawdown)} subvalue="Risk must be visible" icon={<AlertTriangle size={15} />} tone={Number(data.drawdown) < -15 ? "negative" : "attention"} />
        <MetricCard label="Win Rate" value={formatPct(Number(data.win_rate) * 100)} subvalue={`expectancy ${formatNumber(data.expectancy)}R`} icon={<ShieldCheck size={15} />} tone={Number(data.win_rate) > 0.5 ? "positive" : "attention"} />
        <MetricCard label="Profit Factor" value={formatNumber(data.profit_factor)} subvalue={`sample ${data.sample_size ?? 0}`} icon={<BarChart3 size={15} />} tone={Number(data.profit_factor) > 1 ? "positive" : "attention"} />
      </section>

      <section className="grid-2">
        <BloombergPanel title="Current Alpha Readiness" value={<ScoreBadge value={data.current_alpha_readiness?.alpha_readiness_score} label="alpha" />} subtitle="Big green only when evidence exists. Orange when weak. Red when evidence disproves the strategy.">
          <MiniSparkline values={spark as number[]} tone={alphaTone} />
          <div className="brain-list dense" style={{ marginTop: 12 }}>
            {(data.truth ?? []).slice(0, 6).map((line: string, index: number) => (
              <div key={`${index}-${line}`}>
                <StatusBadge label={index === 0 ? "truth" : "warning"} />
                <strong>{line}</strong>
              </div>
            ))}
          </div>
        </BloombergPanel>

        <BloombergPanel title="Evidence Gates" value={data.gates?.all_required_gates_passed ? "passed" : "blocked"} subtitle="No alpha claim is valid until required gates pass.">
          <div className="brain-list dense">
            {(data.gates?.rows ?? []).slice(0, 8).map((row: any) => (
              <div key={row.name}>
                <StatusBadge label={row.passed ? "passed" : "blocked"} />
                <strong>{row.name}</strong>
                <p>Observed {String(row.observed)} | Required {row.requirement}</p>
              </div>
            ))}
          </div>
        </BloombergPanel>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <EvidencePanel title="Historical" payload={data.historical} />
        <EvidencePanel title="Walk Forward" payload={data.walk_forward} />
        <EvidencePanel title="Paper Forward" payload={data.paper_forward} />
        <EvidencePanel title="Live Forward" payload={data.live_forward} />
      </section>

      <BloombergPanel title="Edge Map" value="best and weakest setup evidence" subtitle="The edge map is descriptive evidence, not a guarantee." dense>
        <div className="professional-grid-2">
          <EdgeList title="Best Setups" rows={data.edge_map?.best_setups ?? []} />
          <EdgeList title="Weakest Setups" rows={data.edge_map?.weakest_setups ?? []} />
        </div>
      </BloombergPanel>
    </>
  );
}

function EvidencePanel({ title, payload }: { title: string; payload: any }) {
  return (
    <BloombergPanel title={title} value={payload?.status ?? "missing"} subtitle={`sample ${payload?.sample_size ?? 0}`}>
      <div className="brain-list dense">
        <Fact label="Average excess" value={formatPct(payload?.average_excess_return)} />
        {(payload?.results ?? []).slice(0, 4).map((row: any) => (
          <Fact key={row.benchmark} label={row.benchmark} value={row.result_label} detail={`excess ${formatPct(row.excess_return)} | sample ${row.sample_size ?? 0} | ${row.statistical_confidence ?? "no confidence label"}`} />
        ))}
        {!(payload?.results ?? []).length && <Fact label="Insufficient evidence" value="No comparable rows stored for this evidence type." />}
      </div>
    </BloombergPanel>
  );
}

function EdgeList({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div className="brain-list dense">
      <h3>{title}</h3>
      {rows.slice(0, 6).map((row) => (
        <div key={row.entity}>
          <StatusBadge label={row.evidence_grade ?? "evidence"} />
          <strong>{row.entity}</strong>
          <p>Edge {formatNumber(row.edge_score)}/100 | win {formatPct(Number(row.win_rate) * 100)} | R {formatNumber(row.average_r)}</p>
          <span>sample {row.sample_size ?? 0}</span>
        </div>
      ))}
      {!rows.length && <Fact label="No edge rows" value="Edge map has not enough data yet." />}
    </div>
  );
}

function Fact({ label, value, detail }: { label: string; value: any; detail?: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? "n/a"}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}

function formatNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "n/a";
}

function formatPct(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : "n/a";
}

function evidenceTone(value: any): "positive" | "attention" | "negative" | "info" {
  const text = String(value ?? "").toLowerCase();
  if (text.includes("strong")) return "positive";
  if (text.includes("medium")) return "attention";
  if (text.includes("weak") || text.includes("low") || text.includes("insufficient")) return "negative";
  return "info";
}
