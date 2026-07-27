"""LangSmith tracing activation and per-case trace URL capture.

Two things have to happen for a trace link to actually work:

1. **Activation.** ``pydantic-settings`` reads ``.env`` into ``settings``, but
   the LangChain SDK reads ``os.environ`` directly. :func:`configure_tracing`
   bridges the two, and must run before the graph is compiled.
2. **Capture.** :func:`trace_run` collects the root run of one graph
   invocation so the response can hand back a clickable URL.

Both degrade to no-ops when tracing is off or the SDK is missing — resolving
a case must never fail because observability is misconfigured.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

from src.config import settings

logger = logging.getLogger("ticketwarden.tracing")

ROOT_RUN_NAME = "ticketwarden.resolve"

_configured = False


def tracing_enabled() -> bool:
    key = settings.langchain_api_key
    if not key or key.startswith("lsv2_..."):  # ignore the .env.example placeholder
        return False
    return bool(settings.langchain_tracing_v2)


def configure_tracing() -> bool:
    """Export LangSmith config into ``os.environ``. Idempotent.

    Existing environment variables win over a stale ``.env`` — a real
    deployment env (Cloud Run secrets, docker-compose) should not be
    silently overridden.
    """
    global _configured

    if not tracing_enabled():
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
        logger.info("LangSmith tracing disabled (no API key or LANGCHAIN_TRACING_V2=false)")
        _configured = True
        return False

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langchain_endpoint)
    # LangSmith SDK >=0.2 prefers LANGSMITH_*; set both so either works.
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langchain_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langchain_project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langchain_endpoint)

    logger.info("LangSmith tracing enabled (project=%s)", settings.langchain_project)
    _configured = True
    return True


def _select_root(traced: list[Any]) -> Any | None:
    """Pick the graph invocation out of the collected runs.

    Children finish before parents, so the collector's insertion order isn't
    useful for finding the root — select by identity instead: the named run,
    else the outermost parentless chain, else whatever finished last.
    """
    if not traced:
        return None

    for run in traced:
        if getattr(run, "name", None) == ROOT_RUN_NAME:
            return run

    chains = [
        run
        for run in traced
        if getattr(run, "run_type", None) == "chain" and getattr(run, "parent_run_id", None) is None
    ]
    if chains:
        return chains[-1]

    return traced[-1]


def _url_for_run(run: Any) -> str | None:
    run_id = getattr(run, "id", None)
    if not run_id:
        return None

    try:
        from langsmith import Client

        return Client().get_run_url(run=run)
    except Exception:  # noqa: BLE001 - fall back rather than fail the request
        logger.debug("get_run_url failed; using constructed URL", exc_info=True)

    host = settings.langchain_endpoint.replace("api.smith", "smith").rstrip("/")
    host = host.removesuffix("/api")
    return f"{host}/o/-/projects/p/{settings.langchain_project}/r/{run_id}"


class TraceHandle:
    """Mutable holder populated once the traced block exits."""

    __slots__ = ("run_id", "url")

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.url: str | None = None


@contextmanager
def trace_run():
    """Run a block with LangSmith run collection, yielding a :class:`TraceHandle`.

    A transparent no-op when tracing is off or the SDK is missing — the
    handle stays empty and the caller returns a ``None`` trace URL.
    """
    handle = TraceHandle()

    if not tracing_enabled():
        yield handle
        return

    try:
        from langchain_core.tracers.context import collect_runs

        collector = collect_runs()
    except Exception:  # noqa: BLE001 - pragma: no cover
        yield handle
        return

    # The caller's body is deliberately NOT wrapped in try/except — swallowing
    # its exceptions would hide a real resolution failure behind an
    # observability concern. Only URL resolution below is guarded.
    with collector as run_collector:
        yield handle

        try:
            traced = getattr(run_collector, "traced_runs", None) or []
            root = _select_root(list(traced))
            if root is not None:
                handle.run_id = str(getattr(root, "id", "") or "") or None
                handle.url = _url_for_run(root)
        except Exception:  # noqa: BLE001 - tracing must never break resolution
            logger.warning("trace collection failed", exc_info=True)
