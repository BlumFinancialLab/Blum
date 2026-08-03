from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Iterable

from app.services.deterministic_execution.contracts import (
    KernelOrderEvent,
    KernelPositionEvent,
)


def normalize_native_events(
    events: Iterable[object],
    decision_by_order: dict[str, str],
) -> tuple[tuple[KernelOrderEvent, ...], tuple[KernelPositionEvent, ...]]:
    orders: list[KernelOrderEvent] = []
    positions: list[KernelPositionEvent] = []
    for sequence, event in enumerate(events):
        event_type = type(event).__name__
        timestamp = _datetime_from_ns(int(getattr(event, "ts_event", 0)))
        if event_type.startswith("Order"):
            order_id = str(getattr(event, "client_order_id", ""))
            orders.append(
                KernelOrderEvent(
                    event_id=_event_id(event_type, timestamp.isoformat(), sequence, order_id),
                    order_id=order_id,
                    decision_id=decision_by_order.get(order_id, ""),
                    event_type=event_type,
                    timestamp=timestamp,
                    quantity=_number(getattr(event, "last_qty", None) or getattr(event, "quantity", None)),
                    price=_optional_number(getattr(event, "last_px", None) or getattr(event, "price", None)),
                    reason=str(getattr(event, "reason", "") or ""),
                )
            )
        elif event_type.startswith("Position"):
            positions.append(
                KernelPositionEvent(
                    event_id=_event_id(event_type, timestamp.isoformat(), sequence, str(getattr(event, "position_id", ""))),
                    position_id=str(getattr(event, "position_id", "")),
                    instrument_id=str(getattr(event, "instrument_id", "")),
                    event_type=event_type,
                    timestamp=timestamp,
                    quantity=_number(getattr(event, "quantity", None) or getattr(event, "last_qty", None)),
                    average_price=_optional_number(getattr(event, "last_px", None) or getattr(event, "avg_px_open", None)),
                    realized_pnl=_money_number(getattr(event, "realized_pnl", None)),
                )
            )
    return tuple(orders), tuple(positions)


def reproducibility_fingerprint(
    order_events: tuple[KernelOrderEvent, ...],
    position_events: tuple[KernelPositionEvent, ...],
    costs: tuple[tuple[str, float], ...],
) -> str:
    payload = {
        "orders": [
            [item.decision_id, item.event_type, item.timestamp.isoformat(), item.quantity, item.price, item.reason]
            for item in order_events
        ],
        "positions": [
            [item.instrument_id, item.event_type, item.timestamp.isoformat(), item.quantity, item.average_price, item.realized_pnl]
            for item in position_events
        ],
        "costs": list(costs),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_commissions(rows: list[dict]) -> tuple[tuple[str, float], ...]:
    totals: dict[str, float] = {}
    for row in rows:
        for commission in row.get("commissions") or []:
            match = re.match(r"\s*([-+0-9.]+)\s+([A-Z]{3,})", str(commission))
            if match:
                totals[match.group(2)] = totals.get(match.group(2), 0.0) + float(match.group(1))
    return tuple(sorted((currency, round(value, 10)) for currency, value in totals.items()))


def _event_id(*parts: object) -> str:
    return sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:32]


def _datetime_from_ns(value: int):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc).replace(tzinfo=None)


def _number(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    return _number(value)


def _money_number(value: object) -> float | None:
    if value is None:
        return None
    match = re.match(r"\s*([-+0-9.]+)", str(value))
    return float(match.group(1)) if match else None

