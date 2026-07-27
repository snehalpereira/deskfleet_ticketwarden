"""Routing after the reviewer node — the loop's exit condition, in plain code.

    approved                       -> END (decision already RESOLVED)
    not approved & below the cap   -> responder (retry with feedback)
    not approved & cap reached     -> END (reviewer already set ESCALATE)

Never delegated to the model: a reviewer that keeps rejecting its own drafts
cannot spin forever.
"""

from __future__ import annotations

from langgraph.graph import END

from src.config import settings
from src.constants import Decision
from src.graph.state import CaseState


def route_after_review(state: CaseState) -> str:
    if state.get("decision") == Decision.RESOLVED.value:
        return END
    if state.get("iterations", 0) >= settings.max_review_iterations:
        return END
    return "responder"
