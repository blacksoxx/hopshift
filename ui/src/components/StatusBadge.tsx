const KNOWN = new Set(["created", "running", "paused", "succeeded", "failed", "error", "safe", "caution", "elevated", "critical"]);

export function StatusBadge({ status }: { status: string }) {
  const cls = KNOWN.has(status) ? status : "neutral";
  return (
    <span className={`badge ${cls}`} data-testid="status-badge">
      {status}
    </span>
  );
}
