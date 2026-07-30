from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ForexIntradayPositionSize:
    quantity_units: float
    quantity_lots: float
    risk_amount_eur: float
    risk_fraction: float
    notional_eur: float
    margin_eur: float
    blocker: str | None = None


def size_forex_intraday_position(
    *,
    capital_eur: float,
    risk_fraction: float,
    entry_price: float,
    stop_price: float,
    account_fx_rate: float | None,
    max_notional_leverage: float = 15.0,
    margin_leverage: float = 30.0,
) -> ForexIntradayPositionSize:
    """Size base-currency units from an account-currency risk budget."""

    if account_fx_rate is None or not math.isfinite(account_fx_rate) or account_fx_rate <= 0:
        return _blocked("FX_CONVERSION_UNAVAILABLE")
    risk_per_unit_quote = abs(float(entry_price) - float(stop_price))
    if capital_eur <= 0 or entry_price <= 0 or risk_per_unit_quote <= 0:
        return _blocked("INVALID_FOREX_RISK_GEOMETRY")
    bounded_fraction = max(0.0, min(0.01, float(risk_fraction)))
    if bounded_fraction <= 0:
        return _blocked("INVALID_FOREX_RISK_BUDGET")

    risk_budget_eur = float(capital_eur) * bounded_fraction
    risk_units = risk_budget_eur * float(account_fx_rate) / risk_per_unit_quote
    leverage_units = (
        float(capital_eur)
        * max(1.0, float(max_notional_leverage))
        * float(account_fx_rate)
        / float(entry_price)
    )
    units = max(0.0, min(risk_units, leverage_units))
    notional_eur = float(entry_price) * units / float(account_fx_rate)
    risk_amount_eur = risk_per_unit_quote * units / float(account_fx_rate)
    margin_eur = notional_eur / max(1.0, float(margin_leverage))
    return ForexIntradayPositionSize(
        quantity_units=round(units, 8),
        quantity_lots=round(units / 100_000.0, 8),
        risk_amount_eur=round(risk_amount_eur, 8),
        risk_fraction=round(risk_amount_eur / float(capital_eur), 8),
        notional_eur=round(notional_eur, 8),
        margin_eur=round(margin_eur, 8),
    )


def forex_account_pnl(
    *,
    entry_price: float,
    exit_price: float,
    quantity_units: float,
    account_fx_rate: float | None,
    direction: str = "LONG",
) -> float:
    if account_fx_rate is None or account_fx_rate <= 0:
        raise ValueError("A positive point-in-time account FX rate is required")
    sign = -1.0 if str(direction).upper() in {"SHORT", "SELL"} else 1.0
    quote_pnl = (float(exit_price) - float(entry_price)) * float(quantity_units) * sign
    return quote_pnl / float(account_fx_rate)


def _blocked(reason: str) -> ForexIntradayPositionSize:
    return ForexIntradayPositionSize(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, reason)
