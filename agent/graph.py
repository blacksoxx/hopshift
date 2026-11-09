from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent.nodes.assess_reporter import assess_reporter
from agent.nodes.blocker_parser import blocker_parser
from agent.nodes.cim_mapper import cim_mapper
from agent.nodes.enricher import enricher
from agent.nodes.hcl_generator import hcl_generator
from agent.nodes.ingest import ingest
from agent.nodes.mcp_client import mcp_client
from agent.nodes.reporter import reporter
from agent.nodes.risk_assessor import risk_assessor
from agent.nodes.sizer import sizer
from agent.nodes.validator import validator
from agent.state import MigrationState

NODE_ORDER: tuple[str, ...] = (
    "ingest",
    "blocker_parser",
    "enricher",
    "cim_mapper",
    "sizer",
    "mcp_client",
    "hcl_generator",
    "validator",
    "reporter",
)


def build_graph(
    checkpointer: Any | None = None,
    interrupt_before: Iterable[str] | None = None,
) -> StateGraph:
    """Create and compile the LangGraph for the vmware-migration-agent pipeline.

    The reporter always runs, including after a failed validation, so that the
    quarantine report and review notes are written for every run. The reporter
    decides what is safe to write based on validation_result and status.

    `checkpointer` and `interrupt_before` are used by agent.runtime to pause a run
    before a node (for example before hcl_generator so an operator can review the
    CIM) and to resume or re-run it later.
    """
    workflow = StateGraph(MigrationState)

    workflow.add_node("ingest", ingest)
    workflow.add_node("blocker_parser", blocker_parser)
    workflow.add_node("enricher", enricher)
    workflow.add_node("cim_mapper", cim_mapper)
    workflow.add_node("sizer", sizer)
    workflow.add_node("mcp_client", mcp_client)
    workflow.add_node("hcl_generator", hcl_generator)
    workflow.add_node("validator", validator)
    workflow.add_node("reporter", reporter)

    workflow.add_edge(START, "ingest")
    workflow.add_edge("ingest", "blocker_parser")
    workflow.add_edge("blocker_parser", "enricher")
    workflow.add_edge("enricher", "cim_mapper")
    workflow.add_edge("cim_mapper", "sizer")
    workflow.add_edge("sizer", "mcp_client")
    workflow.add_edge("mcp_client", "hcl_generator")
    workflow.add_edge("hcl_generator", "validator")
    workflow.add_edge("validator", "reporter")
    workflow.add_edge("reporter", END)

    pause_points = [node for node in (interrupt_before or []) if node in NODE_ORDER]
    return workflow.compile(checkpointer=checkpointer, interrupt_before=pause_points)


def build_assess_graph() -> StateGraph:
    """Compile the assessment-only graph.

    Deliberately skips blocker_parser so blocked VMs are assessed (with their reasons)
    instead of being removed from the inventory.
    """
    workflow = StateGraph(MigrationState)

    workflow.add_node("ingest", ingest)
    workflow.add_node("enricher", enricher)
    workflow.add_node("cim_mapper", cim_mapper)
    workflow.add_node("risk_assessor", risk_assessor)
    workflow.add_node("assess_reporter", assess_reporter)

    workflow.add_edge(START, "ingest")
    workflow.add_edge("ingest", "enricher")
    workflow.add_edge("enricher", "cim_mapper")
    workflow.add_edge("cim_mapper", "risk_assessor")
    workflow.add_edge("risk_assessor", "assess_reporter")
    workflow.add_edge("assess_reporter", END)

    return workflow.compile()
