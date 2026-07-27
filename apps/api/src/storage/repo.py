"""Persistence helpers: resolved cases, their tool-call log, and security events.

The last two are deliberately separate tables. ``tool_calls`` is a functional
dispatch record (what ran, what it returned). ``security_events`` is a
narrower security narrative — refusals, blocked tools, sanitized output,
withheld leaks — queried independently by the audit/observability surface so
"what did the guardrails do" is never buried inside ordinary tool telemetry.
"""

from __future__ import annotations

import json
from typing import Any

from src.storage.db import get_connection


def insert_ticket(
    *,
    ticket_id: str,
    body: str,
    category: str | None,
    decision: str | None,
    reply: str | None,
    escalation_reason: str | None,
    iterations: int,
    latency_ms: float,
    cost_usd: float,
    db_path: str | None = None,
) -> None:
    """Upsert a resolved case. ``body``/``reply`` must already be PII-redacted."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO tickets
                (id, body, category, decision, reply, escalation_reason,
                 iterations, latency_ms, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                body=excluded.body,
                category=excluded.category,
                decision=excluded.decision,
                reply=excluded.reply,
                escalation_reason=excluded.escalation_reason,
                iterations=excluded.iterations,
                latency_ms=excluded.latency_ms,
                cost_usd=excluded.cost_usd
            """,
            (
                ticket_id,
                body,
                category,
                decision,
                reply,
                escalation_reason,
                iterations,
                latency_ms,
                cost_usd,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_tool_call(
    *,
    ticket_id: str,
    tool_name: str,
    args: dict[str, Any] | None,
    result: Any,
    status: str,
    db_path: str | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO tool_calls (ticket_id, tool_name, args_json, result_json, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                tool_name,
                json.dumps(args or {}, default=str),
                json.dumps(result, default=str),
                status,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_security_event(
    *,
    ticket_id: str,
    event_type: str,
    detail: str | None,
    db_path: str | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO security_events (ticket_id, event_type, detail) VALUES (?, ?, ?)",
            (ticket_id, event_type, detail),
        )
        conn.commit()
    finally:
        conn.close()


def recent_tickets(limit: int = 10, db_path: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM tickets ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def tool_calls_for_ticket(ticket_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE ticket_id = ? ORDER BY id ASC",
            (ticket_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def recent_security_events(limit: int = 10, db_path: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM security_events ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
