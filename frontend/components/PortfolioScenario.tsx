"use client";

import { PortfolioScenarioPayload } from "@/lib/types";

export function PortfolioScenario({ scenario }: { scenario: PortfolioScenarioPayload }) {
  return (
    <div className="panel portfolio-panel">
      <div className="panel-head">
        <span>AI Portfolio Scenario</span>
        <strong>{scenario.risk_profile}</strong>
      </div>
      <div className="allocation-list">
        {scenario.allocation.map((item) => (
          <div key={item.bucket}>
            <span style={{ width: `${Math.max(4, item.weight)}%` }} />
            <strong>{item.weight}%</strong>
            <p>{item.bucket}</p>
            <em>{item.leaders.join(" | ") || "reserve"}</em>
          </div>
        ))}
      </div>
      <p>{scenario.time_horizon}</p>
      <div className="tag-row">
        {scenario.monitor.slice(0, 5).map((item) => <span key={item}>{item}</span>)}
      </div>
      <small>{scenario.disclaimer}</small>
    </div>
  );
}

