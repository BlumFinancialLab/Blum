"use client";

import { MarketNarrativePayload } from "@/lib/types";

export function MarketNarrative({ narrative }: { narrative: MarketNarrativePayload }) {
  return (
    <div className="panel narrative-panel">
      <div className="panel-head">
        <span>Market Narrative AI</span>
        <strong>{narrative.market_mood}</strong>
      </div>
      <h2>{narrative.dominant_theme.theme}</h2>
      <p>{narrative.synthesis}</p>
      <div className="narrative-grid">
        <div>
          <span>Beneficiary sectors</span>
          <strong>{narrative.beneficiary_sectors.slice(0, 4).join(" | ") || "forming"}</strong>
        </div>
        <div>
          <span>Macro risks</span>
          <strong>{narrative.macro_risks.join(" | ") || "neutral"}</strong>
        </div>
        <div>
          <span>Contrary checks</span>
          <strong>{narrative.contrary_signals.slice(0, 5).join(" | ") || "none flagged"}</strong>
        </div>
      </div>
      <div className="theme-list">
        {narrative.emerging_subthemes.slice(0, 5).map((theme) => (
          <div key={theme.theme}>
            <strong>{theme.theme}</strong>
            <span>{theme.headline_count} headlines | sentiment {theme.avg_sentiment.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

