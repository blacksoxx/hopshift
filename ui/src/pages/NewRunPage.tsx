import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { FilePicker } from "../components/FilePicker";
import type { Meta, RunOptions } from "../types";

const DEFAULTS: RunOptions = {
  cloud: "aws", environment: "dev", owner: "", mode: null, llm_provider: null, llm_model: null,
  skip_validation: false, skip_opa: false, no_mcp: false, dry_run: false, llm_review_notes: true, pause_points: [],
};

export function NewRunPage() {
  const navigate = useNavigate();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [discovery, setDiscovery] = useState<Record<string, unknown> | null>(null);
  const [filename, setFilename] = useState("discovery.json");
  const [options, setOptions] = useState<RunOptions>(DEFAULTS);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.meta()
      .then((loaded) => {
        setMeta(loaded);
        setOptions((current) => ({ ...current, pause_points: loaded.default_pause_points }));
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  function update<K extends keyof RunOptions>(key: K, value: RunOptions[K]) {
    setOptions((current) => ({ ...current, [key]: value }));
  }

  function togglePause(name: string) {
    setOptions((current) => ({
      ...current,
      pause_points: current.pause_points.includes(name)
        ? current.pause_points.filter((item) => item !== name)
        : [...current.pause_points, name],
    }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!discovery) {
      setError("Choose a discovery JSON file first.");
      return;
    }
    setSubmitting(true);
    try {
      const record = await api.createRun(discovery, options, filename, true);
      navigate(`/runs/${record.run_id}`);
    } catch (exc) {
      setError((exc as Error).message);
      setSubmitting(false);
    }
  }

  const llmMode = options.mode === "llm" || options.mode === "hybrid";

  return (
    <div>
      <h1>New run</h1>
      {error && <div className="alert bad" data-testid="form-error">{error}</div>}
      <form className="panel" onSubmit={submit}>
        <div className="field">
          <label>Discovery JSON</label>
          <FilePicker onLoaded={(payload, name) => { setDiscovery(payload); setFilename(name); }} />
        </div>
        <div className="field">
          <label htmlFor="cloud">Target cloud</label>
          <select id="cloud" value={options.cloud} onChange={(e) => update("cloud", e.target.value)}>
            {(meta?.clouds ?? ["aws", "azure", "gcp", "openstack"]).map((cloud) => <option key={cloud} value={cloud}>{cloud}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="mode">Generation mode</label>
          <select id="mode" value={options.mode ?? ""} onChange={(e) => update("mode", e.target.value || null)}>
            <option value="">config default (deterministic)</option>
            {(meta?.modes ?? []).map((mode) => <option key={mode} value={mode}>{mode}</option>)}
          </select>
        </div>
        {llmMode && (
          <div className="field">
            <label htmlFor="llm_provider">LLM provider</label>
            <select id="llm_provider" value={options.llm_provider ?? ""} onChange={(e) => update("llm_provider", e.target.value || null)}>
              <option value="">(from config)</option>
              <option value="anthropic">anthropic</option>
              <option value="openai">openai</option>
              <option value="google">google</option>
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="environment">Environment tag</label>
          <input id="environment" type="text" value={options.environment} onChange={(e) => update("environment", e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="owner">Owner tag</label>
          <input id="owner" type="text" value={options.owner} onChange={(e) => update("owner", e.target.value)} required />
        </div>
        <div className="field">
          <label>Options</label>
          <div className="checks">
            <label><input type="checkbox" checked={options.skip_validation} onChange={(e) => update("skip_validation", e.target.checked)} /> skip validation</label>
            <label><input type="checkbox" checked={options.skip_opa} onChange={(e) => update("skip_opa", e.target.checked)} /> skip OPA</label>
            <label><input type="checkbox" checked={options.no_mcp} onChange={(e) => update("no_mcp", e.target.checked)} /> no MCP</label>
            <label><input type="checkbox" checked={options.dry_run} onChange={(e) => update("dry_run", e.target.checked)} /> dry run</label>
            <label><input type="checkbox" checked={options.llm_review_notes} onChange={(e) => update("llm_review_notes", e.target.checked)} /> AI review notes</label>
          </div>
        </div>
        <div className="field">
          <label>Pause for</label>
          <div className="checks">
            {Object.entries(meta?.pause_points ?? {}).map(([name, node]) => (
              <label key={name}>
                <input type="checkbox" checked={options.pause_points.includes(name)} onChange={() => togglePause(name)} />
                {name} <span className="muted small">(before {node})</span>
              </label>
            ))}
          </div>
        </div>
        <div className="actions">
          <button className="primary" type="submit" disabled={submitting || !discovery} data-testid="start-run">
            {submitting ? "Starting…" : "Start run"}
          </button>
        </div>
      </form>
    </div>
  );
}
