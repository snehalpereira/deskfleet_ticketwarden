"""SQLite connection management and schema/fixture initialization (stdlib only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.config import settings
from src.store.seed import seed_catalog

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id                TEXT PRIMARY KEY,
    body              TEXT NOT NULL,
    category          TEXT,
    decision          TEXT,
    reply             TEXT,
    escalation_reason TEXT,
    iterations        INTEGER DEFAULT 0,
    latency_ms        REAL DEFAULT 0,
    cost_usd          REAL DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    args_json   TEXT,
    result_json TEXT,
    status      TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- Independent from tool_calls: a security narrative (what a guardrail did),
-- not a functional dispatch log. A REFUSE has no tool call at all, for
-- instance, but it always has a security_events row.
CREATE TABLE IF NOT EXISTS security_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       REAL NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY,
    customer_name   TEXT NOT NULL,
    status          TEXT NOT NULL,
    carrier         TEXT,
    tracking_number TEXT,
    placed_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_ticket ON tool_calls(ticket_id);
CREATE INDEX IF NOT EXISTS idx_security_events_ticket ON security_events(ticket_id);
CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a short-lived connection with row access by column name.

    ``check_same_thread=False`` because FastAPI serves sync routes from a
    thread pool; each call gets its own connection rather than sharing one.
    """
    path = db_path or settings.sqlite_path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create tables/indexes if missing, then load the fixture catalog."""
    conn = get_connection(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        seed_catalog(conn)
    finally:
        conn.close()
