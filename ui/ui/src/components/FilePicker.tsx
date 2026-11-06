import { useState } from "react";

/** Reads a discovery JSON file in the browser and hands the parsed payload to the caller. */
export function FilePicker({
  onLoaded,
}: {
  onLoaded: (payload: Record<string, unknown>, filename: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  async function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text) as Record<string, unknown>;
      const vms = Array.isArray(payload.virtual_machines) ? payload.virtual_machines.length : 0;
      const metadata = (payload.metadata ?? {}) as Record<string, unknown>;
      setSummary(`${file.name}: ${vms} VM(s), schema ${String(metadata.schema_name ?? "unknown")} ${String(metadata.schema_version ?? "")}`);
      setError(null);
      onLoaded(payload, file.name);
    } catch (exc) {
      setError(`Could not parse ${file.name}: ${(exc as Error).message}`);
      setSummary(null);
    }
  }

  return (
    <div>
      <input type="file" accept="application/json,.json" onChange={handleChange} data-testid="discovery-file" />
      {summary && <div className="small muted" data-testid="file-summary">{summary}</div>}
      {error && <div className="alert bad">{error}</div>}
    </div>
  );
}
