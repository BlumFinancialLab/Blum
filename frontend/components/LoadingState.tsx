export function LoadingState({ label = "Loading intelligence snapshot" }: { label?: string }) {
  return (
    <div className="loading-state">
      <div />
      <span>{label}</span>
    </div>
  );
}

