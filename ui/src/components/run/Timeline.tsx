import { motion } from "motion/react";
import { Check, Minus, Pause, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/format";
import type { RunEvent, RunRecord } from "@/types";

export type StepState = "pending" | "running" | "done" | "failed" | "skipped";

export interface StepInfo {
  state: StepState;
  startedAt: string | null;
  finishedAt: string | null;
  /** The run is paused right before this node. */
  paused: boolean;
}

/**
 * Derive one entry per pipeline node from the event log plus the run record.
 *
 * Rules: node events mark a node done; a `rerun` resets the rerun node and everything after it
 * (earlier nodes keep their checkpointed result); an `error` fails the node that was executing;
 * `cancelled` skips whatever is left. The run record settles the live cases: the next pending
 * node is running while the run executes, and the node named in `paused_before` is flagged.
 */
export function stepStates(nodes: string[], events: RunEvent[], run: RunRecord | null): Record<string, StepInfo> {
  const steps: Record<string, StepInfo> = {};
  for (const node of nodes) steps[node] = { state: "pending", startedAt: null, finishedAt: null, paused: false };
  const index = (node: string | null | undefined) => (node ? nodes.indexOf(node) : -1);
  const reset = (from: number) => {
    for (const node of nodes.slice(Math.max(from, 0))) steps[node] = { state: "pending", startedAt: null, finishedAt: null, paused: false };
  };
  const firstPending = () => nodes.find((node) => steps[node].state === "pending");

  let segmentStart: string | null = null;
  for (const event of events) {
    switch (event.type) {
      case "start":
        reset(0);
        segmentStart = event.ts;
        break;
      case "rerun":
        reset(index(event.node) === -1 ? 0 : index(event.node));
        segmentStart = event.ts;
        break;
      case "resume":
        segmentStart = event.ts;
        break;
      case "node": {
        if (!event.node || !(event.node in steps)) break;
        steps[event.node] = { state: "done", startedAt: segmentStart, finishedAt: event.ts, paused: false };
        segmentStart = event.ts;
        break;
      }
      case "error": {
        const node = firstPending();
        if (node) steps[node] = { state: "failed", startedAt: segmentStart, finishedAt: event.ts, paused: false };
        break;
      }
      case "cancelled": {
        const from = index(event.node) === -1 ? nodes.findIndex((node) => steps[node].state === "pending") : index(event.node);
        if (from === -1) break;
        for (const node of nodes.slice(from)) if (steps[node].state === "pending") steps[node] = { ...steps[node], state: "skipped" };
        break;
      }
      default:
        break;
    }
  }

  if (!run) return steps;
  const executing = run.status === "running" || run.executing === true;
  if (executing) {
    const node = firstPending();
    if (node) steps[node] = { ...steps[node], state: "running", startedAt: steps[node].startedAt ?? segmentStart ?? events[events.length - 1]?.ts ?? null };
  } else if (run.status === "paused" && run.paused_before && steps[run.paused_before]) {
    steps[run.paused_before] = { ...steps[run.paused_before], state: steps[run.paused_before].state === "done" ? "done" : "pending", paused: true };
  } else if (run.status === "cancelled") {
    for (const node of nodes) if (steps[node].state === "pending" || steps[node].state === "running") steps[node] = { ...steps[node], state: "skipped" };
  } else if (run.status === "failed" || run.status === "error") {
    if (!nodes.some((node) => steps[node].state === "failed")) {
      const node = firstPending();
      if (node) steps[node] = { ...steps[node], state: "failed" };
    }
  }
  return steps;
}

const ACRONYMS = new Set(["cim", "hcl", "mcp", "vm", "api"]);

/** "cim_mapper" -> "CIM mapper"; acronyms stay upper-case, the rest reads as a sentence. */
export function nodeLabel(node: string): string {
  return node
    .split("_")
    .map((part, index) => (ACRONYMS.has(part) ? part.toUpperCase() : index === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ");
}

/** Event timestamps have second precision, so anything under a second is simply not shown. */
function duration(info: StepInfo): string | null {
  if (!info.startedAt || !info.finishedAt) return null;
  const ms = new Date(info.finishedAt).getTime() - new Date(info.startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 1000) return null;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

const DOT: Record<StepState, string> = {
  pending: "border-border bg-card text-muted-foreground",
  running: "border-info bg-info/10 text-info",
  done: "border-success bg-success text-primary-foreground",
  failed: "border-destructive bg-destructive text-destructive-foreground",
  skipped: "border-border bg-muted text-muted-foreground",
};

function StepDot({ info }: { info: StepInfo }) {
  if (info.paused) {
    return (
      <span className="flex size-6 items-center justify-center rounded-full border-2 border-warning bg-warning/15 text-warning">
        <Pause className="size-3" strokeWidth={3} />
      </span>
    );
  }
  return (
    <span className={cn("relative flex size-6 items-center justify-center rounded-full border-2", DOT[info.state])}>
      {info.state === "running" ? (
        <>
          <motion.span
            className="absolute inset-0 rounded-full border-2 border-info"
            animate={{ scale: [1, 1.7], opacity: [0.7, 0] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }}
            aria-hidden
          />
          <span className="size-2 rounded-full bg-info" />
        </>
      ) : info.state === "done" ? (
        <Check className="size-3.5" strokeWidth={3} />
      ) : info.state === "failed" ? (
        <X className="size-3.5" strokeWidth={3} />
      ) : info.state === "skipped" ? (
        <Minus className="size-3" strokeWidth={3} />
      ) : (
        <span className="size-1.5 rounded-full bg-current opacity-40" />
      )}
    </span>
  );
}

export function Timeline({ nodes, events, run, className }: { nodes: string[]; events: RunEvent[]; run: RunRecord | null; className?: string }) {
  const steps = stepStates(nodes, events, run);
  return (
    <ol className={cn("flex min-w-max items-start gap-0 sm:min-w-0", className)} data-testid="timeline" aria-label="Pipeline progress">
      {nodes.map((node, position) => {
        const info = steps[node];
        const previous = position > 0 ? steps[nodes[position - 1]] : null;
        const label = nodeLabel(node);
        const timing = duration(info);
        const title = [
          `${label}: ${info.paused ? "paused here" : info.state}`,
          info.startedAt ? `started ${formatTime(info.startedAt)}` : null,
          info.finishedAt ? `finished ${formatTime(info.finishedAt)}` : null,
          timing ? `took ${timing}` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        return (
          <li
            key={node}
            className="group/step relative flex min-w-[76px] flex-1 flex-col items-center sm:min-w-0"
            data-testid={`step-${node}`}
            data-state={info.state}
            data-paused={info.paused ? "true" : undefined}
            title={title}
          >
            {position > 0 ? (
              <span
                aria-hidden
                className={cn(
                  "absolute left-0 right-1/2 top-3 h-0.5 -translate-y-1/2",
                  previous?.state === "done" ? "bg-success/60" : previous?.state === "failed" ? "bg-destructive/50" : "bg-border",
                )}
              />
            ) : null}
            {position < nodes.length - 1 ? (
              <span aria-hidden className={cn("absolute left-1/2 right-0 top-3 h-0.5 -translate-y-1/2", info.state === "done" ? "bg-success/60" : info.state === "failed" ? "bg-destructive/50" : "bg-border")} />
            ) : null}
            <span className="relative z-[1]">
              <StepDot info={info} />
            </span>
            <span
              className={cn(
                "mt-2 max-w-full truncate px-1 text-center text-[11.5px] font-medium leading-tight",
                info.state === "pending" && !info.paused ? "text-muted-foreground" : "text-foreground",
                info.state === "skipped" && "text-muted-foreground line-through decoration-border",
              )}
            >
              {label}
            </span>
            <span className="mt-0.5 hidden h-4 text-[10.5px] tabular text-muted-foreground sm:block">
              {info.state === "running" ? (
                <span className="text-info">running…</span>
              ) : info.paused ? (
                <span className="text-warning">paused</span>
              ) : info.finishedAt ? (
                <>
                  {formatTime(info.finishedAt)}
                  {timing ? <span className="opacity-70"> · {timing}</span> : null}
                </>
              ) : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
