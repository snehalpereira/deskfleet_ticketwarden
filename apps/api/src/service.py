"""Case resolution orchestration.

Wraps the compiled graph with the cross-cutting concerns around it:

  1. Injection guardrail — short-circuits to REFUSE *before any LLM call*.
  2. PII redaction — inbound text redacted before it enters state/persistence,
     outbound reply redacted before it's returned/persisted.
  3. Graph execution, keyed by ``thread_id = ticket_id``.
  4. Persistence of the case, its tool-call log, and its security-event log
     (kept as two separate tables — see storage/repo.py).
  5. Metrics + token/cost accounting.
  6. LangSmith trace URL construction (best-effort).

Kept separate from ``main.py`` so it can be exercised directly in tests with
an injected fake graph.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from src.config import settings
from src.constants import Decision, SecurityEventType, ToolStatus
from src.guardrails.injection import detect_injection, detect_prompt_leak
from src.guardrails.pii import redact_pii
from src.observability import metrics
from src.observability.costing import Usage, count_tokens, estimate_cost
from src.observability.tracing import ROOT_RUN_NAME, trace_run
from src.observability.usage import UsageCollector
from src.schemas import ResolveRequest, ResolveResponse, ToolCallRecord
from src.storage import repo


def _new_ticket_id() -> str:
    return f"tkt_{uuid.uuid4().hex[:12]}"


def _log_security_event(ticket_id: str, event_type: SecurityEventType, detail: str | None) -> None:
    repo.insert_security_event(ticket_id=ticket_id, event_type=event_type.value, detail=detail)
    metrics.record_security_event(event_type.value)


def _persist(state: dict[str, Any], ticket_id: str, latency_ms: float, cost_usd: float) -> None:
    repo.insert_ticket(
        ticket_id=ticket_id,
        body=state.get("ticket", ""),
        category=state.get("category"),
        decision=state.get("decision"),
        reply=state.get("draft"),
        escalation_reason=state.get("escalation_reason"),
        iterations=state.get("iterations", 0),
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
    for call in state.get("tool_calls", []) or []:
        tool_name = call.get("tool_name", "unknown")
        status = call.get("status", "unknown")
        repo.insert_tool_call(
            ticket_id=ticket_id,
            tool_name=tool_name,
            args=call.get("args"),
            result=call.get("result"),
            status=status,
        )
        metrics.record_tool_call(tool_name, status)

        # The tool-call log is functional telemetry; blocked/sanitized calls
        # additionally get their own row in the security-event log, which is
        # what the audit/observability surface actually watches.
        if status == ToolStatus.BLOCKED.value:
            _log_security_event(ticket_id, SecurityEventType.TOOL_BLOCKED, f"tool={tool_name}")
        elif status == ToolStatus.SANITIZED.value:
            _log_security_event(
                ticket_id, SecurityEventType.TOOL_OUTPUT_SANITIZED, f"tool={tool_name}"
            )


def resolve_case(graph: Any, request: ResolveRequest) -> ResolveResponse:
    """Run the full resolution pipeline for one support case."""
    started = time.perf_counter()
    ticket_id = _new_ticket_id()

    # (1) + (2): redact PII inbound, then scan the redacted text for injection.
    redacted_ticket = redact_pii(request.ticket)

    is_inj, reason = detect_injection(redacted_ticket)
    if is_inj:
        # Short-circuit BEFORE any model invocation.
        latency_ms = (time.perf_counter() - started) * 1000
        escalation_reason = f"Refused: prompt-injection signal detected ({reason})"
        state = {
            "ticket": redacted_ticket,
            "category": None,
            "decision": Decision.REFUSE.value,
            "draft": None,
            "escalation_reason": escalation_reason,
            "iterations": 0,
            "tool_calls": [],
        }
        _persist(state, ticket_id, latency_ms, 0.0)
        _log_security_event(ticket_id, SecurityEventType.INJECTION_REFUSED, reason)
        metrics.record_decision(Decision.REFUSE.value)
        metrics.record_latency(latency_ms / 1000)
        return ResolveResponse(
            ticket_id=ticket_id,
            decision=Decision.REFUSE.value,
            reply=None,
            category=None,
            escalation_reason=escalation_reason,
            iterations=0,
            tool_calls=[],
            langsmith_trace_url=None,
            latency_ms=round(latency_ms, 2),
            cost_usd=0.0,
        )

    # (3): run the graph, thread_id = ticket_id.
    initial: dict[str, Any] = {
        "ticket_id": ticket_id,
        "ticket": redacted_ticket,
        "order_id": request.order_id,
        "facts": [],
        "draft": None,
        "review_feedback": None,
        "decision": None,
        "escalation_reason": None,
        "iterations": 0,
        "tool_calls": [],
    }
    # One collector per request; LangGraph propagates callbacks to every
    # nested LLM call, so this sees real provider token counts from all four
    # nodes, including calls that go through with_structured_output.
    collector = UsageCollector()
    config = {
        "configurable": {"thread_id": ticket_id},
        "callbacks": [collector],
        "run_name": ROOT_RUN_NAME,
        "metadata": {"ticket_id": ticket_id, "order_id_hint": request.order_id or ""},
        "tags": ["ticketwarden", f"provider:{settings.llm_provider}"],
    }

    with trace_run() as trace:
        try:
            final: dict[str, Any] = graph.invoke(initial, config=config)
        except Exception as exc:  # noqa: BLE001 - degrade to ESCALATE, never 500 the graph
            final = {
                **initial,
                "decision": Decision.ESCALATE.value,
                "escalation_reason": f"Graph execution error: {exc}",
            }

    # (2 outbound): redact the reply again before returning/persisting.
    reply = redact_pii(final.get("draft")) if final.get("draft") else None
    final["draft"] = reply

    decision = final.get("decision") or Decision.ESCALATE.value

    # Outbound guardrail: a draft that narrates its own instructions or
    # carries a smuggled role tag means something got past the inbound layers
    # (e.g. a quarantine miss in tool output). Never send it — escalate with
    # the reply withheld, and log it as its own security event.
    is_leak, leak_pattern = detect_prompt_leak(reply)
    if is_leak and decision == Decision.RESOLVED.value:
        decision = Decision.ESCALATE.value
        final["escalation_reason"] = f"Outbound guardrail matched a leak signal: {leak_pattern}"
        _log_security_event(ticket_id, SecurityEventType.OUTBOUND_LEAK_BLOCKED, leak_pattern)
        reply = None
        final["draft"] = None

    final["decision"] = decision

    latency_ms = (time.perf_counter() - started) * 1000

    # (5): cost accounting. Preferred source is the provider's own token
    # counts, accumulated across every LLM call the graph made this request
    # (classify + research + one draft/review pair per review iteration).
    # Estimating from just the ticket and the final reply ignores system
    # prompts, tool schemas, accumulated facts, and retries, and would
    # under-report spend by a large multiple — so that's only a fallback.
    if collector.has_usage:
        prompt_tokens = collector.prompt_tokens
        completion_tokens = collector.completion_tokens
        metrics.record_token_source("provider")
    else:
        prompt_tokens = count_tokens(redacted_ticket, settings.llm_model)
        completion_tokens = count_tokens(reply or "", settings.llm_model)
        metrics.record_token_source("estimated")

    cost_usd = estimate_cost(
        prompt_tokens, completion_tokens, settings.llm_model, settings.llm_provider
    )
    usage = Usage(prompt_tokens, completion_tokens, cost_usd)

    # (4): persist.
    _persist(final, ticket_id, round(latency_ms, 2), cost_usd)

    metrics.record_decision(decision)
    metrics.record_latency(latency_ms / 1000)
    metrics.record_tokens(usage.prompt_tokens, usage.completion_tokens)
    metrics.record_cost(cost_usd)
    metrics.record_llm_calls(collector.llm_calls)

    tool_records = [
        ToolCallRecord(
            tool_name=c.get("tool_name", "unknown"),
            args=c.get("args", {}) or {},
            result=c.get("result"),
            status=c.get("status", "unknown"),
        )
        for c in final.get("tool_calls", []) or []
    ]

    return ResolveResponse(
        ticket_id=ticket_id,
        decision=decision,
        reply=reply,
        category=final.get("category"),
        escalation_reason=final.get("escalation_reason"),
        iterations=final.get("iterations", 0),
        tool_calls=tool_records,
        langsmith_trace_url=trace.url,
        latency_ms=round(latency_ms, 2),
        cost_usd=cost_usd,
    )
