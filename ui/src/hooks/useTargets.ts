import * as React from "react";
import { useMeta } from "@/hooks/useMeta";
import type { SourceSpec, TargetSpec } from "@/types";

export interface TargetsState {
  /** Registered targets in registry order (empty until /api/meta has answered). */
  targets: TargetSpec[];
  /** Registered sources. */
  sources: SourceSpec[];
  loading: boolean;
  error: string | null;
  specOf: (name: string) => TargetSpec | undefined;
  /** Human label for a target name; falls back to the upper-cased name while loading or for unknown targets. */
  labelOf: (name: string | null | undefined) => string;
  /** Connection-catalog provider a target deploys through (the target name when the registry says nothing). */
  providerOf: (name: string) => string;
  /** The source that accepts a discovery schema name, if any. */
  sourceForSchema: (schema: string | null | undefined) => SourceSpec | undefined;
}

/** Label for a target name when the registry is not available: the bare name, upper-cased. */
export function fallbackTargetLabel(name: string | null | undefined): string {
  const key = String(name ?? "").trim();
  return key ? key.toUpperCase() : "—";
}

export function targetLabel(targets: TargetSpec[], name: string | null | undefined): string {
  const key = String(name ?? "").trim().toLowerCase();
  return targets.find((item) => item.name === key)?.label ?? fallbackTargetLabel(name);
}

export function sourceForSchema(sources: SourceSpec[], schema: string | null | undefined): SourceSpec | undefined {
  const key = String(schema ?? "").trim().toLowerCase();
  if (!key) return undefined;
  return sources.find((item) => item.schema_names.some((candidate) => candidate.toLowerCase() === key));
}

/** Registered targets and sources from /api/meta with label helpers. */
export function useTargets(): TargetsState {
  const { meta, loading, error } = useMeta();
  const targets = React.useMemo(() => meta?.targets ?? [], [meta]);
  const sources = React.useMemo(() => meta?.sources ?? [], [meta]);
  return React.useMemo(
    () => ({
      targets,
      sources,
      loading,
      error,
      specOf: (name: string) => targets.find((item) => item.name === String(name ?? "").trim().toLowerCase()),
      labelOf: (name: string | null | undefined) => targetLabel(targets, name),
      providerOf: (name: string) => targets.find((item) => item.name === name)?.connection_provider ?? name,
      sourceForSchema: (schema: string | null | undefined) => sourceForSchema(sources, schema),
    }),
    [targets, sources, loading, error],
  );
}
