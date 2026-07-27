"""Constants shared between the API and the Streamlit UI.

Deliberately dependency-free so the UI process doesn't need the API package
installed just to read a color or an enum value.
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
    SANITIZED = "sanitized"


DECISIONS = [d.value for d in Decision]
CATEGORIES = [c.value for c in Category]

DECISION_COLORS = {
    Decision.RESOLVED.value: "#1a7f37",
    Decision.ESCALATE.value: "#9a6700",
    Decision.REFUSE.value: "#cf222e",
}
