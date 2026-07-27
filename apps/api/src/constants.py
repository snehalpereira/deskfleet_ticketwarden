"""Enum vocabulary for the case-resolution pipeline.

Mirrored (not imported) in ``packages/shared/constants.py`` so the Streamlit UI
can use the same values without depending on the API package.
"""

from __future__ import annotations

from enum import Enum


class Decision(str, Enum):
    RESOLVED = "RESOLVED"
    ESCALATE = "ESCALATE"
    REFUSE = "REFUSE"


class Category(str, Enum):
    ORDER = "order"
    PRODUCT = "product"
    REFUND = "refund"
    OTHER = "other"


class ToolStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"
    SANITIZED = "sanitized"  # tool succeeded, but its output carried an injection payload


class SecurityEventType(str, Enum):
    """Independent security-audit vocabulary — never mixed with tool-call records."""

    INJECTION_REFUSED = "injection_refused"
    TOOL_BLOCKED = "tool_blocked"
    TOOL_OUTPUT_SANITIZED = "tool_output_sanitized"
    OUTBOUND_LEAK_BLOCKED = "outbound_leak_blocked"


DECISIONS = [d.value for d in Decision]
CATEGORIES = [c.value for c in Category]

DECISION_COLORS = {
    Decision.RESOLVED.value: "#1a7f37",
    Decision.ESCALATE.value: "#9a6700",
    Decision.REFUSE.value: "#cf222e",
}
