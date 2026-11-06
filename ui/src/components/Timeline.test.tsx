import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Timeline, stepStates } from "./Timeline";
import type { RunEvent, RunRecord } from "../types";

const NODES = ["ingest", "blocker_parser", "enricher", "cim_mapper", "sizer", "mcp_client", "hcl_generator", "validator", "reporter"];

function event(type: RunEvent["type"], node: string | null = null): RunEvent {
  return { ts: "2026-11-06T10:00:00+00:00", type, node, summary: {}, messages: [] };
}

function run(status: RunRecord["status"], paused_before: string | null = null): RunRecord {
  return {
    run_id: "r1", created_at: "", updated_at: "", status, cloud: "aws", mode: "deterministic",
    options: { cloud: "aws", environment: "dev", owner: "o", skip_validation: false, skip_opa: false, no_mcp: false, dry_run: false, pause_points: [] },
    input_filename: "d.json", run_dir: "", paused_before, pause_point: paused_before ? "review_cim" : null, error: null, event_count: 0,
  };
}

describe("stepStates", () => {
  it("marks completed nodes done, the paused node paused and the rest pending", () => {
    const events = [event("start"), event("node", "ingest"), event("node", "blocker_parser"), event("paused", "enricher")];
    const states = stepStates(NODES, events, run("paused", "enricher"));
    expect(states.ingest).toBe("done");
    expect(states.blocker_parser).toBe("done");
    expect(states.enricher).toBe("paused");
    expect(states.reporter).toBe("pending");
  });

  it("only counts events since the last re-run", () => {
    const events = [event("start"), event("node", "ingest"), event("node", "sizer"), event("end"), event("rerun", "sizer"), event("node", "sizer")];
    const states = stepStates(NODES, events, run("running"));
    expect(states.ingest).toBe("done"); // kept from the checkpoint the re-run forked from
    expect(states.cim_mapper).toBe("done");
    expect(states.sizer).toBe("done");
    expect(states.mcp_client).toBe("active");
    expect(states.reporter).toBe("pending");
  });

  it("marks the node after an error as errored", () => {
    const states = stepStates(NODES, [event("start"), event("node", "ingest"), event("error")], run("error"));
    expect(states.blocker_parser).toBe("error");
  });
});

describe("Timeline", () => {
  it("renders one step per node with its state", () => {
    render(<Timeline nodes={NODES} events={[event("start"), event("node", "ingest")]} run={run("running")} />);
    expect(screen.getByTestId("step-ingest")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("step-blocker_parser")).toHaveAttribute("data-state", "active");
    expect(screen.getAllByTestId(/^step-/)).toHaveLength(NODES.length);
  });
});
