#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import date, datetime
import gzip
import json
from pathlib import Path
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data.seed_assets import SEED_ASSETS  # noqa: E402


OUTPUT = ROOT / "backend" / "app" / "data" / "historical_prices_seed.csv.gz"
MANIFEST = ROOT / "backend" / "app" / "data" / "historical_prices_seed_manifest.json"
OUTPUT_TMP = OUTPUT.with_suffix(".csv.gz.tmp")
MANIFEST_TMP = MANIFEST.with_suffix(".json.tmp")
FIELDS = ["ticker", "date", "open", "high", "low", "close", "volume", "provider"]
HTTP_TIMEOUT_SECONDS = 8
MIN_ACCEPTED_ROWS = 50_000

socket.setdefaulttimeout(HTTP_TIMEOUT_SECONDS)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    diagnostics = []
    with gzip.open(OUTPUT_TMP, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for asset in SEED_ASSETS:
            ticker = asset["ticker"]
            rows, provider, status = fetch_history(ticker)
            if len(rows) >= 60:
                for row in rows:
                    row["ticker"] = ticker
                    row["provider"] = provider
                    writer.writerow({field: row.get(field, "") for field in FIELDS})
                written += len(rows)
            diagnostics.append(
                {
                    "ticker": ticker,
                    "provider": provider,
                    "status": status,
                    "rows": len(rows),
                    "start": rows[0]["date"] if rows else None,
                    "end": rows[-1]["date"] if rows else None,
                }
            )
            print(f"{ticker:8} {provider:12} {status:12} {len(rows):6} rows", flush=True)
            time.sleep(0.18)
    manifest = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "data_policy": "Real public OHLCV cache. Missing assets are not backfilled with synthetic data.",
        "output": OUTPUT.name,
        "row_count": written,
        "asset_count": len([item for item in diagnostics if item["rows"] >= 60]),
        "diagnostics": diagnostics,
    }
    MANIFEST_TMP.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if written < MIN_ACCEPTED_ROWS:
        print(
            f"Refusing to replace cache: only {written} rows generated, minimum is {MIN_ACCEPTED_ROWS}. "
            f"Temporary file kept at {OUTPUT_TMP}",
            flush=True,
        )
        return 1
    OUTPUT_TMP.replace(OUTPUT)
    MANIFEST_TMP.replace(MANIFEST)
    print(f"Wrote {written} rows to {OUTPUT}", flush=True)
    return 0


def fetch_history(ticker: str) -> tuple[list[dict], str, str]:
    if "." not in ticker:
        rows = fetch_nasdaq(ticker)
        if len(rows) >= 60:
            return rows, "nasdaq_api", "ok"
    rows = fetch_yahoo_chart(ticker)
    if len(rows) >= 60:
        return rows, "yahoo_chart", "ok"
    return [], "none", "missing"


def fetch_stooq(host: str, symbol: str) -> list[dict]:
    url = f"{host}/q/d/l/?s={symbol}&i=d"
    try:
        text = http_get(url).decode("utf-8", errors="replace")
    except Exception:
        return []
    if not text or "No data" in text[:120]:
        return []
    rows = []
    for item in csv.DictReader(text.splitlines()):
        parsed = normalize_ohlcv_row(item)
        if parsed:
            rows.append(parsed)
    return sorted(rows, key=lambda row: row["date"])


def fetch_nasdaq(ticker: str) -> list[dict]:
    today = date.today()
    params = {
        "fromdate": "1990-01-01",
        "todate": today.isoformat(),
        "limit": "9999",
    }
    for asset_class in ("stocks", "etf"):
        url = f"https://api.nasdaq.com/api/quote/{ticker}/historical?{urlencode({**params, 'assetclass': asset_class})}"
        try:
            payload = json.loads(http_get(url, nasdaq=True).decode("utf-8", errors="replace"))
        except Exception:
            continue
        data = payload.get("data") if isinstance(payload, dict) else None
        raw_rows = (data or {}).get("tradesTable", {}).get("rows", [])
        rows = [normalize_nasdaq_row(row) for row in raw_rows]
        rows = [row for row in rows if row]
        if len(rows) >= 60:
            return sorted(rows, key=lambda row: row["date"])
    return []


def fetch_yahoo_chart(ticker: str) -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = urlencode({"range": "max", "interval": "1d", "includePrePost": "false", "events": "div,splits"})
    try:
        payload = json.loads(http_get(f"{url}?{params}").decode("utf-8", errors="replace"))
    except Exception:
        return []
    result = payload.get("chart", {}).get("result", []) if isinstance(payload, dict) else []
    if not result:
        return []
    data = result[0]
    timestamps = data.get("timestamp") or []
    quote = (data.get("indicators", {}).get("quote") or [{}])[0]
    rows = []
    for index, timestamp in enumerate(timestamps):
        try:
            close = value_at(quote.get("close"), index)
            if close is None:
                continue
            rows.append(
                {
                    "date": datetime.utcfromtimestamp(int(timestamp)).date().isoformat(),
                    "open": value_at(quote.get("open"), index),
                    "high": value_at(quote.get("high"), index),
                    "low": value_at(quote.get("low"), index),
                    "close": close,
                    "volume": value_at(quote.get("volume"), index),
                }
            )
        except Exception:
            continue
    return sorted(rows, key=lambda row: row["date"])


def http_get(url: str, nasdaq: bool = False) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json,text/csv,text/plain,*/*",
    }
    if nasdaq:
        headers.update({"Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError):
        return b""


def normalize_ohlcv_row(row: dict) -> dict | None:
    try:
        parsed_date = parse_date(row.get("Date"))
        close = parse_number(row.get("Close"))
        if not parsed_date or close is None:
            return None
        return {
            "date": parsed_date,
            "open": parse_number(row.get("Open")),
            "high": parse_number(row.get("High")),
            "low": parse_number(row.get("Low")),
            "close": close,
            "volume": parse_number(row.get("Volume")),
        }
    except Exception:
        return None


def normalize_nasdaq_row(row: dict) -> dict | None:
    try:
        parsed_date = parse_date(row.get("date"))
        close = parse_number(row.get("close"))
        if not parsed_date or close is None:
            return None
        return {
            "date": parsed_date,
            "open": parse_number(row.get("open")),
            "high": parse_number(row.get("high")),
            "low": parse_number(row.get("low")),
            "close": close,
            "volume": parse_number(row.get("volume")),
        }
    except Exception:
        return None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except Exception:
            continue
    return None


def parse_number(value) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if cleaned in {"", "N/A", "--", "nan", "NaN"}:
        return None
    try:
        return float(cleaned)
    except Exception:
        return None


def value_at(values, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def stooq_candidates(ticker: str) -> list[str]:
    raw = ticker.lower()
    suffix_map = {
        ".pa": ".fr",
        ".de": ".de",
        ".mi": ".it",
        ".as": ".nl",
        ".sw": ".ch",
        ".l": ".uk",
    }
    candidates: list[str] = []
    if "." in raw:
        for source_suffix, stooq_suffix in suffix_map.items():
            if raw.endswith(source_suffix):
                candidates.append(raw[: -len(source_suffix)] + stooq_suffix)
        candidates.append(raw)
    else:
        candidates.append(f"{raw}.us")
        candidates.append(raw)
    return list(dict.fromkeys(candidates))


if __name__ == "__main__":
    raise SystemExit(main())
