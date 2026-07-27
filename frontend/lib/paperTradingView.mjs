export const CLOSED_PAPER_STATUSES = new Set(["CLOSED", "EXPIRED", "INVALIDATED"]);
export const OPEN_PAPER_STATUSES = new Set(["OPEN", "MANAGED"]);
export const CANDIDATE_PAPER_STATUSES = new Set(["CANDIDATE", "WAITING_FOR_TRIGGER", "SKIPPED", "DATA_BLOCKED", "ERROR"]);

export function normalizePaperStatus(value) {
  return String(value ?? "UNKNOWN").toUpperCase();
}

export function paperTradeKey(row) {
  return String(
    row.trade_id
      ?? row.trade_uid
      ?? `${row.source_engine ?? "paper"}-${row.source_trade_id ?? "unknown"}-${row.ticker ?? "unknown"}`,
  );
}

export function mergePaperTrades(snapshot) {
  const rows = [
    ...(snapshot?.trades ?? []),
    ...(snapshot?.latest_candidates ?? snapshot?.candidates ?? []),
    ...(snapshot?.open_positions ?? []),
    ...(snapshot?.recently_closed_trades ?? snapshot?.recently_closed ?? []),
  ];
  const byTrade = new Map();

  for (const row of rows) {
    const key = paperTradeKey(row);
    const previous = byTrade.get(key);
    if (!previous) {
      byTrade.set(key, row);
      continue;
    }

    const previousTerminal = CLOSED_PAPER_STATUSES.has(normalizePaperStatus(previous.status));
    const currentTerminal = CLOSED_PAPER_STATUSES.has(normalizePaperStatus(row.status));
    if (currentTerminal || !previousTerminal) {
      byTrade.set(key, { ...previous, ...row });
    }
  }

  return Array.from(byTrade.values());
}

export function filterPaperMarket(rows, market) {
  return rows.filter((row) => market === "forex" ? row.market_group === "forex" : row.market_group !== "forex");
}

export function filterPaperLifecycle(rows, lifecycle) {
  const statuses = lifecycle === "closed"
    ? CLOSED_PAPER_STATUSES
    : lifecycle === "open"
      ? OPEN_PAPER_STATUSES
      : CANDIDATE_PAPER_STATUSES;
  return rows.filter((row) => statuses.has(normalizePaperStatus(row.status)));
}
