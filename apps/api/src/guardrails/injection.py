"""Prompt-injection defense: a scored risk model, not a first-match trigger.

Design note (why scored rather than "any regex match refuses"): a single
ambiguous phrase — "hypothetically, if you were an admin..." — is weak
evidence on its own, but several weak signals stacked in one message are not
weak anymore. Patterns below are grouped into severity tiers with a weight
each; :func:`detect_injection` sums every match (not just the first) and
refuses once the total crosses ``REFUSE_THRESHOLD``. A single HIGH-tier hit
(an outright "ignore your instructions" or a smuggled role tag) crosses the
threshold by itself, so the obvious attacks still short-circuit immediately —
the scoring only changes behavior for the ambiguous middle ground.

Four things run in plain, deterministic Python, never delegated to a model:

1. :func:`normalize` — NFKC-fold + strip invisible/bidi characters so
   obfuscated payloads (fullwidth letters, zero-width-joined words) still hit
   the pattern layer.
2. :func:`detect_injection` — the scored scan described above. A match
   short-circuits the whole request to ``REFUSE`` before any LLM call.
3. :func:`scan_tool_result` — external tool output is untrusted (indirect
   injection: a poisoned product title). Flagged strings are quarantined
   before they reach the responder's prompt.
4. :func:`detect_prompt_leak` — an outbound-only check: does the drafted
   reply narrate its own instructions, or echo a smuggled role tag back to
   the customer?
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ZWSP, ZWNJ, ZWJ, word joiner, BOM, soft hyphen, and bidi control characters —
# all commonly used to split a trigger word so it slips past naive matching.
_INVISIBLE_CHARS = re.compile(
    "[\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)


@dataclass(frozen=True)
class _Signal:
    label: str
    weight: int
    pattern: re.Pattern[str]


# HIGH (weight 3): a single hit is, by itself, enough to refuse.
_HIGH_SIGNALS = [
    _Signal(
        "override_instructions",
        3,
        re.compile(
            r"\b(ignore|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+"
            r"(instructions|context)",
            re.I,
        ),
    ),
    _Signal(
        "forget_instructions",
        3,
        re.compile(r"\bforget\s+(everything|all|your)\s+" r"(instructions|rules|prompt)?", re.I),
    ),
    _Signal(
        "exfiltrate_prompt",
        3,
        re.compile(
            r"(reveal|show|print|repeat|expose|leak|output|display)\s+(me\s+)?(your\s+)?"
            r"(the\s+)?(system\s+prompt|initial\s+prompt|instructions|api\s+key|secret|"
            r"credentials)",
            re.I,
        ),
    ),
    _Signal("role_tag_smuggling", 3, re.compile(r"</?(system|assistant|user)>", re.I)),
    _Signal("special_token_smuggling", 3, re.compile(r"<\|[a-z_]+\|>", re.I)),
    _Signal("chat_template_smuggling", 3, re.compile(r"\[/?(INST|SYS|SYSTEM)\]", re.I)),
    _Signal("code_fence_role_smuggling", 3, re.compile(r"```[\s\S]*?(system|assistant)\s*:", re.I)),
    _Signal(
        "jailbreak_persona",
        3,
        re.compile(
            r"\b(developer\s+mode|jailbreak|DAN\b(?:\s+mode)?|" r"do\s+anything\s+now)\b", re.I
        ),
    ),
    _Signal(
        "privilege_escalation",
        3,
        re.compile(r"\b(admin|root|sudo|superuser)\s+" r"(mode|access|override)\b", re.I),
    ),
    _Signal(
        "tool_coercion", 3, re.compile(r"\bcall\s+(the\s+)?tool\s+['\"]?\w+['\"]?\s+with\b", re.I)
    ),
    _Signal("encoded_payload", 3, re.compile(r"\bbase64\s*(decode|:)\s*[A-Za-z0-9+/=]{16,}", re.I)),
    _Signal(
        "execute_coercion",
        3,
        re.compile(r"\bexecute\s+(this|the\s+following)\s+" r"(code|command|instruction)", re.I),
    ),
    # Getting the model to recite prior context verbatim is a direct
    # exfiltration technique, not an ambiguous one — weighted HIGH like the
    # rest of this tier, unlike the softer probing signals below.
    _Signal(
        "echo_coercion",
        3,
        re.compile(r"\b(repeat|echo|say)\s+(everything|all|the\s+text)\s+" r"(above|before)", re.I),
    ),
    _Signal(
        "translate_coercion",
        3,
        re.compile(r"\btranslate\s+(everything|the\s+text)\s+above\b", re.I),
    ),
    _Signal(
        "persistent_reframe", 3, re.compile(r"\bfrom\s+now\s+on\s+you\s+(are|will|must)\b", re.I)
    ),
]

# MEDIUM (weight 2): role-play coercion and rule-replacement attempts. Real
# signal, but plausible enough in isolation (a customer asking to role-play a
# scenario) that a single hit shouldn't refuse on its own.
_MEDIUM_SIGNALS = [
    _Signal("persona_hijack", 2, re.compile(r"\byou\s+are\s+now\s+(a|an|the)\b", re.I)),
    _Signal(
        "roleplay_coercion",
        2,
        re.compile(r"\b(act\s+as\s+(a|an|if)|pretend\s+(to\s+be|" r"you\s+are))\b", re.I),
    ),
    _Signal("new_rules", 2, re.compile(r"\bnew\s+(instructions|system\s+prompt|rules)\b", re.I)),
    _Signal(
        "safety_override",
        2,
        re.compile(
            r"\boverride\s+(your|the|all)\s+(instructions|rules|" r"safety|guardrails)", re.I
        ),
    ),
    _Signal("identity_suppression", 2, re.compile(r"\bstop\s+being\s+(a|an)\b", re.I)),
]

# LOW (weight 1): softer signals, plausible in a genuine customer message on
# their own — meaningful only once stacked with another hit.
_LOW_SIGNALS = [
    _Signal(
        "prompt_probing",
        1,
        re.compile(r"\bwhat\s+(are|were)\s+your\s+(instructions|rules|" r"system\s+prompt)", re.I),
    ),
    _Signal(
        "hypothetical_framing", 1, re.compile(r"\bhypothetically\s+you\s+(are|could|can)\b", re.I)
    ),
]

_ALL_SIGNALS: list[_Signal] = [*_HIGH_SIGNALS, *_MEDIUM_SIGNALS, *_LOW_SIGNALS]

REFUSE_THRESHOLD = 3

_LEAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmy\s+(system\s+prompt|instructions)\s+(is|are|say)", re.I),
    re.compile(r"\bI\s+(was|am)\s+(told|instructed|programmed)\s+to\b", re.I),
    re.compile(r"\bas\s+an?\s+AI\s+(language\s+)?model,?\s+my\s+instructions\b", re.I),
    re.compile(r"</?(system|assistant)>", re.I),
    re.compile(r"<\|[a-z_]+\|>", re.I),
    re.compile(r"\b(api[_\s]?key|secret[_\s]?key|password)\s*[:=]\s*\S+", re.I),
]


def normalize(text: str) -> str:
    """NFKC-fold and strip invisible characters before any pattern scan."""
    if not text:
        return ""
    return _INVISIBLE_CHARS.sub("", unicodedata.normalize("NFKC", text))


def _risk_score(text: str) -> tuple[int, list[str]]:
    """Sum every matching signal's weight (not just the first) and label it."""
    score = 0
    matched: list[str] = []
    for signal in _ALL_SIGNALS:
        if signal.pattern.search(text):
            score += signal.weight
            matched.append(signal.label)
    return score, matched


def detect_injection(text: str) -> tuple[bool, str | None]:
    """Return ``(refuse, reason)``. ``reason`` names every signal that fired."""
    if not text:
        return False, None
    score, matched = _risk_score(normalize(text))
    if score >= REFUSE_THRESHOLD:
        return True, f"risk_score={score} signals={','.join(matched)}"
    return False, None


def is_injection(text: str) -> bool:
    return detect_injection(text)[0]


def scan_tool_result(result: object) -> tuple[bool, object]:
    """Quarantine injection payloads embedded in untrusted tool output.

    Returns ``(flagged, sanitized)``; flagged strings are replaced with a
    quarantine marker so the payload never reaches the responder's prompt.
    """
    flagged = False

    def _clean(value: object) -> object:
        nonlocal flagged
        if isinstance(value, str):
            if is_injection(value):
                flagged = True
                return "[QUARANTINED: injection signal in external data]"
            return value
        if isinstance(value, dict):
            return {k: _clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value

    # Evaluate _clean before reading `flagged` — tuple args evaluate
    # left-to-right, and `return flagged, _clean(...)` would always read False.
    sanitized = _clean(result)
    return flagged, sanitized


def detect_prompt_leak(text: str | None) -> tuple[bool, str | None]:
    """Return ``(is_leaking, matched_pattern)`` for an outbound drafted reply."""
    if not text:
        return False, None
    cleaned = normalize(text)
    for pattern in _LEAK_PATTERNS:
        if pattern.search(cleaned):
            return True, pattern.pattern
    return False, None
