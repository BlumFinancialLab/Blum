export function BreakdownBars({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown ?? {});
  if (!entries.length) return <div className="empty-state">No score breakdown available.</div>;
  return (
    <div className="breakdown-bars">
      {entries.map(([key, value]) => (
        <div className="breakdown-row" key={key}>
          <span>{key.replaceAll("_", " ")}</span>
          <div><i style={{ width: `${Math.max(4, Math.min(100, Number(value)))}%` }} /></div>
          <strong>{Number(value).toFixed(1)}</strong>
        </div>
      ))}
    </div>
  );
}

