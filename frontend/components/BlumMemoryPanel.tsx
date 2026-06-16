"use client";

import { BrainAssetMemory } from "@/lib/types";

export function BlumMemoryPanel({ memory }: { memory: BrainAssetMemory | null }) {
  if (!memory) {
    return (
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Blum Memory</span><strong>Loading</strong></div>
        <div className="empty-state">Historical memory is loading for this instrument.</div>
      </section>
    );
  }
  const similarity = memory.historical_similarity;
  return (
    <section className="panel blum-memory-panel" style={{ marginTop: 12 }}>
      <div className="panel-head">
        <span>Blum Memory</span>
        <strong>{memory.learning_state}</strong>
      </div>
      <p>{memory.blum_memory_summary}</p>
      <div className="brain-status-grid">
        <MemoryMetric label="Similar Cases" value={similarity.similar_cases_found} />
        <MemoryMetric label="Average Return" value={displayPercent(similarity.average_return)} />
        <MemoryMetric label="Success Rate" value={ratio(similarity.success_rate)} />
        <MemoryMetric label="Confidence Adjustment" value={`${Number(similarity.confidence_adjustment ?? 0).toFixed(1)} pts`} />
      </div>
      <div className="brain-drift info">
        <strong>Historical Similarity</strong>
        <span>{similarity.explanation}</span>
      </div>
      <div className="brain-two-col">
        <div>
          <h3>Why Confidence Changed</h3>
          <div className="learning-event-list">
            {(memory.why_confidence_changed.length ? memory.why_confidence_changed : ["No confidence change has been recorded yet."]).slice(0, 5).map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </div>
        <div>
          <h3>What Blum Learned</h3>
          <div className="learning-event-list">
            {memory.what_blum_learned.slice(0, 5).map((item) => <span key={item}>{item}</span>)}
          </div>
        </div>
      </div>
      <div className="brain-two-col">
        <div>
          <h3>Confidence Evolution</h3>
          <div className="confidence-timeline">
            {memory.confidence_evolution.slice(0, 8).map((item) => (
              <div key={item.id}>
                <strong>{Number(item.adjusted_confidence ?? 0).toFixed(1)}</strong>
                <span>{Number(item.adjustment ?? 0).toFixed(1)} pts | {item.signal_type ?? "signal"}</span>
              </div>
            ))}
            {!memory.confidence_evolution.length && <div className="empty-state compact">No confidence history yet.</div>}
          </div>
        </div>
        <div>
          <h3>Signal Outcome History</h3>
          <div className="brain-performance-list">
            {memory.signal_outcome_history.slice(0, 8).map((row) => (
              <div key={row.id}>
                <strong>{row.horizon_days}D {row.outcome}</strong>
                <span>{row.signal_type} | return {displayPercent(row.realized_return)} | data {row.data_quality_score.toFixed(0)}</span>
              </div>
            ))}
            {!memory.signal_outcome_history.length && <div className="empty-state compact">No evaluated signal horizons yet.</div>}
          </div>
        </div>
      </div>
      {!!memory.similar_historical_setups.length && (
        <div className="similar-case-strip">
          {memory.similar_historical_setups.slice(0, 6).map((item) => (
            <span key={item.id}>{item.outcome_summary?.historical_ticker ?? "Case"} | {Number(item.similarity_score ?? 0).toFixed(0)} similarity | {item.outcome_summary?.final_outcome ?? "pending"}</span>
          ))}
        </div>
      )}
      <p>{memory.governance_note}</p>
    </section>
  );
}

function MemoryMetric({ label, value }: { label: string; value: number | string }) {
  return <div className="brain-metric"><span>{label}</span><strong>{value}</strong></div>;
}

function displayPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "Pending";
  return `${Number(value).toFixed(2)}%`;
}

function ratio(value: number | null | undefined) {
  if (value === null || value === undefined) return "Pending";
  return `${Math.round(Number(value) * 100)}%`;
}
