import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import type { RunRecord } from "../types";

export function RunsPage() {
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setRuns(await api.listRuns());
      setError(null);
    } catch (exc) {
      setError((exc as Error).message);
    }
  }

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div>
      <div className="page-header">
        <h1>Runs</h1>
        <Link className="button primary" to="/runs/new">New run</Link>
      </div>
      {error && <div className="alert bad">{error}</div>}
      <div className="panel">
        {runs === null ? (
          <div className="empty">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="empty">No runs yet. Start one from "New run".</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Cloud</th>
                <th>Mode</th>
                <th>Input</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} data-testid="run-row">
                  <td><Link to={`/runs/${run.run_id}`}>{run.run_id}</Link></td>
                  <td>
                    <StatusBadge status={run.status} />
                    {run.pause_point && <span className="small muted"> at {run.pause_point}</span>}
                  </td>
                  <td>{run.cloud}</td>
                  <td>{run.mode}</td>
                  <td className="small">{run.input_filename}</td>
                  <td className="small muted">{run.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
