"""PII redaction — applied to the inbound case text and the outbound draft.

Redaction is idempotent (running it twice is a no-op) and regex-based: a
standard technique, kept deliberately simple so it needs no model call and no
external service. Business identifiers (order/invoice/tracking numbers) are
preserved even though they're digit strings the phone/card patterns would
otherwise eat — those are operational references the Researcher needs, not
personal data.
"""

from __future__ import annotations

import re

_MASK = "[REDACTED]"

# Business references that must survive redaction. Digits following a
# keyword like "order" or "tracking" are masked out *before* the PII patterns
# run, then restored afterward, so a phrase like "order 1234567890" doesn't
# get eaten by the phone-number pattern.
#
# The keyword-to-digits connector is one bounded alternation, not a chain of
# independent optional pieces — that shape is what a regex-DoS scanner flags,
# since a long run of whitespace with no digits after it could otherwise be
# split across separate quantifiers in exponentially many ways before failing.
_BUSINESS_REF = re.compile(
    r"\b(order|invoice|tracking|ticket|reference|ref|awb)\b"
    r"(?:[\s:#]|id|no\.?|number){0,20}\d{3,}\b",
    re.I,
)

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
        ),
    ),
    ("ip_address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def _shield_business_refs(text: str) -> tuple[str, list[str]]:
    """Swap protected references for a digit-free placeholder; return the swap log."""
    saved: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        saved.append(match.group(0))
        return f"\x00REF{len(saved) - 1}\x00"

    return _BUSINESS_REF.sub(_stash, text), saved


def _unshield_business_refs(text: str, saved: list[str]) -> str:
    for index, original in enumerate(saved):
        text = text.replace(f"\x00REF{index}\x00", original)
    return text


def redact_pii(text: str | None) -> str:
    """Replace detected PII spans with ``[REDACTED]``, preserving business refs."""
    if not text:
        return text or ""

    shielded, saved = _shield_business_refs(text)
    for _label, pattern in _PII_PATTERNS:
        shielded = pattern.sub(_MASK, shielded)
    return _unshield_business_refs(shielded, saved)


def find_pii(text: str | None) -> dict[str, int]:
    """Count PII spans by category — used by tests and the health/audit surface."""
    counts: dict[str, int] = {}
    if not text:
        return counts

    shielded, _saved = _shield_business_refs(text)
    for label, pattern in _PII_PATTERNS:
        hits = pattern.findall(shielded)
        if hits:
            counts[label] = len(hits)
    return counts
