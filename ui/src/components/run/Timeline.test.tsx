import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Timeline, stepStates } from "./Timeline";
import { makeRun } from "./test-helpers";
import type { RunEvent } from "@/types";

const NODES = ["ingest", "blocker_parser", "enricher", "cim_mapper", "sizer", "mcp_client", "hcl_generator", "validator", "reporter"];

function event(type: RunEvent["type"], node: string | null = null, ts = "2026-11-09T12:00:00+00:00"): RunEvent {
  return { ts, type, node, summary: {}, messages: [] };
}

const t = (seconds: number) => `2026-11-09T12:00:${String(seconds).padStart(2, "0")}+00:00`;

describe("stepStates", () => {
  it("marks node events done, the paused node pending and later ones pending", () => {
    const events = [event("start", null, t(0)), event("node", "ingest", t(1)), event("node", "blocker_parser", t(2)), event("node", "enricher", t(3)), event("node", "cim_mapper", t(5)), event("paused", "sizer", t(5))];
    const steps = stepStates(NODES, events, makeRun({ status: "paused", paused_before: "sizer" }));
    expect(steps.ingest.state).toBe("done");
    expect(steps.cim_mapper.state).toBe("done");
    expect(steps.cim_mapper.startedAt).toBe(t(3));
    expect(steps.cim_mapper.finishedAt).toBe(t(5));
    expect(steps.sizer.state).toBe("pending");
    expect(steps.sizer.paused).toBe(true);
    expect(steps.reporter.state).toBe("pending");
  });

  it("shows the next pending node as running while the run executes", () => {
    const events = [event("start"), event("node", "ingest"), event("node", "blocker_parser")];
    const steps = stepStates(NODES, events, makeRun({ status: "running", paused_before: null, pause_point: null, executing: true }));
    expect(steps.blocker_parser.state).toBe("done");
    expect(steps.enricher.state).toBe("running");
    expect(steps.cim_mapper.state).toBe("pending");
  });

  it("fails the node that was executing on an error event", () => {
    const events = [event("start"), event("node", "ingest"), event("error")];
    const steps = stepStates(NODES, events, makeRun({ status: "failed", paused_before: null, pause_point: null, error: "boom" }));
    expect(steps.ingest.state).toBe("done");
    expect(steps.blocker_parser.state).toBe("failed");
    expect(steps.enricher.state).toBe("pending");
  });

  it("keeps nodes before a rerun done and resets the rest", () => {
    const events = [event("start"), ...NODES.map((node) => event("node", node)), event("end"), event("rerun", "sizer"), event("node", "sizer")];
    const steps = stepStates(NODES, events, makeRun({ status: "running", paused_before: null, pause_point: null, executing: true }));
    expect(steps.cim_mapper.state).toBe("done");
    expect(steps.sizer.state).toBe("done");
    expect(steps.mcp_client.state).toBe("running");
    expect(steps.reporter.state).toBe("pending");
  });

  it("skips the remaining nodes when the run is cancelled", () => {
    const events = [event("start"), event("node", "ingest"), event("cancelled", "blocker_parser")];
    const steps = stepStates(NODES, events, makeRun({ status: "cancelled", paused_before: null, pause_point: null }));
    expect(steps.ingest.state).toBe("done");
    expect(steps.blocker_parser.state).toBe("skipped");
    expect(steps.reporter.state).toBe("skipped");
  });

  it("marks everything done after a successful end", () => {
    const events = [event("start"), ...NODES.map((node) => event("node", node)), event("end")];
    const steps = stepStates(NODES, events, makeRun({ status: "succeeded", paused_before: null, pause_point: null }));
    expect(NODES.every((node) => steps[node].state === "done")).toBe(true);
  });
});

describe("Timeline", () => {
  it("renders one step per node with its state attribute", () => {
    const events = [event("start"), event("node", "ingest"), event("node", "blocker_parser")];
    render(<Timeline nodes={NODES} events={events} run={makeRun({ status: "running", paused_before: null, pause_point: null, executing: true })} />);
    expect(screen.getByTestId("step-ingest")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("step-enricher")).toHaveAttribute("data-state", "running");
    expect(screen.getByTestId("step-reporter")).toHaveAttribute("data-state", "pending");
    expect(screen.getAllByRole("listitem")).toHaveLength(NODES.length);
  });

  it("flags the paused node", () => {
    const events = [event("start"), event("node", "ingest"), event("paused", "blocker_parser")];
    render(<Timeline nodes={NODES} events={events} run={makeRun({ status: "paused", paused_before: "blocker_parser" })} />);
    expect(screen.getByTestId("step-blocker_parser")).toHaveAttribute("data-paused", "true");
    expect(screen.getByTestId("step-blocker_parser")).toHaveAttribute("data-state", "pending");
  });
});
