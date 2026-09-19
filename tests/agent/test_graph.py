from __future__ import annotations

from agent.graph import build_graph


def test_build_graph_compiles() -> None:
    compiled = build_graph()
    assert compiled is not None


def test_reporter_always_runs_after_validator() -> None:
    """Regression: failed validations used to route to END, so no quarantine report or
    review notes were written for failed runs."""
    edges = {(edge.source, edge.target) for edge in build_graph().get_graph().edges}

    assert ("validator", "reporter") in edges
    assert ("validator", "__end__") not in edges
    assert ("reporter", "__end__") in edges


def test_graph_is_linear_in_expected_order() -> None:
    edges = {(edge.source, edge.target) for edge in build_graph().get_graph().edges}
    expected_chain = [
        "__start__",
        "ingest",
        "blocker_parser",
        "enricher",
        "cim_mapper",
        "sizer",
        "mcp_client",
        "hcl_generator",
        "validator",
        "reporter",
        "__end__",
    ]
    for source, target in zip(expected_chain, expected_chain[1:]):
        assert (source, target) in edges, f"missing edge {source} -> {target}"
