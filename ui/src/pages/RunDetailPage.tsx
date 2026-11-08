import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { TERMINAL_STATUSES, api, subscribeEvents } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import type { Artifact, Cim, ComputeUnit, Meta, RunEvent, RunRecord, RunState } from "../types";

type Tab = "overview" | "cim" | "artifacts" | "log";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<RunRecord | null>(null);
  const [state, setState] = useState<RunState | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rerunNode, setRerunNode] = useState("sizer");
  const [streamGeneration, setStreamGeneration] = useState(0);
  const unsubscribe = useRef<(() => void) | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [record, loadedEvents] = await Promise.all([api.getRun(runId), api.events(runId)]);
      setRun(record);
      setEvents(loadedEvents);
      if (record.status === "paused" || TERMINAL_STATUSES.has(record.status)) {
        setState(await api.getState(runId));
      }
      setError(null);
    } catch (exc) {
      setError((exc as Error).message);
    }
  }, [runId]);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => undefined);
    void refresh();
  }, [refresh]);

  // Live updates while the run executes: server-sent events for the log, plus a status poll
  // as a safety net so a dropped stream can never leave the page stuck on "running".
  const executing = run?.status === "running" || run?.executing === true;
  useEffect(() => {
    if (!executing) return;
    unsubscribe.current?.();
    unsubscribe.current = subscribeEvents(
      runId,
      events.length,
      (event) => setEvents((current) => [...current, event]),
      (status) => {
        void refresh();
        if (status === "disconnected") setTimeout(() => setStreamGeneration((n) => n + 1), 2000);
      },
    );
    return () => unsubscribe.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [executing, runId, streamGeneration]);

  useEffect(() => {
    if (!executing) return;
    const timer = setInterval(() => {
      api.getRun(runId)
        .then((record) => {
          const stillExecuting = record.status === "running" || record.executing === true;
          if (!stillExecuting || record.status !== run?.status) void refresh();
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [executing, runId, run?.status, refresh]);

  async function act(action: () => Promise<unknown>, label: string) {
    try {
      await action();
      setNotice(label);
      await refresh();
    } catch (exc) {
      setError((exc as Error).message);
    }
  }

  if (error && !run) return <div className="alert bad">{error}</div>;
  if (!run) return <div className="empty">Loading…</div>;

  const nodes = meta?.nodes ?? [];
  const paused = run.status === "paused" && !run.executing;
  const terminal = TERMINAL_STATUSES.has(run.status) && !run.executing;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 style={{ marginBottom: 4 }}>Run {run.run_id}</h1>
          <div className="small muted">{run.cloud} · {run.mode} · {run.input_filename} · created {run.created_at}</div>
        </div>
        <div className="actions">
          <StatusBadge status={run.executing ? "running" : run.status} />
          {paused && (
            <button className="primary" onClick={() => act(() => api.resume(run.run_id), `Resumed from ${run.pause_point}`)} data-testid="approve">
              {run.pause_point === "approve_output" ? "Approve and write output" : "Approve and continue"}
            </button>
          )}
          {terminal && nodes.length > 0 && (
            <>
              <select value={rerunNode} onChange={(e) => setRerunNode(e.target.value)} data-testid="rerun-node">
                {nodes.map((node) => <option key={node} value={node}>{node}</option>)}
              </select>
              <button onClick={() => act(() => api.rerun(run.run_id, rerunNode), `Re-running from ${rerunNode}`)} data-testid="rerun">Re-run from</button>
            </>
          )}
          <button onClick={() => void refresh()}>Refresh</button>
        </div>
      </div>

      {error && <div className="alert bad">{error}</div>}
      {notice && <div className="alert ok">{notice}</div>}
      {run.status === "paused" && (
        <div className="alert warn" data-testid="paused-banner">
          Paused at <strong>{run.pause_point ?? run.paused_before}</strong>
          {run.pause_point === "review_cim" && " — review or edit the CIM below, then approve."}
          {run.pause_point === "approve_output" && " — generated files are validated; approve to write them."}
        </div>
      )}
      {run.error && <div className="alert bad">{run.error}</div>}

      <div className="panel">
        <Timeline nodes={nodes} events={events} run={run} />
      </div>

      <div className="tabs">
        {(["overview", "cim", "artifacts", "log"] as Tab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)} data-testid={`tab-${item}`}>{item}</button>
        ))}
      </div>

      {tab === "overview" && <Overview state={state} events={events} />}
      {tab === "cim" && (
        <CimEditor
          runId={run.run_id}
          cim={state?.values.sized_cim ?? state?.values.cim ?? null}
          editable={paused && run.pause_point === "review_cim"}
          onSaved={() => act(async () => undefined, "CIM saved into the paused run")}
        />
      )}
      {tab === "artifacts" && <Artifacts runId={run.run_id} active={terminal} />}
      {tab === "log" && <Log events={events} />}
    </div>
  );
}

function Overview({ state, events }: { state: RunState | null; events: RunEvent[] }) {
  const last = [...events].reverse().find((event) => event.type === "node" || event.type === "end");
  const summary = (last?.summary ?? {}) as Record<string, unknown>;
  const validation = state?.values.validation_result;
  const quarantine = state?.values.quarantine_queue ?? [];
  const cells: [string, unknown][] = [
    ["compute units", summary.compute_units],
    ["quarantined", summary.quarantined],
    ["HCL files", summary.hcl_files],
    ["validation", summary.validation_passed === undefined ? "–" : summary.validation_passed ? "passed" : "failed"],
  ];
  return (
    <div>
      <div className="stats">
        {cells.map(([label, value]) => (
          <div className="stat" key={label}>
            <div className="label">{label}</div>
            <div className="value">{value === undefined ? "–" : String(value)}</div>
          </div>
        ))}
      </div>
      {validation && ((validation.errors?.length ?? 0) > 0 || (validation.warnings?.length ?? 0) > 0) ? (
        <div className="panel">
          <h2>Validation</h2>
          {(validation.errors ?? []).map((item, index) => <div key={`e${index}`} className="alert bad"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{item}</pre></div>)}
          {(validation.warnings ?? []).map((item, index) => <div key={`w${index}`} className="alert warn">{item}</div>)}
        </div>
      ) : null}
      <div className="panel">
        <h2>Quarantine</h2>
        {quarantine.length === 0 ? (
          <div className="muted small">No quarantined VMs{state ? "" : " (state loads when the run pauses or ends)"}.</div>
        ) : (
          <table data-testid="quarantine-table">
            <thead><tr><th>VM</th><th>Stage</th><th>Reasons</th></tr></thead>
            <tbody>
              {quarantine.map((item) => (
                <tr key={`${item.stage}:${item.compute_unit_id}`}>
                  <td>{item.compute_unit_name}</td>
                  <td>{item.stage}</td>
                  <td className="small">{item.reasons.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function CimEditor({ runId, cim, editable, onSaved }: { runId: string; cim: Cim | null; editable: boolean; onSaved: () => void }) {
  const [draft, setDraft] = useState<Cim | null>(cim);
  const [raw, setRaw] = useState(false);
  const [rawText, setRawText] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setDraft(cim); setRawText(cim ? JSON.stringify(cim, null, 2) : ""); }, [cim]);

  if (!draft) return <div className="panel"><div className="empty">The CIM is available once the run has paused or finished.</div></div>;

  function updateUnit(index: number, patch: Partial<ComputeUnit>) {
    setDraft((current) => {
      if (!current) return current;
      const units = current.compute_units.map((unit, i) => (i === index ? { ...unit, ...patch } : unit));
      return { ...current, compute_units: units };
    });
  }

  async function save() {
    try {
      const payload = raw ? (JSON.parse(rawText) as Cim) : draft;
      await api.patchState(runId, { sized_cim: payload });
      setError(null);
      onSaved();
    } catch (exc) {
      setError((exc as Error).message);
    }
  }

  const switches = draft.network_topology.distributed_switches;
  return (
    <div>
      {error && <div className="alert bad">{error}</div>}
      <div className="panel">
        <div className="page-header">
          <div className="small muted">
            Source {draft.source.platform} · {draft.source.name} · target {draft.target_provider} · {draft.clusters.length} cluster(s) · {switches.length} switch(es)
          </div>
          <div className="actions">
            <label className="small"><input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} /> raw JSON</label>
            {editable && <button className="primary" onClick={() => void save()} data-testid="save-cim">Save CIM</button>}
          </div>
        </div>
        {!editable && <div className="muted small">Read-only: the CIM can be edited while the run is paused at review_cim.</div>}
        {raw ? (
          <textarea className="json" value={rawText} onChange={(e) => setRawText(e.target.value)} readOnly={!editable} data-testid="cim-json" />
        ) : (
          <table data-testid="cim-table">
            <thead><tr><th>Name</th><th>vCPU</th><th>RAM MB</th><th>Cluster</th><th>Status</th><th>Guest OS</th><th>Image ref</th><th>NICs</th><th>Disks</th></tr></thead>
            <tbody>
              {draft.compute_units.map((unit, index) => (
                <tr key={unit.id}>
                  <td>{editable ? <input value={unit.name} onChange={(e) => updateUnit(index, { name: e.target.value })} data-testid={`unit-name-${index}`} /> : unit.name}</td>
                  <td>{editable ? <input type="number" min={1} value={unit.vcpus} onChange={(e) => updateUnit(index, { vcpus: Number(e.target.value) })} /> : unit.vcpus}</td>
                  <td>{editable ? <input type="number" min={1} value={unit.ram_mb} onChange={(e) => updateUnit(index, { ram_mb: Number(e.target.value) })} /> : unit.ram_mb}</td>
                  <td>{unit.cluster_ref ?? <span className="muted">–</span>}</td>
                  <td><StatusBadge status={unit.migration_status} />{unit.blockers.length > 0 && <div className="small muted">{unit.blockers.join(", ")}</div>}</td>
                  <td className="small">{unit.guest_os ?? "–"}</td>
                  <td>{editable ? <input value={unit.image_ref ?? ""} placeholder="ami-… / image id" onChange={(e) => updateUnit(index, { image_ref: e.target.value || null })} /> : (unit.image_ref ?? <span className="muted">–</span>)}</td>
                  <td className="small">{unit.nics.map((nic) => nic.port_group_ref).join(", ")}</td>
                  <td className="small">{unit.storage_volumes.map((volume) => `${volume.size_gb} GB`).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="panel">
        <h2>Network topology</h2>
        {switches.length === 0 ? <div className="muted small">No switches.</div> : (
          <table>
            <thead><tr><th>Switch</th><th>Segments (VLAN)</th></tr></thead>
            <tbody>
              {switches.map((sw) => (
                <tr key={sw.name}><td>{sw.name}</td><td className="small">{sw.port_groups.map((pg) => `${pg.name}${pg.vlan_id ? ` (${pg.vlan_id})` : ""}`).join(", ")}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Artifacts({ runId, active }: { runId: string; active: boolean }) {
  const [files, setFiles] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  useEffect(() => {
    api.artifacts(runId).then(setFiles).catch(() => setFiles([]));
  }, [runId, active]);
  useEffect(() => {
    if (!selected) return;
    api.artifact(runId, selected).then(setContent).catch((exc: Error) => setContent(exc.message));
  }, [runId, selected]);
  const sorted = useMemo(() => [...files].sort((a, b) => a.path.localeCompare(b.path)), [files]);
  if (sorted.length === 0) return <div className="panel"><div className="empty">No artifacts yet. Files are written after the output is approved.</div></div>;
  return (
    <div className="panel file-list" data-testid="artifacts">
      <ul>
        {sorted.map((file) => (
          <li key={file.path} className={file.path === selected ? "active" : ""} onClick={() => setSelected(file.path)} data-testid="artifact-item">{file.path} <span className="muted">({file.size} B)</span></li>
        ))}
      </ul>
      <pre className="code" data-testid="artifact-content">{selected ? content : "Select a file."}</pre>
    </div>
  );
}

function Log({ events }: { events: RunEvent[] }) {
  return (
    <div className="log" data-testid="log">
      {events.map((event, index) => (
        <div key={index}>
          <span className="ts">{event.ts.replace("T", " ").replace("+00:00", "")}</span>
          <span className="node">{event.node ?? event.type}</span>
          <span className={event.type === "error" ? "err" : ""}>
            {event.type !== "node" ? `[${event.type}] ` : ""}
            {event.messages.length > 0 ? event.messages.join(" | ") : JSON.stringify(event.summary)}
          </span>
        </div>
      ))}
    </div>
  );
}
