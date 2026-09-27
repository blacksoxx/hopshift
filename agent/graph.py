from __future__ import annotations

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


def build_graph() -> StateGraph:
    """Create and compile the LangGraph for the vmware-migration-agent pipeline.

    The reporter always runs, including after a failed validation, so that the
    quarantine report and review notes are written for every run. The reporter
    decides what is safe to write based on validation_result and status.
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

    return workflow.compile()


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
