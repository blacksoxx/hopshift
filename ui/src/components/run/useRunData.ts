import * as React from "react";
import { TERMINAL_STATUSES, api, subscribeEvents } from "@/api";
import { loadMeta, peekMeta } from "@/lib/meta";
import type { Meta, RunEvent, RunRecord, RunState } from "@/types";

export { loadMeta };

interface Snapshot {
  run: RunRecord | null;
  events: RunEvent[];
  state: RunState | null;
}

// The app shell remounts the page on every path change, and tabs live in the path. A small
// cache keyed by run id lets the remounted page paint instantly and resume the stream from
// where it was instead of flashing skeletons on each tab switch.
const snapshots = new Map<string, Snapshot>();

export function isExecuting(run: RunRecord | null): boolean {
  return !!run && (run.status === "running" || run.executing === true);
}

export interface RunData {
  run: RunRecord | null;
  events: RunEvent[];
  state: RunState | null;
  meta: Meta | null;
  error: string | null;
  loading: boolean;
  executing: boolean;
  refresh: () => Promise<void>;
  setRun: (run: RunRecord) => void;
}

/** Run record, events and state with live updates while the run executes. */
export function useRunData(runId: string): RunData {
  const cached = snapshots.get(runId);
  const [run, setRunState] = React.useState<RunRecord | null>(cached?.run ?? null);
  const [events, setEvents] = React.useState<RunEvent[]>(cached?.events ?? []);
  const [state, setState] = React.useState<RunState | null>(cached?.state ?? null);
  const [meta, setMeta] = React.useState<Meta | null>(peekMeta());
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(!cached?.run);
  const [generation, setGeneration] = React.useState(0);
  const alive = React.useRef(true);
  const eventsRef = React.useRef(events);
  eventsRef.current = events;

  React.useEffect(() => {
    snapshots.set(runId, { run, events, state });
  }, [runId, run, events, state]);

  const refresh = React.useCallback(async () => {
    try {
      const [record, loadedEvents] = await Promise.all([api.getRun(runId), api.events(runId)]);
      if (!alive.current) return;
      setRunState(record);
      setEvents(loadedEvents);
      if (record.status === "paused" || TERMINAL_STATUSES.has(record.status)) {
        const loadedState = await api.getState(runId);
        if (!alive.current) return;
        setState(loadedState);
      }
      setError(null);
    } catch (exc) {
      if (alive.current) setError((exc as Error).message || "Request failed");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [runId]);

  React.useEffect(() => {
    alive.current = true;
    loadMeta()
      .then((loaded) => alive.current && setMeta(loaded))
      .catch(() => undefined);
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  const executing = isExecuting(run);
  const status = run?.status;
  const updatedAt = run?.updated_at;
  const eventCount = run?.event_count;

  // Server-sent events while the run executes; resubscribe after a drop.
  React.useEffect(() => {
    if (!executing) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribeEvents(
      runId,
      eventsRef.current.length,
      (event) => setEvents((current) => [...current, event]),
      (result) => {
        void refresh();
        if (result === "disconnected") timer = setTimeout(() => alive.current && setGeneration((n) => n + 1), 2000);
      },
    );
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, [executing, runId, generation, refresh]);

  // Status poll: 2 s while executing (safety net for a dropped stream), slower otherwise so a
  // change made elsewhere (approval, cancel, re-run) shows up without a manual reload.
  React.useEffect(() => {
    if (!status) return;
    const interval = executing ? 2000 : TERMINAL_STATUSES.has(status) ? 30000 : 10000;
    const timer = setInterval(() => {
      api.getRun(runId)
        .then((record) => {
          if (!alive.current) return;
          const changed = record.status !== status || isExecuting(record) !== executing || record.updated_at !== updatedAt || record.event_count !== eventCount;
          if (changed) void refresh();
        })
        .catch(() => undefined);
    }, interval);
    return () => clearInterval(timer);
  }, [executing, runId, status, updatedAt, eventCount, refresh]);

  const setRun = React.useCallback((record: RunRecord) => setRunState(record), []);

  return { run, events, state, meta, error, loading, executing, refresh, setRun };
}
