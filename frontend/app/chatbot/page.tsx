"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Send } from "lucide-react";
import { api } from "@/lib/api";
import { FinancialChatResponse } from "@/lib/types";
import { assetPath } from "@/lib/routes";
import { BloombergPanel, ConfidenceMeter, MetricCard, RiskIndicator, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";

const STARTER_PROMPTS = [
  "What should I monitor today across US and European equities?",
  "Build a research plan for FTSE MIB and DAX opportunities.",
  "Where is sentiment diverging from price action?",
  "Create a bull/base/bear scenario plan for the strongest setup."
];

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: FinancialChatResponse;
};

export default function FinancialChatbotPage() {
  const [input, setInput] = useState("");
  const [horizon, setHorizon] = useState("short and medium term");
  const [riskProfile, setRiskProfile] = useState("balanced");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Ask me a market question. I will answer like an evidence-bound financial analyst: thesis, supporting evidence, contradictions, scenario planning, risk controls and what to monitor next. I do not provide financial advice or guarantees.",
    },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const latestResponse = [...messages].reverse().find((message) => message.response)?.response;
  const candidates = latestResponse?.candidate_opportunities ?? [];
  const contextStats = useMemo(() => {
    const marketContext = latestResponse?.market_context ?? {};
    const narrative = marketContext.narrative as any;
    const sentiment = marketContext.market_sentiment as any;
    return {
      dominantTheme: narrative?.dominant_theme?.theme ?? "No active answer yet",
      marketMood: narrative?.market_mood ?? "Waiting",
      articleCount: sentiment?.article_count ?? 0,
      semanticHits: latestResponse?.semantic_evidence?.length ?? 0,
    };
  }, [latestResponse]);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const question = input.trim();
    if (question.length < 3 || busy) return;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: question };
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setError("");
    setBusy(true);
    try {
      const response = await api.financialChat({
        message: question,
        horizon,
        risk_profile: riskProfile,
        include_semantic_search: true,
      });
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer.composed_response ?? response.answer.answer_to_user,
          response,
        },
      ]);
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `I could not complete the analysis because the backend returned: ${message}`,
        },
      ]);
    } finally {
      setBusy(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  };

  const usePrompt = (prompt: string) => {
    setInput(prompt);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  return (
    <>
      <TerminalHeader
        eyebrow="Blum Financial Chat"
        title="AI market analyst conversation."
        subtitle="A ChatGPT-style research interface for thesis generation, scenario planning, signal critique and evidence-bound financial reasoning."
        statusItems={[
          { label: "Mode", value: "Conversational analyst", tone: "info" },
          { label: "Risk frame", value: riskProfile },
          { label: "Horizon", value: horizon },
          { label: "Evidence", value: latestResponse ? `${contextStats.articleCount} news` : "waiting", tone: latestResponse ? "positive" : "attention" },
        ]}
      />

      <section className="chatgpt-shell">
        <div className="chatgpt-main">
          <div className="chat-thread">
            {messages.map((message) => (
              <ChatBubble message={message} key={message.id} />
            ))}
            {busy && (
              <div className="chat-bubble assistant">
                <div className="chat-avatar">B</div>
                <div className="chat-message-card">
                  <span className="chat-role">Blum is reasoning</span>
                  <p>Retrieving market context, candidate opportunities, semantic evidence, contradictions and scenario plan...</p>
                </div>
              </div>
            )}
          </div>

          <div className="prompt-chip-row chat-starters">
            {STARTER_PROMPTS.map((prompt) => (
              <button className="prompt-chip" onClick={() => usePrompt(prompt)} key={prompt}>{prompt}</button>
            ))}
          </div>

          <form className="chat-composer" onSubmit={submit}>
            <div className="chat-composer-controls">
              <select className="input" value={horizon} onChange={(event) => setHorizon(event.target.value)} aria-label="Analysis horizon">
                <option>intraday and short term</option>
                <option>short and medium term</option>
                <option>medium and long term</option>
                <option>multi-horizon</option>
              </select>
              <select className="input" value={riskProfile} onChange={(event) => setRiskProfile(event.target.value)} aria-label="Risk profile">
                <option>balanced</option>
                <option>conservative</option>
                <option>opportunistic</option>
                <option>high volatility tolerant</option>
              </select>
            </div>
            <div className="chat-input-row">
              <textarea
                ref={inputRef}
                className="input chat-input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask Blum to build a thesis, compare assets, plan a monitored setup, or challenge a market narrative..."
                rows={2}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit();
                  }
                }}
              />
              <button className="button primary chat-send-button" disabled={busy || input.trim().length < 3} type="submit" aria-label="Send">
                <Send size={17} />
              </button>
            </div>
            {error && <div className="terminal-empty compact">Chat endpoint warning: {error}</div>}
          </form>
        </div>

        <aside className="chat-context-rail">
          <BloombergPanel title="Current Context" value={contextStats.marketMood}>
            <div className="professional-grid-2">
              <MetricCard label="Dominant Theme" value={contextStats.dominantTheme} />
              <MetricCard label="Semantic Hits" value={contextStats.semanticHits} />
              <MetricCard label="News Evidence" value={contextStats.articleCount} />
              <MetricCard label="Candidates" value={candidates.length} />
            </div>
          </BloombergPanel>
          <BloombergPanel title="Candidate Queue" value={`${candidates.length} names`}>
            <div className="chat-candidate-stack">
              {candidates.length === 0 && <div className="terminal-empty compact">Ask a question to build a live research queue.</div>}
              {candidates.slice(0, 8).map((candidate, index) => <CompactCandidate candidate={candidate} rank={index + 1} key={`${candidate.ticker ?? "candidate"}-${index}`} />)}
            </div>
          </BloombergPanel>
          <BloombergPanel title="Guardrails" value="Research only">
            <div className="chat-guardrail-list">
              <span>No direct buy/sell instruction.</span>
              <span>No promise of future performance.</span>
              <span>Always show contradiction and invalidation logic.</span>
              <span>Planning is hypothetical and evidence-bound.</span>
            </div>
          </BloombergPanel>
        </aside>
      </section>
    </>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const response = message.response;
  return (
    <div className={`chat-bubble ${message.role}`}>
      <div className="chat-avatar">{message.role === "assistant" ? "B" : "U"}</div>
      <div className="chat-message-card">
        <span className="chat-role">{message.role === "assistant" ? "Blum Financial Brain" : "You"}</span>
        <RichAnswer text={message.content} />
        {response && <ResponseEvidence response={response} />}
      </div>
    </div>
  );
}

function RichAnswer({ text }: { text: string }) {
  return (
    <div className="rich-answer">
      {text.split("\n").map((line, index) => {
        if (!line.trim()) return <br key={`br-${index}`} />;
        if (line.startsWith("- ")) return <li key={line + index}>{line.slice(2)}</li>;
        if (line.endsWith(":")) return <h3 key={line + index}>{line}</h3>;
        return <p key={line + index}>{line}</p>;
      })}
    </div>
  );
}

function ResponseEvidence({ response }: { response: FinancialChatResponse }) {
  return (
    <div className="chat-response-evidence">
      <div className="chat-evidence-columns">
        <EvidenceList title="Supporting Evidence" rows={response.answer.supporting_evidence} />
        <EvidenceList title="Contradictions" rows={response.answer.contradicting_evidence} />
      </div>
      <div className="chat-evidence-columns">
        <EvidenceList title="Research Plan" rows={response.answer.research_plan ?? response.answer.what_to_monitor} />
        <EvidenceList title="What Market May Miss" rows={response.answer.market_may_be_missing ?? []} />
      </div>
      <div className="scenario-mini-grid">
        <ScenarioMini title="Bull" text={response.answer.bull_case} />
        <ScenarioMini title="Base" text={response.answer.base_case} />
        <ScenarioMini title="Bear" text={response.answer.bear_case} />
      </div>
      <div className="news-list">
        {response.semantic_evidence.slice(0, 4).map((hit, index) => {
          const article = hit.article ?? {};
          return (
            <a className="news-item" href={article.url ?? "#"} target="_blank" rel="noreferrer" key={`${article.id ?? article.url ?? "hit"}-${index}`}>
              <strong>{article.title ?? "Untitled evidence"}</strong>
              <span>Similarity {Number(hit.score ?? 0).toFixed(3)} | {article.source ?? "unknown source"}</span>
            </a>
          );
        })}
      </div>
      <p className="chat-disclaimer">{response.disclaimer}</p>
    </div>
  );
}

function EvidenceList({ title, rows }: { title: string; rows: string[] }) {
  return (
    <div className="chat-evidence-list compact-list">
      <strong>{title}</strong>
      {rows.length === 0 && <span>No material evidence retrieved.</span>}
      {rows.slice(0, 6).map((row) => <span key={row}>{row}</span>)}
    </div>
  );
}

function ScenarioMini({ title, text }: { title: string; text: string }) {
  return (
    <div className="chat-scenario-card">
      <span>{title}</span>
      <p>{text}</p>
    </div>
  );
}

function CompactCandidate({ candidate, rank }: { candidate: Record<string, any>; rank: number }) {
  const ticker = String(candidate.ticker ?? "");
  return (
    <div className="compact-candidate">
      <strong>#{rank}</strong>
      <div>
        {ticker ? <Link href={assetPath(ticker)}>{ticker}</Link> : <span>n/a</span>}
        <p>{candidate.name ?? "Asset"} | {candidate.sector ?? "sector pending"}</p>
      </div>
      <ScoreBadge value={candidate.opportunity_score} label="opp" />
      <RiskIndicator risk={candidate.risk_level ?? "Not rated"} score={candidate.risk_score} />
      <ConfidenceMeter value={candidate.news_score} label="News" />
    </div>
  );
}
