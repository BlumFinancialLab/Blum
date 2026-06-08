import clsx from "clsx";

export function StatusBadge({ label }: { label: string }) {
  const tone =
    label.includes("Breakout") || label.includes("Strong")
      ? "positive"
      : label.includes("Risk") || label.includes("Avoid")
        ? "negative"
        : label.includes("Divergence") || label.includes("Contrarian")
          ? "warning"
          : "neutral";
  return <span className={clsx("status-badge", tone)}>{label}</span>;
}

