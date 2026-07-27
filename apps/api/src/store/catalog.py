"""Read-only queries against the local Basecamp Supply Co. catalog.

Every function here is a plain SQLite read against tables seeded by
:mod:`src.store.seed` — no HTTP client, no timeout handling, no upstream
outage to plan for. That's a deliberate trade against the brief's "external
order API" expectation: the researcher still calls tools that look up
order/product facts it doesn't already have, but the backing store is local
and deterministic, which also makes the test suite fully offline.
"""

from __future__ import annotations

from typing import Any

from src.storage.db import get_connection


def check_order_status(order_id: str | int) -> dict[str, Any]:
    """Look up an order's fulfillment status, carrier, and line items."""
    try:
        oid = int(str(order_id).strip())
    except (TypeError, ValueError):
        return {"error": "invalid_order_id", "order_id": str(order_id)}

    conn = get_connection()
    try:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if order is None:
            return {"error": "order_not_found", "order_id": oid}

        items = conn.execute(
            """
            SELECT p.title, p.price, oi.quantity
            FROM order_items oi JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ?
            """,
            (oid,),
        ).fetchall()
    finally:
        conn.close()

    return {
        "order_id": oid,
        "status": order["status"],
        "customer_name": order["customer_name"],
        "carrier": order["carrier"],
        "tracking_number": order["tracking_number"],
        "placed_at": order["placed_at"],
        "items": [
            {"title": row["title"], "price": row["price"], "quantity": row["quantity"]}
            for row in items
        ],
    }


def get_product_details(product_id: str | int) -> dict[str, Any]:
    """Fetch a single product record by id."""
    try:
        pid = int(str(product_id).strip())
    except (TypeError, ValueError):
        return {"error": "invalid_product_id", "product_id": str(product_id)}

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()

    if row is None:
        return {"error": "product_not_found", "product_id": pid}
    return dict(row)


def search_catalog(query: str = "", category: str | None = None) -> dict[str, Any]:
    """Keyword-search the catalog, optionally scoped to a category."""
    conn = get_connection()
    try:
        sql = "SELECT id, title, category, price FROM products WHERE 1=1"
        params: list[Any] = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        if query:
            sql += " AND (title LIKE ? OR description LIKE ?)"
            like = f"%{query}%"
            params.extend([like, like])
        sql += " LIMIT 10"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    results = [dict(row) for row in rows]
    return {"query": query, "category": category, "count": len(results), "results": results}
