import * as React from "react";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

/**
 * Minimal data hook: runs `loader` on mount and whenever `deps` change; optional polling.
 * `pollMs` can be a function of the current data so pages poll only while something is live.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: React.DependencyList, options: { pollMs?: number | ((data: T | null) => number | null); enabled?: boolean } = {}): AsyncState<T> {
  const { pollMs, enabled = true } = options;
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(enabled);
  const loaderRef = React.useRef(loader);
  loaderRef.current = loader;
  const alive = React.useRef(true);

  const reload = React.useCallback(async () => {
    try {
      const next = await loaderRef.current();
      if (alive.current) {
        setData(next);
        setError(null);
      }
    } catch (exc) {
      if (alive.current) setError((exc as Error).message || "Request failed");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    alive.current = true;
    if (!enabled) {
      setLoading(false);
      return () => {
        alive.current = false;
      };
    }
    setLoading(true);
    void reload();
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  React.useEffect(() => {
    if (!enabled || pollMs === undefined) return;
    const interval = typeof pollMs === "function" ? pollMs(data) : pollMs;
    if (!interval || interval <= 0) return;
    const timer = setInterval(() => void reload(), interval);
    return () => clearInterval(timer);
  }, [enabled, pollMs, data, reload]);

  return { data, error, loading, reload, setData };
}

/** Debounce a changing value (search inputs). */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
