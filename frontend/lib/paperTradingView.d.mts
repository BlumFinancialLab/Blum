export type PaperTradingRow = Record<string, any>;
export type PaperMarket = "equities" | "forex";
export type PaperLifecycle = "closed" | "open" | "candidates";

export const CLOSED_PAPER_STATUSES: Set<string>;
export const OPEN_PAPER_STATUSES: Set<string>;
export const CANDIDATE_PAPER_STATUSES: Set<string>;

export function normalizePaperStatus(value: unknown): string;
export function paperTradeKey(row: PaperTradingRow): string;
export function mergePaperTrades(snapshot: any): PaperTradingRow[];
export function isForexPaperTrade(row: PaperTradingRow): boolean;
export function filterPaperMarket(
  rows: PaperTradingRow[],
  market: PaperMarket,
): PaperTradingRow[];
export function filterPaperLifecycle(
  rows: PaperTradingRow[],
  lifecycle: PaperLifecycle,
): PaperTradingRow[];
export function formatPaperCurrency(value: unknown): string;
export function paperPnlTone(value: unknown): "positive" | "negative" | "neutral";
