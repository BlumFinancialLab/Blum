import { MarketSnapshot } from "@/lib/types";

export function MarketSnapshotStrip({ snapshot, compact = false }: { snapshot?: MarketSnapshot | null; compact?: boolean }) {
  if (!snapshot || snapshot.data_status !== "ready" || snapshot.price == null) {
    return (
      <div className={compact ? "market-strip compact" : "market-strip"}>
        <div><span>Price</span><strong>Real price pending</strong></div>
        <div><span>Provider</span><strong>n/a</strong></div>
      </div>
    );
  }
  return (
    <div className={compact ? "market-strip compact" : "market-strip"}>
      <div>
        <span>Last Price</span>
        <strong>{formatPrice(snapshot.price, snapshot.currency)}</strong>
      </div>
      <div>
        <span>1D</span>
        <strong className={tone(snapshot.perf_1d)}>{formatPercent(snapshot.perf_1d)}</strong>
      </div>
      {!compact && (
        <>
          <div>
            <span>5D</span>
            <strong className={tone(snapshot.perf_5d)}>{formatPercent(snapshot.perf_5d)}</strong>
          </div>
          <div>
            <span>1M</span>
            <strong className={tone(snapshot.perf_1m)}>{formatPercent(snapshot.perf_1m)}</strong>
          </div>
        </>
      )}
      <div>
        <span>{snapshot.provider ?? "Provider"}</span>
        <strong>{snapshot.date ?? "n/a"}</strong>
      </div>
    </div>
  );
}

export function formatPrice(value: number | null | undefined, currency = "USD") {
  if (value == null || Number.isNaN(Number(value))) return "n/a";
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency: currency || "USD",
    maximumFractionDigits: value >= 100 ? 2 : 4,
  }).format(Number(value));
}

export function formatPercent(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return "n/a";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

export function formatVolume(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return "n/a";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 2 }).format(Number(value));
}

function tone(value: number | null | undefined) {
  if (value == null) return "";
  if (value > 0) return "positive-text";
  if (value < 0) return "negative-text";
  return "";
}
