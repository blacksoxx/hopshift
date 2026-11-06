import type { RunEvent, RunRecord } from "../types";

export type StepState = "pending" | "done" | "active" | "paused" | "error";

export function stepStates(nodes: string[], events: RunEvent[], run: RunRecord | null): Record<string, StepState> {
  const states: Record<string, StepState> = {};
  for (const node of nodes) states[node] = "pending";

  // Only the most recent execution counts: a re-run replays from a node.
  let lastStart = 0;
  events.forEach((event, index) => {
    if (event.type === "start" || event.type === "rerun") lastStart = index;
  });
  for (const event of events.slice(lastStart)) {
    if (event.type === "node" && event.node) states[event.node] = "done";
    if (event.type === "error") {
      const next = nodes.find((node) => states[node] === "pending");
      if (next) states[next] = "error";
    }
  }
  if (run?.status === "paused" && run.paused_before) states[run.paused_before] = "paused";
  if (run?.status === "running") {
    const next = nodes.find((node) => states[node] === "pending");
    if (next) states[next] = "active";
  }
  return states;
}

export function Timeline({ nodes, events, run }: { nodes: string[]; events: RunEvent[]; run: RunRecord | null }) {
  const states = stepStates(nodes, events, run);
  return (
    <div className="timeline" data-testid="timeline">
      {nodes.map((node) => (
        <div key={node} className={`step ${states[node]}`} data-testid={`step-${node}`} data-state={states[node]}>
          <span className="dot" />
          <span>{node}</span>
        </div>
      ))}
    </div>
  );
}
