import { useState } from "react";
import { api } from "../api";
import { FilePicker } from "../components/FilePicker";
import { StatusBadge } from "../components/StatusBadge";
import type { AssessmentResult } from "../types";

export function AssessPage() {
  const [discovery, setDiscovery] = useState<Record<string, unknown> | null>(null);
  const [cloud, setCloud] = useState("aws");
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    if (!discovery) return;
    setBusy(true);
    try {
      setResult(await api.assess(discovery, cloud));
      setError(null);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Assess</h1>
      <p className="muted small">Deterministic readiness report over the whole inventory. No cloud access, no model, blocked VMs are scored instead of dropped.</p>
      {error && <div className="alert bad">{error}</div>}
      <form className="panel" onSubmit={run}>
        <div className="field">
          <label>Discovery JSON</label>
          <FilePicker onLoaded={(payload) => setDiscovery(payload)} />
        </div>
        <div className="field">
          <label htmlFor="assess-cloud">Target cloud</label>
          <select id="assess-cloud" value={cloud} onChange={(e) => setCloud(e.target.value)}>
            {["aws", "azure", "gcp", "openstack"].map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </div>
        <div className="actions">
          <button className="primary" type="submit" disabled={busy || !discovery} data-testid="run-assess">{busy ? "Assessing…" : "Assess"}</button>
        </div>
      </form>

      {result && (
        <div data-testid="assessment">
          <div className="stats">
            {(["total_resources", "safe", "caution", "elevated", "critical"] as const).map((key) => (
              <div className="stat" key={key}>
                <div className="label">{key.replace("_", " ")}</div>
                <div className="value">{result.summary[key]}</div>
              </div>
            ))}
          </div>
          <div className="panel">
            <table>
              <thead>
                <tr><th>Type</th><th>Resource</th><th>Risk</th><th>Score</th><th>Reasons</th><th>Recommendations</th></tr>
              </thead>
              <tbody>
                {result.resources.map((resource) => (
                  <tr key={`${resource.resource_type}:${resource.resource_id}`}>
                    <td>{resource.resource_type}</td>
                    <td>{resource.resource_name}</td>
                    <td><StatusBadge status={resource.risk_level} /></td>
                    <td>{resource.risk_score}</td>
                    <td className="small">{resource.reasons.join("; ")}</td>
                    <td className="small muted">{resource.recommendations.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
