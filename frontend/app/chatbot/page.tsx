"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { FinancialChatResponse } from "@/lib/types";
import { assetPath } from "@/lib/routes";
import { BloombergPanel, ConfidenceMeter, MetricCard, RiskIndicator, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";

const STARTER_PROMPTS = [
  "What should I monitor today across US and European equities, and where is sentiment diverging from price?",
  "Find statistically interesting opportunities in FTSE MIB, DAX and US mega-cap stocks with balanced risk.",
  "Which narratives look early, which look crowded, and which assets have the strongest evidence stack?",
  "Compare the top opportunities by risk/reward and show bull, base and bear scenarios."
];

export default function FinancialChatbotPage() {
  const [message, setMessage] = useState(STARTER_PROMPTS[0]);
  const [horizon, setHorizon] = useState("short and medium term");
  const [riskProfile, setRiskProfile] = useState("balanced");
  const [response, setResponse] = useState<FinancialChatResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const candidates = response?.candidate_opportunities ?? [];
  const topCandidate = candidates[0];
  const contextStats = useMemo(() => {
    const marketContext = response?.market_context ?? {};
    const narrative = marketContext.narrative as any;
    const sentiment = marketContext.market_sentiment as any;
    return {
      dominantTheme: narrative?.dominant_theme?.theme ?? "Evidence pending",
      marketMood: narrative?.market_mood ?? "Context pending",
      articleCount: sentiment?.article_count ?? narrative?.dominant_theme?.headline_count ?? 0,
      semanticHits: response?.semantic_evidence?.length ?? 0,
    };
  }, [response]);

  const submit = async () => {
    if (message.trim().length < 3) return;
    setBusy(true);
    setError("");
    try {
      setResponse(await api.financialChat({
        message,
        horizon,
        risk_profile: riskProfile,
        include_semantic_search: true
      }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <TerminalHeader
        eyebrow="Blum Financial Chat"
        title="Evidence-bound market analyst."
        subtitle="Ask Blum to reason across price history, signals, sentiment, news, narratives, sector context and stored learning memory. Outputs remain research-only and never direct financial advice."
        statusItems={[
          { label: "Mode", value: response?.mode?.replaceAll("_", " ") ?? "Analyst standby", tone: "info" },
          { label: "Candidates", value: String(candidates.length), tone: candidates.length ? "positive" : "attention" },
          { label: "Semantic hits", value: String(contextStats.semanticHits), tone: contextStats.semanticHits ? "info" : "attention" },
          { label: "Risk profile", value: riskProfile }
        ]}
      />

      <section className="chat-command-layout">
        <BloombergPanel title="Research Prompt" value={busy ? "Thinking" : "Ready"} subtitle="Ask for opportunities, contradictions, scenarios, market narratives or single-asset research">
          <div className="chat-prompt-grid">
            <textarea
              className="input chat-textarea"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              aria-label="Financial research prompt"
            />
            <div className="chat-controls">
              <label>
                Horizon
                <select className="input" value={horizon} onChange={(event) => setHorizon(event.target.value)}>
                  <option>intraday and short term</option>
                  <option>short and medium term</option>
                  <option>medium and long term</option>
                  <option>multi-horizon</option>
                </select>
              </label>
              <label>
                Risk profile
                <select className="input" value={riskProfile} onChange={(event) => setRiskProfile(event.target.value)}>
                  <option>balanced</option>
                  <option>conservative</option>
                  <option>opportunistic</option>
                  <option>high volatility tolerant</option>
                </select>
              </label>
              <button className="button primary" onClick={submit} disabled={busy || message.trim().length < 3}>
                {busy ? "Building analysis..." : "Ask Blum"}
              </button>
            </div>
          </div>
          <div className="prompt-chip-row">
            {STARTER_PROMPTS.map((prompt) => (
              <button className="prompt-chip" key={prompt} onClick={() => setMessage(prompt)}>{prompt}</button>
            ))}
          </div>
          {error && <div className="terminal-empty compact" style={{ marginTop: 12 }}>Chat endpoint warning: {error}</div>}
        </BloombergPanel>

        <BloombergPanel title="Operating Guardrails" value="Research only" subtitle="Decision support, not a recommendation engine">
          <div className="chat-guardrail-list">
            <span>Observed evidence is separated from inference.</span>
            <span>Every answer must show risks and contradiction points.</span>
            <span>No guarantee, no direct buy/sell instruction, no automated trading.</span>
            <span>Confidence is reduced when coverage, sources or price evidence are weak.</span>
          </div>
        </BloombergPanel>
      </section>

      {!response && (
        <BloombergPanel title="Analyst Console" value="Waiting for prompt" className="radar-core-panel">
          <div className="terminal-empty">
            Ask a market question to generate an evidence-bound analyst note using Blum radar, narratives, sentiment, technical context and historical learning memory.
          </div>
        </BloombergPanel>
      )}

      {response && (
        <>
          <section className="terminal-command-grid" style={{ marginTop: 12 }}>
            <MetricCard label="Dominant Theme" value={contextStats.dominantTheme} subvalue={contextStats.marketMood} tone="attention" />
            <MetricCard label="News Evidence" value={contextStats.articleCount} subvalue="Articles in retrieved context" tone="info" />
            <MetricCard label="Top Candidate" value={topCandidate?.ticker ?? "n/a"} subvalue={topCandidate?.classification ?? "No ranked candidate"} tone={topCandidate ? "positive" : "attention"} />
            <MetricCard label="Generated" value={formatTime(response.generated_at)} subvalue="Autonomous evidence snapshot" />
          </section>

          <BloombergPanel title="Executive Analyst View" value="Blum thesis" className="radar-core-panel">
            <div className="chat-answer-grid">
              <div className="chat-thesis-block">
                <span>Executive view</span>
                <p>{response.answer.executive_view}</p>
              </div>
              <div className="chat-thesis-block">
                <span>Opportunity lens</span>
                <p>{response.answer.opportunity_lens}</p>
              </div>
              <div className="chat-thesis-block full">
                <span>Direct answer</span>
                <p>{response.answer.answer_to_user}</p>
              </div>
            </div>
          </BloombergPanel>

          <section className="professional-grid-2" style={{ marginTop: 12 }}>
            <EvidencePanel title="Supporting Evidence" rows={response.answer.supporting_evidence} tone="positive" />
            <EvidencePanel title="Contradicting Evidence" rows={response.answer.contradicting_evidence} tone="negative" />
          </section>

          <section className="professional-grid-3" style={{ marginTop: 12 }}>
            <ScenarioPanel label="Bull Case" text={response.answer.bull_case} tone="positive" />
            <ScenarioPanel label="Base Case" text={response.answer.base_case} tone="attention" />
            <ScenarioPanel label="Bear Case" text={response.answer.bear_case} tone="negative" />
          </section>

          <BloombergPanel title="Candidate Opportunity Queue" value={`${candidates.length} ranked`} subtitle="Research queue generated from stored Blum opportunity radar and requested context" className="radar-core-panel">
            <div className="chat-candidate-table">
              {candidates.length === 0 && <div className="terminal-empty compact">No candidate opportunity has enough evidence in the retrieved context.</div>}
              {candidates.map((candidate, index) => <CandidateRow candidate={candidate} rank={index + 1} key={`${candidate.ticker ?? "candidate"}-${index}`} />)}
            </div>
          </BloombergPanel>

          <section className="professional-grid-2" style={{ marginTop: 12 }}>
            <BloombergPanel title="Risk / Reward Interpretation" value={riskProfile}>
              <p>{response.answer.risk_reward_view}</p>
              <div className="chat-monitor-list">
                {response.answer.what_to_monitor.map((item) => <span key={item}>{item}</span>)}
              </div>
            </BloombergPanel>
            <BloombergPanel title="Intellectual Honesty" value="Calibration">
              <p>{response.answer.intellectual_honesty}</p>
              <div className="chat-monitor-list">
                {response.governance.map((item) => <span key={item}>{item}</span>)}
              </div>
            </BloombergPanel>
          </section>

          <section className="professional-grid-2" style={{ marginTop: 12 }}>
            <BloombergPanel title="Semantic Evidence" value={`${response.semantic_evidence.length} hits`}>
              <div className="news-list">
                {response.semantic_evidence.length === 0 && <div className="terminal-empty compact">No semantic evidence was retrieved for this prompt.</div>}
                {response.semantic_evidence.slice(0, 8).map((hit, index) => {
                  const article = hit.article ?? {};
                  return (
                    <a className="news-item" href={article.url ?? "#"} target="_blank" rel="noreferrer" key={`${article.id ?? article.url ?? "semantic"}-${index}`}>
                      <strong>{article.title ?? "Untitled evidence"}</strong>
                      <span>Similarity {Number(hit.score ?? 0).toFixed(3)} | {article.source ?? "unknown source"}</span>
                    </a>
                  );
                })}
              </div>
            </BloombergPanel>
            <BloombergPanel title="Suggested Follow-ups" value="Next questions">
              <div className="chat-monitor-list">
                {response.suggested_followups.map((item) => (
                  <button className="prompt-chip wide" key={item} onClick={() => setMessage(item)}>{item}</button>
                ))}
              </div>
              <p>{response.disclaimer}</p>
            </BloombergPanel>
          </section>
        </>
      )}
    </>
  );
}

function EvidencePanel({ title, rows, tone }: { title: string; rows: string[]; tone: "positive" | "negative" }) {
  return (
    <BloombergPanel title={title} value={`${rows.length} points`}>
      <div className={`chat-evidence-list tone-${tone}`}>
        {rows.length === 0 && <span>No material evidence retrieved.</span>}
        {rows.map((row) => <span key={row}>{row}</span>)}
      </div>
    </BloombergPanel>
  );
}

function ScenarioPanel({ label, text, tone }: { label: string; text: string; tone: "positive" | "negative" | "attention" }) {
  return (
    <div className={`chat-scenario-card tone-${tone}`}>
      <span>{label}</span>
      <p>{text}</p>
    </div>
  );
}

function CandidateRow({ candidate, rank }: { candidate: Record<string, any>; rank: number }) {
  const ticker = String(candidate.ticker ?? "");
  return (
    <div className="chat-candidate-row">
      <strong>#{rank}</strong>
      <div>
        {ticker ? <Link href={assetPath(ticker)}>{ticker}</Link> : <span>n/a</span>}
        <p>{candidate.name ?? "No asset name"} | {candidate.sector ?? "sector pending"}</p>
      </div>
      <ScoreBadge value={candidate.opportunity_score} label="opp" />
      <ScoreBadge value={candidate.momentum_score} label="mom" />
      <ScoreBadge value={candidate.sentiment_score} label="sent" />
      <ConfidenceMeter value={candidate.news_score} label="News" />
      <RiskIndicator risk={candidate.risk_level ?? "Not rated"} score={candidate.risk_score} />
      <span className="terminal-signal">{candidate.classification ?? "Under observation"}</span>
      <p>{candidate.why_today ?? "Candidate selected from current evidence."}</p>
    </div>
  );
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
