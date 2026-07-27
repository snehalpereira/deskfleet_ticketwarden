"""Prometheus metric definitions.

Module-level singletons registered against the default registry, so
``generate_latest`` in the ``/metrics`` route exports all of them at once.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

CASES_TOTAL = Counter(
    "ticketwarden_cases_total",
    "Total cases processed, labeled by terminal decision.",
    ["decision"],
)

CASE_LATENCY = Histogram(
    "ticketwarden_case_latency_seconds",
    "End-to-end case resolution latency in seconds.",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

TOKENS_TOTAL = Counter(
    "ticketwarden_tokens_total",
    "Total LLM tokens accounted, labeled by direction.",
    ["direction"],  # prompt | completion
)

COST_USD_TOTAL = Counter(
    "ticketwarden_cost_usd_total",
    "Cumulative estimated LLM spend in USD.",
)

TOOL_CALLS_TOTAL = Counter(
    "ticketwarden_tool_calls_total",
    "Total tool invocations, labeled by tool and status.",
    ["tool", "status"],
)

LLM_CALLS_TOTAL = Counter(
    "ticketwarden_llm_calls_total",
    "Total LLM invocations made across all graph nodes.",
)

TOKEN_SOURCE_TOTAL = Counter(
    "ticketwarden_token_source_total",
    "How token counts were obtained, for cost-accuracy monitoring.",
    ["source"],  # provider | estimated
)

SECURITY_EVENTS_TOTAL = Counter(
    "ticketwarden_security_events_total",
    "Guardrail security events, labeled by type.",
    ["event_type"],
)


def record_decision(decision: str) -> None:
    CASES_TOTAL.labels(decision=decision).inc()


def record_latency(seconds: float) -> None:
    CASE_LATENCY.observe(seconds)


def record_tokens(prompt: int, completion: int) -> None:
    if prompt:
        TOKENS_TOTAL.labels(direction="prompt").inc(prompt)
    if completion:
        TOKENS_TOTAL.labels(direction="completion").inc(completion)


def record_cost(usd: float) -> None:
    if usd:
        COST_USD_TOTAL.inc(usd)


def record_tool_call(tool: str, status: str) -> None:
    TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()


def record_llm_calls(count: int) -> None:
    if count:
        LLM_CALLS_TOTAL.inc(count)


def record_token_source(source: str) -> None:
    TOKEN_SOURCE_TOTAL.labels(source=source).inc()


def record_security_event(event_type: str) -> None:
    SECURITY_EVENTS_TOTAL.labels(event_type=event_type).inc()


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
