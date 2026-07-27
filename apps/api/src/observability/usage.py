"""Real token-usage capture via a LangChain callback handler.

Why a callback instead of reading return values: the graph makes several LLM
calls per case (classify, plan_research, draft, and one review per loop
iteration), and two of those go through ``with_structured_output``, which
hands back a Pydantic model rather than an ``AIMessage`` — the token counts
aren't visible to the caller at all. A callback sees every call uniformly.
One :class:`UsageCollector` is created per request and passed in the graph
config; LangGraph propagates callbacks to nested runnables, so every node's
LLM call reports into it without the node code knowing anything about costing.
"""

from __future__ import annotations

from typing import Any

try:
    from langchain_core.callbacks import BaseCallbackHandler

    _BASE: Any = BaseCallbackHandler
except Exception:  # pragma: no cover - only when langchain_core is absent

    class _Base:  # type: ignore[no-redef]
        pass

    _BASE = _Base


def _extract(response: Any) -> tuple[int, int]:
    """Pull ``(prompt_tokens, completion_tokens)`` out of an ``LLMResult``.

    Two shapes are checked, newest first: the provider-neutral
    ``usage_metadata`` on the generated message, then the legacy
    ``llm_output["token_usage"]`` dict some providers still emit.
    """
    prompt = completion = 0

    for generations in getattr(response, "generations", None) or []:
        for gen in generations or []:
            message = getattr(gen, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, dict):
                prompt += int(usage.get("input_tokens") or 0)
                completion += int(usage.get("output_tokens") or 0)

    if prompt or completion:
        return prompt, completion

    llm_output = getattr(response, "llm_output", None) or {}
    if isinstance(llm_output, dict):
        token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if isinstance(token_usage, dict):
            prompt += int(token_usage.get("prompt_tokens") or 0)
            completion += int(token_usage.get("completion_tokens") or 0)

    return prompt, completion


class UsageCollector(_BASE):  # type: ignore[misc,valid-type]
    """Accumulates token usage across every LLM call made while resolving one case."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.llm_calls = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: D102
        self.llm_calls += 1
        try:
            prompt, completion = _extract(response)
        except Exception:  # noqa: BLE001 - accounting must never break resolution
            return
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    @property
    def has_usage(self) -> bool:
        """True once a provider actually reported token counts.

        False means either no LLM ran yet (an injection short-circuit, or a
        test's fake client) or the provider simply omits usage — callers
        fall back to a tiktoken estimate in that case.
        """
        return bool(self.prompt_tokens or self.completion_tokens)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
