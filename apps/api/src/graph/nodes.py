"""The four graph nodes: classifier, researcher, responder, reviewer.

Each ``make_*`` function closes over an injected :class:`LLMClient`, so
production and tests run identical node code — only the client differs. Nodes
are pure state transformers: read from ``CaseState``, return a partial update.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config import settings
from src.constants import Category, Decision, ToolStatus
from src.graph.llm import LLMClient
from src.graph.state import CaseState
from src.guardrails.injection import scan_tool_result
from src.guardrails.pii import redact_pii
from src.store.registry import dispatch_tool


def make_classifier(llm: LLMClient) -> Callable[[CaseState], dict[str, Any]]:
    def classifier(state: CaseState) -> dict:
        category = llm.classify(state["ticket"])
        if category not in {c.value for c in Category}:
            category = Category.OTHER.value
        return {"category": category}

    return classifier


def make_researcher(llm: LLMClient) -> Callable[[CaseState], dict[str, Any]]:
    """Bounded tool-calling loop; only allowlisted tools ever run.

    A model request for anything outside :data:`src.store.registry.ALLOWLIST`
    comes back from :func:`dispatch_tool` as ``status="blocked"`` — recorded
    for the audit trail, never executed.
    """

    def researcher(state: CaseState) -> dict:
        facts = list(state.get("facts") or [])
        tool_calls = list(state.get("tool_calls") or [])

        requests = llm.plan_research(
            ticket=state["ticket"],
            category=state.get("category") or Category.OTHER.value,
            order_id=state.get("order_id"),
        )

        for req in requests[: settings.max_tool_rounds]:
            name = req.get("name", "")
            args = req.get("args", {}) or {}
            record = dispatch_tool(name, args)
            tool_calls.append(record)
            if record["status"] == "ok":
                # Indirect-injection defense: a tool's own output is untrusted
                # (an attacker can plant a payload inside e.g. a product
                # description). Quarantine before it reaches the responder.
                flagged, sanitized = scan_tool_result(record["result"])
                if flagged:
                    record["status"] = ToolStatus.SANITIZED.value
                    record["result"] = sanitized
                facts.append({"tool": name, "args": args, "data": sanitized})

        return {"facts": facts, "tool_calls": tool_calls}

    return researcher


def make_responder(llm: LLMClient) -> Callable[[CaseState], dict[str, Any]]:
    def responder(state: CaseState) -> dict:
        draft = llm.draft(
            ticket=state["ticket"],
            category=state.get("category") or Category.OTHER.value,
            facts=state.get("facts") or [],
            feedback=state.get("review_feedback"),
        )
        # Defense in depth: redact again here even though the API boundary
        # redacts the final reply too, in case a caller invokes the graph
        # directly without going through service.resolve_case.
        return {"draft": redact_pii(draft)}

    return responder


def make_reviewer(llm: LLMClient) -> Callable[[CaseState], dict[str, Any]]:
    """Grade the draft; the iteration cap itself is enforced in ``edges.py``.

    This node only increments the counter and reports approval/feedback. When
    the cap is hit, routing converts the last feedback into an ESCALATE
    reason so the terminal state always carries a concrete explanation.
    """

    def reviewer(state: CaseState) -> dict:
        iterations = state.get("iterations", 0) + 1
        verdict = llm.review(
            ticket=state["ticket"],
            draft=state.get("draft") or "",
            facts=state.get("facts") or [],
        )

        if verdict.get("approved"):
            return {
                "iterations": iterations,
                "decision": Decision.RESOLVED.value,
                "review_feedback": None,
            }

        feedback = verdict.get("feedback") or "Reviewer did not approve this draft."
        update: dict = {"iterations": iterations, "review_feedback": feedback}

        if iterations >= settings.max_review_iterations:
            update["decision"] = Decision.ESCALATE.value
            update["escalation_reason"] = (
                f"Not approved after {iterations} review pass(es): {feedback}"
            )
        return update

    return reviewer
