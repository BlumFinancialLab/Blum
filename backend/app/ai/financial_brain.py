from __future__ import annotations

from functools import cached_property
import json
from typing import Any

from app.core.config import get_settings


class FinancialBrainModel:
    """Domain-specific financial reasoning adapter.

    The preferred model is a finance-domain open model. Loading is opt-in because
    7B finance models are too heavy for many CPU demo Spaces. The deterministic
    fallback keeps the same JSON contract and never invents unavailable evidence.
    """

    def __init__(self):
        self.settings = get_settings()
        self.model_name = self.settings.financial_brain_model

    @cached_property
    def generator(self):
        if not self.settings.enable_model_loading or not self.settings.enable_financial_brain_model:
            return None
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
            import torch

            tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                low_cpu_mem_usage=True,
            )
            return pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                max_new_tokens=self.settings.financial_brain_max_new_tokens,
                do_sample=False,
                return_full_text=False,
            )
        except Exception:
            return None

    def analyze_market(self, market_packet: dict[str, Any]) -> dict:
        compact_packet = compact_market_packet(market_packet)
        prompt = build_financial_brain_prompt(compact_packet)
        if self.generator is not None:
            try:
                output = self.generator(prompt)[0]["generated_text"]
                parsed = extract_json(output)
                if parsed:
                    parsed["model_name"] = self.model_name
                    parsed["model_status"] = "open_source_financial_llm"
                    parsed["evidence_policy"] = "model output constrained to supplied Market Brain packet"
                    return normalize_brain_output(parsed, compact_packet)
            except Exception:
                pass
        fallback = deterministic_financial_brain(compact_packet)
        fallback["configured_model"] = self.model_name
        fallback["model_status"] = "deterministic_fallback_financial_brain"
        fallback["evidence_policy"] = "fallback uses only supplied Market Brain packet"
        return fallback

    def status(self) -> dict:
        return {
            "configured_model": self.model_name,
            "enabled": self.settings.enable_model_loading and self.settings.enable_financial_brain_model,
            "load_policy": (
                "Loads the finance-domain LLM only when BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true. "
                "Otherwise the same JSON contract is served by the deterministic evidence engine."
            ),
            "purpose": "market regime reasoning, opportunity triage, contradiction review and monitoring plan generation",
        }


def build_financial_brain_prompt(packet: dict) -> str:
    evidence = json.dumps(packet, ensure_ascii=False, default=json_default)[:9000]
    return (
        "You are Blum Financial Brain, an open-source financial intelligence reasoning model. "
        "Use only the JSON evidence below. Do not invent facts, prices, targets, listing dates, valuations, future returns, "
        "or investment recommendations. Produce strict JSON only with keys: thesis, regime_interpretation, "
        "causal_map, opportunity_hypotheses, risk_hypotheses, opposing_case, what_market_may_be_missing, "
        "contradictions_to_resolve, monitoring_plan, confidence, intellectual_honesty, limitations.\n"
        "Each hypothesis must include evidence_refs from the supplied JSON.\n"
        f"EVIDENCE_JSON:\n{evidence}\nJSON_OUTPUT:"
    )


def compact_market_packet(packet: dict) -> dict:
    stack = packet.get("opportunity_stack", {})
    return {
        "created_at": packet.get("created_at"),
        "regime": packet.get("regime"),
        "brain_score": packet.get("brain_score"),
        "summary": packet.get("summary"),
        "market_now": {
            "average_sentiment": packet.get("market_now", {}).get("average_sentiment"),
            "news_count_48h": packet.get("market_now", {}).get("news_count_48h"),
            "signal_count": packet.get("market_now", {}).get("signal_count"),
            "top_themes": packet.get("market_now", {}).get("top_themes", [])[:8],
        },
        "top_stocks": stack.get("stock_research_priorities", [])[:8],
        "top_etfs": stack.get("etf_rotation_leaders", [])[:6],
        "top_ipos": stack.get("ipo_watch", [])[:6],
        "forward_scenarios": packet.get("forward_scenarios", [])[:3],
        "risk_alerts": packet.get("risk_alerts", [])[:10],
        "contradictions": packet.get("contradictions", [])[:10],
        "change_log": packet.get("change_log", [])[:8],
        "evidence_ledger": packet.get("evidence_ledger", {}),
    }


def deterministic_financial_brain(packet: dict) -> dict:
    top_stock = first_item(packet.get("top_stocks", []))
    top_etf = first_item(packet.get("top_etfs", []))
    top_ipo = first_item(packet.get("top_ipos", []))
    contradictions = packet.get("contradictions", [])
    risks = packet.get("risk_alerts", [])
    themes = packet.get("market_now", {}).get("top_themes", [])
    thesis_parts = [
        f"Current regime is {packet.get('regime', 'unknown')} with Brain Score {packet.get('brain_score', 0)}.",
        f"Market sentiment is {packet.get('market_now', {}).get('average_sentiment', 0)} across {packet.get('market_now', {}).get('news_count_48h', 0)} recent articles.",
    ]
    if top_stock:
        thesis_parts.append(f"Top stock research priority is {top_stock.get('ticker') or top_stock.get('name')} with score {top_stock.get('score')}.")
    if top_etf:
        thesis_parts.append(f"Top ETF confirmation is {top_etf.get('ticker')} with confirmation {top_etf.get('confirmation_score')}.")
    if top_ipo:
        thesis_parts.append(f"Top IPO watch item is {top_ipo.get('name')} with opportunity score {top_ipo.get('opportunity_score')}.")

    return {
        "model_name": "blum-deterministic-financial-brain",
        "thesis": " ".join(thesis_parts),
        "regime_interpretation": {
            "regime": packet.get("regime"),
            "read": regime_read(packet),
            "evidence_refs": ["regime", "brain_score", "market_now", "forward_scenarios"],
        },
        "opportunity_hypotheses": opportunity_hypotheses(top_stock, top_etf, top_ipo, themes),
        "risk_hypotheses": risk_hypotheses(risks, contradictions),
        "causal_map": market_causal_map(packet, top_stock, top_etf, themes),
        "opposing_case": market_opposing_case(packet, risks, contradictions),
        "what_market_may_be_missing": market_missing(packet, top_stock, top_etf, themes),
        "contradictions_to_resolve": [
            {
                "title": item.get("title"),
                "severity": item.get("severity"),
                "evidence_refs": ["contradictions", item.get("ticker")],
            }
            for item in contradictions[:6]
        ],
        "monitoring_plan": monitoring_plan(packet, top_stock, top_etf, top_ipo),
        "confidence": confidence_from_packet(packet),
        "intellectual_honesty": [
            "Regime classification is contextual, not a forecast.",
            "Opportunity hypotheses require confirmation from fresh price, volume and news evidence.",
            "Contradictions are treated as thesis reducers, not noise to ignore.",
        ],
        "limitations": [
            "This is research triage, not investment advice.",
            "The model cannot infer unavailable prices, private-company listing dates or valuations.",
            "Confidence depends on stored public data coverage and source availability.",
        ],
    }


def normalize_brain_output(parsed: dict, packet: dict) -> dict:
    required = deterministic_financial_brain(packet)
    for key, fallback_value in required.items():
        parsed.setdefault(key, fallback_value)
    if not isinstance(parsed.get("opportunity_hypotheses"), list):
        parsed["opportunity_hypotheses"] = required["opportunity_hypotheses"]
    if not isinstance(parsed.get("risk_hypotheses"), list):
        parsed["risk_hypotheses"] = required["risk_hypotheses"]
    if not isinstance(parsed.get("monitoring_plan"), list):
        parsed["monitoring_plan"] = required["monitoring_plan"]
    if not isinstance(parsed.get("limitations"), list):
        parsed["limitations"] = required["limitations"]
    return parsed


def opportunity_hypotheses(top_stock: dict | None, top_etf: dict | None, top_ipo: dict | None, themes: list[dict]) -> list[dict]:
    output = []
    if top_stock:
        output.append(
            {
                "title": f"{top_stock.get('ticker') or top_stock.get('name')} is the highest stock research priority.",
                "why_it_matters": "It is surfaced by the stock signal stack and should be validated against technical, sentiment and ETF evidence.",
                "evidence_refs": ["top_stocks[0]", "stock_research_priorities"],
            }
        )
    if top_etf:
        output.append(
            {
                "title": f"{top_etf.get('ticker')} is leading ETF confirmation.",
                "why_it_matters": "ETF rotation can confirm whether an equity narrative is sector-wide or isolated.",
                "evidence_refs": ["top_etfs[0]", "etf_rotation_leaders"],
            }
        )
    if top_ipo:
        output.append(
            {
                "title": f"{top_ipo.get('name')} is the top primary-market watch item.",
                "why_it_matters": "SEC filing readiness and narrative heat can identify research candidates before broad screen inclusion.",
                "evidence_refs": ["top_ipos[0]", "ipo_watch"],
            }
        )
    if themes:
        output.append(
            {
                "title": f"{themes[0].get('theme')} is the leading narrative cluster.",
                "why_it_matters": "Theme leadership helps connect news flow to assets and ETFs.",
                "evidence_refs": ["market_now.top_themes[0]"],
            }
        )
    return output


def risk_hypotheses(risks: list[dict], contradictions: list[dict]) -> list[dict]:
    output = [
        {
            "title": risk.get("title"),
            "why_it_matters": risk.get("detail"),
            "severity": risk.get("severity"),
            "evidence_refs": ["risk_alerts", ",".join(risk.get("tickers", [])[:4])],
        }
        for risk in risks[:5]
    ]
    if contradictions:
        output.append(
            {
                "title": "Contradictions need resolution before escalation.",
                "why_it_matters": "Price, sentiment and risk signals are not fully aligned.",
                "severity": "Medium",
                "evidence_refs": ["contradictions"],
            }
        )
    return output


def market_causal_map(packet: dict, top_stock: dict | None, top_etf: dict | None, themes: list[dict]) -> dict:
    sentiment = numeric(packet.get("market_now", {}).get("average_sentiment"))
    news_count = numeric(packet.get("market_now", {}).get("news_count_48h"))
    theme = themes[0].get("theme") if themes else "no dominant theme"
    return {
        "observed_facts": [
            f"Regime is {packet.get('regime')}.",
            f"Average sentiment is {sentiment:.2f} across {int(news_count)} recent articles.",
            f"Dominant theme is {theme}.",
        ],
        "possible_causes": [
            "News flow may be driving price attention if top signals and theme sentiment are aligned.",
            "Price action may be driving narrative attention if high-scoring stocks lack clear source catalysts.",
            "A macro or sector rotation event may explain both price and sentiment when ETF confirmation is elevated.",
        ],
        "correlations_not_causality": [
            "High sentiment and strong prices are treated as alignment, not proof that one caused the other.",
            "ETF confirmation indicates breadth, but does not prove fundamentals have changed.",
        ],
        "probable_causality": probable_market_causality(packet, top_stock, top_etf, themes),
        "evidence_refs": ["market_now", "top_stocks", "top_etfs", "forward_scenarios"],
    }


def market_opposing_case(packet: dict, risks: list[dict], contradictions: list[dict]) -> list[dict]:
    output = [
        {
            "title": "The opportunity stack may be price-led rather than fundamentally confirmed.",
            "why_it_matters": "Momentum without durable news, earnings or ETF breadth can reverse quickly.",
            "evidence_refs": ["top_stocks", "risk_alerts"],
        },
        {
            "title": "Signal confidence may be overstated if data coverage is thin.",
            "why_it_matters": "Missing or stale OHLCV/news evidence should reduce thesis strength.",
            "evidence_refs": ["evidence_ledger"],
        },
    ]
    if contradictions:
        output.insert(
            0,
            {
                "title": "Contradictions directly challenge the market thesis.",
                "why_it_matters": "A strong thesis should survive price/sentiment/risk cross-checks.",
                "evidence_refs": ["contradictions"],
            },
        )
    if risks:
        output.append(
            {
                "title": "Risk alerts may dominate opportunity selection.",
                "why_it_matters": risks[0].get("detail") or "Risk cluster requires tighter monitoring.",
                "evidence_refs": ["risk_alerts[0]"],
            }
        )
    return output[:6]


def market_missing(packet: dict, top_stock: dict | None, top_etf: dict | None, themes: list[dict]) -> list[dict]:
    output = []
    if top_stock and top_etf:
        output.append(
            {
                "title": "Sector breadth may be more important than the individual top stock.",
                "why_it_matters": "ETF confirmation can reveal a sector rotation that single-name scoring understates.",
                "evidence_refs": ["top_stocks[0]", "top_etfs[0]"],
            }
        )
    if themes:
        output.append(
            {
                "title": f"{themes[0].get('theme')} may be earlier or later than headline counts imply.",
                "why_it_matters": "Narrative lifecycle depends on velocity, saturation and crowding, not headline count alone.",
                "evidence_refs": ["market_now.top_themes[0]"],
            }
        )
    if numeric(packet.get("market_now", {}).get("signal_count")) == 0:
        output.append(
            {
                "title": "The market may be unscored because data coverage is incomplete.",
                "why_it_matters": "No score should be interpreted as no opportunity when evidence hydration is still incomplete.",
                "evidence_refs": ["evidence_ledger"],
            }
        )
    return output or [
        {
            "title": "No clear market blind spot is visible.",
            "why_it_matters": "Blum should prefer intellectual honesty when evidence does not show a differentiated read.",
            "evidence_refs": ["evidence_ledger"],
        }
    ]


def probable_market_causality(packet: dict, top_stock: dict | None, top_etf: dict | None, themes: list[dict]) -> str:
    sentiment = numeric(packet.get("market_now", {}).get("average_sentiment"))
    news_count = numeric(packet.get("market_now", {}).get("news_count_48h"))
    etf_score = numeric(top_etf.get("confirmation_score")) if top_etf else 0
    stock_score = numeric(top_stock.get("score")) if top_stock else 0
    if news_count >= 20 and sentiment > 0.12 and stock_score >= 65:
        return "Narrative and price are likely reinforcing each other, but direct causality is not proven."
    if etf_score >= 62 and stock_score >= 60:
        return "Sector rotation may be a common driver behind single-name and ETF strength."
    if stock_score >= 65 and sentiment <= 0:
        return "Price action may be leading sentiment or reflecting technical/positioning factors."
    return "The supplied evidence does not isolate one dominant causal driver."


def monitoring_plan(packet: dict, top_stock: dict | None, top_etf: dict | None, top_ipo: dict | None) -> list[dict]:
    plan = [
        {"item": "Regime change", "metric": "market_brain.regime and change_log", "cadence": "each run"},
        {"item": "Narrative health", "metric": "market_now.average_sentiment and top themes", "cadence": "live news refresh"},
        {"item": "Contradiction count", "metric": "contradictions", "cadence": "each brain run"},
    ]
    if top_stock:
        plan.append({"item": top_stock.get("ticker") or top_stock.get("name"), "metric": "score, lifecycle, confidence, sentiment divergence", "cadence": "market refresh"})
    if top_etf:
        plan.append({"item": top_etf.get("ticker"), "metric": "ETF confirmation score and 1M performance", "cadence": "market refresh"})
    if top_ipo:
        plan.append({"item": top_ipo.get("name"), "metric": "SEC filings, latest form, readiness score", "cadence": "IPO refresh"})
    return plan


def regime_read(packet: dict) -> str:
    score = numeric(packet.get("brain_score"))
    contradictions = len(packet.get("contradictions", []))
    if contradictions >= 4:
        return "Opportunity stack is active but conflict-heavy; require confirmation before escalating research priority."
    if score >= 70:
        return "Evidence coverage and signal strength are relatively strong."
    if score >= 45:
        return "Evidence is usable but selective; prioritize the highest-confidence clusters."
    return "Evidence is still forming; source coverage and signal snapshots need to improve."


def confidence_from_packet(packet: dict) -> dict:
    ledger = packet.get("evidence_ledger", {})
    signal_count = numeric(ledger.get("distinct_signals"))
    news_count = numeric(ledger.get("sentiment_articles_48h"))
    ipo_count = numeric(ledger.get("ipo_filings_observed"))
    raw = min(100, signal_count * 1.8 + news_count * 1.4 + ipo_count * 0.35)
    if len(packet.get("contradictions", [])) >= 5:
        raw -= 12
    return {
        "score": round(max(0, min(100, raw)), 1),
        "label": "High" if raw >= 70 else "Medium" if raw >= 45 else "Low",
        "evidence_refs": ["evidence_ledger", "contradictions"],
    }


def first_item(rows: list[dict]) -> dict | None:
    return rows[0] if rows else None


def extract_json(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def numeric(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def json_default(value) -> str:
    return str(value)
