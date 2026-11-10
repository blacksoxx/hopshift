import * as React from "react";
import { loadMeta, peekMeta } from "@/lib/meta";
import type { Meta } from "@/types";

export interface MetaState {
  meta: Meta | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

/** GET /api/meta, fetched once per page load and shared (see lib/meta.ts). */
export function useMeta(): MetaState {
  const [meta, setMeta] = React.useState<Meta | null>(() => peekMeta());
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(meta === null);
  const alive = React.useRef(true);

  const reload = React.useCallback(async () => {
    try {
      const next = await loadMeta();
      if (alive.current) {
        setMeta(next);
        setError(null);
      }
    } catch (exc) {
      if (alive.current) setError((exc as Error).message || "Could not load the server description");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    alive.current = true;
    void reload();
    return () => {
      alive.current = false;
    };
  }, [reload]);

  return { meta, loading, error, reload };
}
