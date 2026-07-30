from __future__ import annotations

import pytest

from app.services.forex_intraday_accounting import (
    forex_account_pnl,
    size_forex_intraday_position,
)


def test_forex_sizing_uses_account_currency_risk_and_margin() -> None:
    sizing = size_forex_intraday_position(
        capital_eur=100.0,
        risk_fraction=0.005,
        entry_price=187.0,
        stop_price=186.5,
        account_fx_rate=187.0,
        max_notional_leverage=15.0,
        margin_leverage=30.0,
    )

    assert sizing.quantity_units == pytest.approx(187.0)
    assert sizing.quantity_lots == pytest.approx(0.00187)
    assert sizing.risk_amount_eur == pytest.approx(0.5)
    assert sizing.notional_eur == pytest.approx(187.0)
    assert sizing.margin_eur == pytest.approx(187.0 / 30.0)


def test_forex_pnl_is_converted_from_quote_currency_to_eur() -> None:
    pnl = forex_account_pnl(
        entry_price=187.0,
        exit_price=187.2,
        quantity_units=187.0,
        account_fx_rate=187.0,
        direction="LONG",
    )

    assert pnl == pytest.approx(0.2)


def test_forex_sizing_rejects_missing_point_in_time_fx_rate() -> None:
    sizing = size_forex_intraday_position(
        capital_eur=100.0,
        risk_fraction=0.005,
        entry_price=1.1,
        stop_price=1.095,
        account_fx_rate=None,
    )

    assert sizing.quantity_units == 0.0
    assert sizing.blocker == "FX_CONVERSION_UNAVAILABLE"
