"""Token counting and USD cost estimation.

Best-effort and model-aware: falls back to ``cl100k_base`` when tiktoken
doesn't recognize the configured model, and to the gpt-4o-mini rate when a
(provider, model) pair isn't in the price table.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import tiktoken

    _HAS_TIKTOKEN = True
except Exception:  # pragma: no cover - tiktoken is a hard dep in practice
    _HAS_TIKTOKEN = False

# USD per 1K tokens, keyed by (provider, model): (prompt_rate, completion_rate).
# "*" is the per-provider fallback. Local/credit-based providers cost 0.
_PRICE_TABLE: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-4o-mini"): (0.00015, 0.00060),
    ("openai", "gpt-4o"): (0.0025, 0.0100),
    ("openai", "gpt-4-turbo"): (0.0100, 0.0300),
    ("openai", "gpt-3.5-turbo"): (0.0005, 0.0015),
    ("openai", "*"): (0.00015, 0.00060),
    ("groq", "llama-3.3-70b-versatile"): (0.00059, 0.00079),
    ("groq", "llama-3.1-8b-instant"): (0.00005, 0.00008),
    ("groq", "*"): (0.00059, 0.00079),
    ("gemini", "gemini-2.0-flash"): (0.00010, 0.00040),
    ("gemini", "gemini-1.5-pro"): (0.00125, 0.00500),
    ("gemini", "*"): (0.00010, 0.00040),
    ("anthropic", "claude-sonnet-4-6"): (0.00300, 0.01500),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.00080, 0.00400),
    ("anthropic", "*"): (0.00300, 0.01500),
    ("nvidia", "*"): (0.0, 0.0),
    ("ollama", "*"): (0.0, 0.0),
}
_DEFAULT_PRICE = _PRICE_TABLE[("openai", "gpt-4o-mini")]


def _price_for(model: str, provider: str = "openai") -> tuple[float, float]:
    provider = (provider or "openai").lower()
    return (
        _PRICE_TABLE.get((provider, model)) or _PRICE_TABLE.get((provider, "*")) or _DEFAULT_PRICE
    )


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
        )


def _encoding_for(model: str):
    if not _HAS_TIKTOKEN:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:  # pragma: no cover
            return None


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    if not text:
        return 0
    enc = _encoding_for(model)
    if enc is None:  # pragma: no cover - only when tiktoken is unavailable
        return max(1, len(text.split()))
    return len(enc.encode(text))


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
) -> float:
    prompt_rate, completion_rate = _price_for(model, provider)
    cost = (prompt_tokens / 1000.0) * prompt_rate + (completion_tokens / 1000.0) * completion_rate
    return round(cost, 8)


def usage_for(
    prompt_text: str,
    completion_text: str,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
) -> Usage:
    p = count_tokens(prompt_text, model)
    c = count_tokens(completion_text, model)
    return Usage(
        prompt_tokens=p,
        completion_tokens=c,
        cost_usd=estimate_cost(p, c, model, provider),
    )
