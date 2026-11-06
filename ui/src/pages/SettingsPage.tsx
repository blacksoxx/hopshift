import { useEffect, useState } from "react";
import { api } from "../api";
import type { Meta } from "../types";

export function SettingsPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.config(), api.meta()])
      .then(([loadedConfig, loadedMeta]) => { setConfig(loadedConfig); setMeta(loadedMeta); })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  return (
    <div>
      <h1>Settings</h1>
      {error && <div className="alert bad">{error}</div>}
      <p className="muted small">Effective configuration read from config.yaml on the server. Editing is a later step; change the file and restart the API.</p>
      {meta && (
        <div className="panel small">
          <div><strong>Pipeline nodes:</strong> {meta.nodes.join(" → ")}</div>
          <div><strong>Default pause points:</strong> {meta.default_pause_points.join(", ") || "none"}</div>
        </div>
      )}
      {config && <pre className="code" data-testid="config-json">{JSON.stringify(config, null, 2)}</pre>}
    </div>
  );
}
