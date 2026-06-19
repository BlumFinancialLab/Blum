"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Send, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { FinancialChatResponse } from "@/lib/types";
import { assetPath } from "@/lib/routes";
import { BloombergPanel, ConfidenceMeter, MetricCard, RiskIndicator, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";

const STARTER_PROMPTS = [
  "Analizza NVIDIA con approccio tecnico e fondamentale.",
  "Trova ETF AI interessanti con rischio definibile.",
  "Confronta S&P 500 vs Nasdaq.",
  "Dove potrebbe entrare un trader momentum?",
  "Quali titoli stanno mostrando forza relativa?",
  "Quali narrative stanno accelerando?",
  "What could the market be missing today?",
  "Compare Nvidia, AMD and Broadcom."
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
  const [language, setLanguage] = useState("auto");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Sono BLUM Chat. Fai una domanda come faresti a un analista buy-side: io recupero contesto BLUM, segnali, news, narrativa, tecnica, fondamentali, memoria storica e restituisco una risposta strutturata. Analisi informativa, non consulenza finanziaria.",
    },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [context, setContext] = useState<Record<string, any> | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    api.financialChatContext().then(setContext).catch(() => setContext(null));
  }, []);

  const latestResponse = [...messages].reverse().find((message) => message.response)?.response;
  const candidates = latestResponse?.candidate_opportunities ?? [];
  const mentionedAssets = latestResponse?.asset_context ?? [];
  const sources = latestResponse?.sources_used ?? [];
  const coverage = latestResponse?.context_coverage ?? {};
  const sniper = latestResponse?.answer.market_sniper_mode ?? {};

  const contextStats = useMemo(() => {
    const marketContext = latestResponse?.market_context ?? {};
    const narrative = marketContext.narrative as any;
    const sentiment = marketContext.market_sentiment as any;
    return {
      dominantTheme: narrative?.dominant_theme?.theme ?? context?.dominant_narrative?.theme ?? "Waiting",
      marketMood: narrative?.market_mood ?? context?.market_mood ?? "Waiting",
      articleCount: sentiment?.article_count ?? context?.market_sentiment?.article_count ?? 0,
      semanticHits: latestResponse?.semantic_evidence?.length ?? 0,
      memoryHits: latestResponse?.training_memory?.length ?? 0,
      dataQuality: latestResponse?.answer.data_quality?.label ?? "Pending",
    };
  }, [context, latestResponse]);

  const submit = async (event?: FormEvent, forcedPrompt?: string) => {
    event?.preventDefault();
    const question = (forcedPrompt ?? input).trim();
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
        language,
        session_id: sessionId,
        include_semantic_search: true,
      });
      setSessionId(response.session_id);
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
        eyebrow="BLUM Chat"
        title="Financial intelligence conversation."
        subtitle="Multilingual market assistant connected to Blum signals, narratives, technical analysis, fundamentals, memory, backtests and evidence controls."
        statusItems={[
          { label: "Mode", value: latestResponse?.intent ?? "RAG analyst", tone: "info" },
          { label: "Language", value: latestResponse?.language ?? language },
          { label: "Risk", value: riskProfile },
          { label: "Evidence", value: `${contextStats.articleCount} news`, tone: latestResponse ? "positive" : "attention" },
        ]}
      />

      <section className="chatgpt-shell blum-chat-shell">
        <div className="chatgpt-main">
          <div className="chat-thread">
            {messages.map((message) => (
              <ChatBubble message={message} key={message.id} />
            ))}
            {busy && (
              <div className="chat-bubble assistant">
                <div className="chat-avatar">B</div>
                <div className="chat-message-card">
                  <span className="chat-role">BLUM is composing</span>
                  <p>Retrieving assets, technicals, fundamentals, sentiment, narrative, memory, contradictions and risk controls...</p>
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
              <select className="input" value={language} onChange={(event) => setLanguage(event.target.value)} aria-label="Language">
                <option value="auto">Auto language</option>
                <option value="it">Italiano</option>
                <option value="en">English</option>
                <option value="de">Deutsch</option>
                <option value="fr">Francais</option>
                <option value="es">Espanol</option>
              </select>
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
                placeholder="Ask BLUM to analyze an asset, compare setups, find selective opportunities, or plan a monitored technical scenario..."
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
          <BloombergPanel title="Conversation Context" value={contextStats.marketMood}>
            <div className="professional-grid-2">
              <MetricCard label="Dominant Theme" value={contextStats.dominantTheme} />
              <MetricCard label="Data Quality" value={contextStats.dataQuality} />
              <MetricCard label="Semantic Hits" value={contextStats.semanticHits} />
              <MetricCard label="Memory Hits" value={contextStats.memoryHits} />
            </div>
          </BloombergPanel>

          <BloombergPanel title="Assets Mentioned" value={`${mentionedAssets.length} names`}>
            <div className="chat-candidate-stack">
              {mentionedAssets.length === 0 && <div className="terminal-empty compact">Ask about an asset, ETF, sector or market to build context.</div>}
              {mentionedAssets.slice(0, 8).map((asset: any) => <AssetContextPill asset={asset} key={asset.ticker} />)}
            </div>
          </BloombergPanel>

          <BloombergPanel title="Candidate Queue" value={`${candidates.length} names`}>
            <div className="chat-candidate-stack">
              {candidates.length === 0 && <div className="terminal-empty compact">The assistant will populate a ranked queue from real BLUM evidence.</div>}
              {candidates.slice(0, 8).map((candidate, index) => <CompactCandidate candidate={candidate} rank={index + 1} key={`${candidate.ticker ?? "candidate"}-${index}`} />)}
            </div>
          </BloombergPanel>

          {sniper?.asset && (
            <BloombergPanel title="Market Sniper Mode" value={sniper.confidence ?? "Selective"}>
              <div className="sniper-box">
                <strong>{sniper.asset} | {sniper.setup_type}</strong>
                <span>Zone: {sniper.entry_zone_informational}</span>
                <span>Invalidation: {String(sniper.invalidation ?? "n/a")}</span>
                <span>Target zone: {String(sniper.target_zone_informational ?? "n/a")}</span>
                <span>{sniper.what_could_go_wrong}</span>
              </div>
            </BloombergPanel>
          )}

          <BloombergPanel title="Sources Used" value={`${sources.length} layers`}>
            <div className="source-badge-grid">
              {sources.map((source: any) => <SourceBadge source={source} key={`${source.name}-${source.type}`} />)}
            </div>
            <div className="context-coverage">
              <span>Price {coverage.assets_with_price ?? 0}/{coverage.assets_detected ?? 0}</span>
              <span>Technicals {coverage.assets_with_technical_analysis ?? 0}</span>
              <span>Fundamentals {coverage.assets_with_fundamentals ?? 0}</span>
              <span>News {coverage.assets_with_news ?? 0}</span>
            </div>
          </BloombergPanel>

          <BloombergPanel title="Guardrails" value="Research only">
            <div className="chat-guardrail-list">
              <span>No direct buy/sell instruction.</span>
              <span>No guaranteed outcome or market-beating claim.</span>
              <span>Missing data is declared.</span>
              <span>Levels are informational and probabilistic.</span>
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
        <span className="chat-role">{message.role === "assistant" ? "BLUM Financial Brain" : "You"}</span>
        {response?.answer.standard_sections ? <StructuredAnswer response={response} /> : <RichAnswer text={message.content} />}
        {response && <ResponseEvidence response={response} />}
      </div>
    </div>
  );
}

function StructuredAnswer({ response }: { response: FinancialChatResponse }) {
  return (
    <div className="structured-answer">
      {response.answer.standard_sections?.map((section) => (
        <section className="structured-section" key={section.key}>
          <h3>{section.title}</h3>
          <ul>
            {section.bullets.slice(0, 8).map((bullet, index) => <li key={`${section.key}-${index}`}>{bullet}</li>)}
          </ul>
        </section>
      ))}
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
      {rows.slice(0, 6).map((row, index) => <span key={`${title}-${index}`}>{row}</span>)}
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

function AssetContextPill({ asset }: { asset: Record<string, any> }) {
  const snapshot = asset.market_snapshot ?? {};
  return (
    <div className="asset-context-pill">
      <div>
        <Link href={assetPath(String(asset.ticker))}>{asset.ticker}</Link>
        <p>{asset.name} | {asset.sector}</p>
      </div>
      <strong>{snapshot.price ? `${Number(snapshot.price).toFixed(2)} ${snapshot.currency ?? ""}` : "No price"}</strong>
      <span>{snapshot.data_status ?? "unknown"}</span>
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
      <ConfidenceMeter value={candidate.technical_score} label="Tech" />
    </div>
  );
}

function SourceBadge({ source }: { source: Record<string, any> }) {
  return (
    <div className="source-badge">
      <Sparkles size={13} />
      <div>
        <strong>{source.name}</strong>
        <span>{source.type} | coverage {String(source.coverage ?? 0)}</span>
      </div>
    </div>
  );
}

