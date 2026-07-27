"""The LangGraph state threaded through Classifier -> Researcher -> Responder -> Reviewer."""

from __future__ import annotations

from typing import TypedDict


class CaseState(TypedDict, total=False):
    ticket_id: str
    ticket: str  # PII-redacted inbound text
    order_id: str | None
    category: str | None  # order | product | refund | other
    facts: list[dict]  # accumulated tool results
    draft: str | None
    review_feedback: str | None
    decision: str | None  # RESOLVED | ESCALATE | REFUSE
    escalation_reason: str | None
    iterations: int
    tool_calls: list[dict]  # functional dispatch log (ok/error/blocked/sanitized)
