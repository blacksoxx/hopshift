import { api } from "@/api";
import type { Meta } from "@/types";

// GET /api/meta describes the server: registered targets and sources, pipeline nodes, feature
// flags. It changes only when the server restarts, so one fetch per page load is shared by every
// component that needs it (run pages, target labels, the wizard).
let metaPromise: Promise<Meta> | null = null;
let cachedMeta: Meta | null = null;

export function loadMeta(): Promise<Meta> {
  if (!metaPromise) {
    const pending = api.meta().then((meta) => {
      cachedMeta = meta;
      return meta;
    });
    pending.catch(() => {
      metaPromise = null;
    });
    metaPromise = pending;
  }
  return metaPromise;
}

/** The last meta payload received, if any (synchronous; lets a remounted page paint instantly). */
export function peekMeta(): Meta | null {
  return cachedMeta;
}

/** Test hook: forget the cached payload so the next loadMeta() fetches again. */
export function resetMetaCache(): void {
  metaPromise = null;
  cachedMeta = null;
}
