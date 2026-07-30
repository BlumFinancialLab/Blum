import assert from "node:assert/strict";
import test from "node:test";
import {
  filterPaperLifecycle,
  filterPaperMarket,
  isForexPaperTrade,
  mergePaperTrades,
} from "../lib/paperTradingView.mjs";

test("a closed trade replaces an older skipped projection of the same trade", () => {
  const rows = mergePaperTrades({
    trades: [{ trade_id: "trade-1", ticker: "NVDA", status: "SKIPPED" }],
    recently_closed_trades: [{
      trade_id: "trade-1",
      ticker: "NVDA",
      status: "CLOSED",
      net_pnl_eur: 12.5,
      exit_price: 155,
    }],
  });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, "CLOSED");
  assert.equal(rows[0].net_pnl_eur, 12.5);
});

test("closed history is isolated from skipped candidates", () => {
  const rows = [
    { trade_id: "closed", status: "CLOSED", net_pnl_eur: -2 },
    { trade_id: "skipped", status: "SKIPPED" },
  ];

  assert.deepEqual(filterPaperLifecycle(rows, "closed").map((row) => row.trade_id), ["closed"]);
  assert.deepEqual(filterPaperLifecycle(rows, "candidates").map((row) => row.trade_id), ["skipped"]);
});

test("market filtering preserves separate equity and forex histories", () => {
  const rows = [
    { trade_id: "equity", market_group: "standard", status: "CLOSED" },
    { trade_id: "forex", market_group: "forex", status: "CLOSED" },
  ];

  assert.deepEqual(filterPaperMarket(rows, "equities").map((row) => row.trade_id), ["equity"]);
  assert.deepEqual(filterPaperMarket(rows, "forex").map((row) => row.trade_id), ["forex"]);
});

test("forex identity wins over stale intraday market grouping", () => {
  const rows = [
    {
      trade_id: "intraday-forex",
      ticker: "EURJPY=X",
      market_group: "intraday",
      market: "FOREX",
      asset_type: "Forex",
      status: "CLOSED",
    },
    {
      trade_id: "intraday-equity",
      ticker: "NVDA",
      market_group: "intraday",
      market: "us_equity",
      asset_type: "Stock",
      status: "CLOSED",
    },
  ];

  assert.equal(isForexPaperTrade(rows[0]), true);
  assert.equal(isForexPaperTrade(rows[1]), false);
  assert.deepEqual(filterPaperMarket(rows, "equities").map((row) => row.trade_id), ["intraday-equity"]);
  assert.deepEqual(filterPaperMarket(rows, "forex").map((row) => row.trade_id), ["intraday-forex"]);
});
