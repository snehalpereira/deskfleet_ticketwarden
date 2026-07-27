"""The tool allowlist — the actual security boundary for the Researcher node.

``dispatch_tool`` is the only path the graph uses to run a tool. A model
request for anything not present in ``ALLOWLIST`` is recorded as
``status="blocked"`` and never executed; nothing about that decision is
delegated to the model.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.constants import ToolStatus
from src.store.catalog import check_order_status, get_product_details, search_catalog

ALLOWLIST: dict[str, Callable[..., dict[str, Any]]] = {
    "check_order_status": check_order_status,
    "get_product_details": get_product_details,
    "search_catalog": search_catalog,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_order_status",
            "description": (
                "Look up the fulfillment status, carrier, and line items for a "
                "customer order by its numeric order id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Numeric order id."}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Fetch details (title, price, description) for one product by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Numeric product id."}
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": "Search the product catalog by keyword and optional category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to search for."},
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (outdoor, electronics, apparel).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def is_allowed(name: str) -> bool:
    return name in ALLOWLIST


def dispatch_tool(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Run an allowlisted tool and return a structured audit record.

    Off-registry names are refused outright — the function is never called.
    """
    args = args or {}
    if not is_allowed(name):
        return {
            "tool_name": name,
            "args": args,
            "result": {"error": "tool_not_allowlisted"},
            "status": ToolStatus.BLOCKED.value,
        }

    func = ALLOWLIST[name]
    try:
        result = func(**args)
    except TypeError as exc:
        return {
            "tool_name": name,
            "args": args,
            "result": {"error": "bad_arguments", "detail": str(exc)},
            "status": ToolStatus.ERROR.value,
        }
    except Exception as exc:  # noqa: BLE001 - a tool must never crash the graph
        return {
            "tool_name": name,
            "args": args,
            "result": {"error": "tool_exception", "detail": str(exc)},
            "status": ToolStatus.ERROR.value,
        }

    status = ToolStatus.OK.value
    if isinstance(result, dict) and result.get("error"):
        status = ToolStatus.ERROR.value
    return {"tool_name": name, "args": args, "result": result, "status": status}
