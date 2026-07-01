from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.agents.contracts import AgentBoundary, AgentEvidence, AgentName, EngineAgent
from app.engine.agents.core_agents import (
    AlphaAgent,
    DatasetAgent,
    DecisionAgent,
    FundamentalAgent,
    LearningAgent,
    MarketAgent,
    MemoryAgent,
    NewsAgent,
    PaperTradingAgent,
    PatternAgent,
    PortfolioAgent,
    ResearchAgent,
    RiskAgent,
    TechnicalAgent,
    ValidationAgent,
)


AGENT_BOUNDARIES: tuple[AgentBoundary, ...] = (
    AgentBoundary(
        name="market_agent",
        display_name="Market Agent",
        responsibility="Own market coverage evidence: asset universe, price history and macro snapshot coverage.",
        consumes=["assets", "price_history", "macro_snapshots"],
        publishes=["market_coverage"],
        implemented=True,
        implementation_note="Reads stored market coverage; does not fetch markets or hydrate data.",
    ),
    AgentBoundary(
        name="news_agent",
        display_name="News Agent",
        responsibility="Own news, sentiment and narrative coverage evidence.",
        consumes=["news_articles", "sentiment_analysis", "theme_clusters"],
        publishes=["news_sentiment_coverage"],
        implemented=True,
        implementation_note="Reads persisted articles, sentiment rows and narrative clusters.",
    ),
    AgentBoundary(
        name="technical_agent",
        display_name="Technical Agent",
        responsibility="Own technical indicator and signal snapshot evidence.",
        consumes=["technical_indicators", "signal_snapshots"],
        publishes=["technical_signal_coverage"],
        implemented=True,
        implementation_note="Reads persisted technical rows and signal snapshots; no recalculation on collect.",
    ),
    AgentBoundary(
        name="fundamental_agent",
        display_name="Fundamental Agent",
        responsibility="Own fundamental, business quality and fundamental-alpha evidence.",
        consumes=["fundamental_snapshots", "business_quality_scores", "fundamental_alpha_patterns"],
        publishes=["fundamental_quality_coverage"],
        implemented=True,
        implementation_note="Reads stored fundamental and business-quality evidence.",
    ),
    AgentBoundary(
        name="pattern_agent",
        display_name="Pattern Agent",
        responsibility="Own historical pattern and setup-memory evidence.",
        consumes=["historical_similarity_cases", "trade_learning_evidence"],
        publishes=["pattern_memory"],
        implemented=True,
        implementation_note="Reads historical similarity cases and trade-learning lessons.",
    ),
    AgentBoundary(
        name="decision_agent",
        display_name="Decision Agent",
        responsibility="Own final decision-quality evidence from the trader brain read model.",
        consumes=["brain_score", "decision_superiority", "learning_memory"],
        publishes=["decision_quality"],
        implemented=True,
        implementation_note="Uses the Engine Trader Brain read model; does not create decisions.",
    ),
    AgentBoundary(
        name="risk_agent",
        display_name="Risk Agent",
        responsibility="Own risk gates, noise flags and capital risk evidence.",
        consumes=["alpha_gate_snapshots", "reasoning_noise_flags", "capital_allocation_snapshots"],
        publishes=["risk_evidence"],
        implemented=True,
        implementation_note="Reads risk gates and noise flags; does not alter filters or weights.",
    ),
    AgentBoundary(
        name="portfolio_agent",
        display_name="Portfolio Agent",
        responsibility="Own portfolio quality, portfolio alpha and capital allocation evidence.",
        consumes=["portfolio_quality_scores", "portfolio_alpha_scores", "capital_allocation_snapshots"],
        publishes=["portfolio_intelligence"],
        implemented=True,
        implementation_note="Reads portfolio intelligence snapshots and scores.",
    ),
    AgentBoundary(
        name="paper_trading_agent",
        display_name="Paper Trading Agent",
        responsibility="Own paper-only trading decisions and completed outcome evidence.",
        consumes=["paper_trading_read_model", "trade_outcomes"],
        publishes=["paper_trading_evidence"],
        implemented=True,
        implementation_note="Uses the paper-trading read model; never connects to brokers.",
    ),
    AgentBoundary(
        name="learning_agent",
        display_name="Learning Agent",
        responsibility="Own learning-cycle progress, validation and memory-update evidence.",
        consumes=["learning_runs", "prediction_outcomes", "strategy_memory"],
        publishes=["learning_progress"],
        implemented=True,
        implementation_note="Uses the Training Ground read model; does not start a learning cycle.",
    ),
    AgentBoundary(
        name="research_agent",
        display_name="Research Agent",
        responsibility="Own research priorities, recovery actions and next-learning focus evidence.",
        consumes=["learning_focus_priorities", "alpha_recovery_actions"],
        publishes=["research_priorities"],
        implemented=True,
        implementation_note="Reads active/proposed research priorities and recovery actions.",
    ),
    AgentBoundary(
        name="memory_agent",
        display_name="Memory Agent",
        responsibility="Own durable learning memory and meta-cognition event evidence.",
        consumes=["trade_learning_evidence", "meta_cognition_events", "learning_runs"],
        publishes=["memory_evidence"],
        implemented=True,
        implementation_note="Reads accumulated memory; does not mutate lessons.",
    ),
    AgentBoundary(
        name="alpha_agent",
        display_name="Alpha Agent",
        responsibility="Own alpha readiness, benchmark truth and evidence-grade output.",
        consumes=["alpha_readiness", "benchmark_comparisons", "truth_panel"],
        publishes=["alpha_validation"],
        implemented=True,
        implementation_note="Uses the Alpha read model and truth-first warnings.",
    ),
    AgentBoundary(
        name="validation_agent",
        display_name="Validation Agent",
        responsibility="Own benchmark, truth-panel and reliability warning evidence.",
        consumes=["learning_summary", "benchmark_comparisons", "dashboard_snapshots"],
        publishes=["validation_truth"],
        implemented=True,
        implementation_note="Reads lightweight summary and benchmark rows; no recomputation.",
    ),
    AgentBoundary(
        name="dataset_agent",
        display_name="Dataset Agent",
        responsibility="Own BLUM Analyst dataset readiness and export-manifest evidence.",
        consumes=["training_manifest", "analyst_dataset_contract"],
        publishes=["analyst_dataset_readiness"],
        implemented=True,
        implementation_note="Reports dataset readiness; does not start model training.",
    ),
)


def agent_boundaries() -> list[dict]:
    return [boundary.to_dict() for boundary in AGENT_BOUNDARIES]


def agent_registry() -> dict[AgentName, EngineAgent]:
    agents: list[EngineAgent] = [
        MarketAgent(),
        NewsAgent(),
        TechnicalAgent(),
        FundamentalAgent(),
        PatternAgent(),
        DecisionAgent(),
        RiskAgent(),
        PortfolioAgent(),
        PaperTradingAgent(),
        LearningAgent(),
        ResearchAgent(),
        MemoryAgent(),
        AlphaAgent(),
        ValidationAgent(),
        DatasetAgent(),
    ]
    return {agent.name: agent for agent in agents}  # type: ignore[misc]


def collect_agent_evidence(db: Session, *, names: list[str] | None = None, limit: int = 8) -> dict:
    registry = agent_registry()
    selected_names = names or list(registry.keys())
    evidence: list[AgentEvidence] = []
    warnings: list[str] = []

    for raw_name in selected_names:
        if raw_name not in registry:
            warnings.append(f"Agent '{raw_name}' is not implemented or not registered.")
            continue
        evidence.append(registry[raw_name].collect(db, limit=limit))

    return {
        "status": "ready" if evidence else "no_agent_evidence",
        "agent_count": len(AGENT_BOUNDARIES),
        "implemented_agent_count": len(registry),
        "boundaries": agent_boundaries(),
        "evidence": [item.to_dict() for item in evidence],
        "warnings": warnings,
        "policy": "Agents publish structured Engine evidence only; they do not own UI, broker execution or page rendering.",
    }
