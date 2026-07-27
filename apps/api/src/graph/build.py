"""Assemble and compile the TicketWarden StateGraph.

``compile_graph`` takes an optional :class:`LLMClient` — production omits it
and gets the configured provider client; tests pass a scripted fake.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.graph.edges import route_after_review
from src.graph.llm import LLMClient, build_llm_client
from src.graph.nodes import (
    make_classifier,
    make_researcher,
    make_responder,
    make_reviewer,
)
from src.graph.state import CaseState
from src.observability.tracing import configure_tracing


def compile_graph(llm: LLMClient | None = None):
    """Build the Classifier -> Researcher -> Responder -> Reviewer graph."""
    # Idempotent no-op when tracing is off; called here too so graphs built
    # outside the FastAPI lifespan (tests, scripts) still get traced.
    configure_tracing()

    client = llm or build_llm_client()

    graph = StateGraph(CaseState)
    # Plain callables returning partial-state dicts are the documented
    # LangGraph node form; langgraph 1.x's add_node overloads don't admit them
    # under mypy, hence the targeted ignores.
    graph.add_node("classifier", make_classifier(client))  # type: ignore[call-overload]
    graph.add_node("researcher", make_researcher(client))  # type: ignore[call-overload]
    graph.add_node("responder", make_responder(client))  # type: ignore[call-overload]
    graph.add_node("reviewer", make_reviewer(client))  # type: ignore[call-overload]

    graph.add_edge(START, "classifier")
    graph.add_edge("classifier", "researcher")
    graph.add_edge("researcher", "responder")
    graph.add_edge("responder", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"responder": "responder", END: END},
    )

    return graph.compile()
