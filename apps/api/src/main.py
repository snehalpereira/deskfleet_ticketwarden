"""FastAPI application factory, routes, and middleware."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from src.config import settings
from src.observability import metrics
from src.observability.tracing import configure_tracing, tracing_enabled
from src.schemas import (
    HealthResponse,
    ResolveRequest,
    ResolveResponse,
    SecurityEventSummary,
    TicketSummary,
)
from src.service import resolve_case
from src.storage import repo
from src.storage.db import init_db

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("ticketwarden")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Must run before any graph/LLM construction: the LangChain SDK reads
    # tracing config from os.environ at client-build time, not our settings.
    traced = configure_tracing()
    logger.info(
        "TicketWarden API started (llm_configured=%s, tracing=%s)",
        settings.has_llm_credentials,
        traced,
    )
    yield


def get_graph(request: Request) -> Any:
    """Compile the production graph, caching it on ``app.state``.

    Tests override ``app.state.graph`` with a fake-LLM-backed graph, so this
    path never runs with real credentials in CI.
    """
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        from src.graph.build import compile_graph

        graph = compile_graph()
        request.app.state.graph = graph
    return graph


class _LazyGraph:
    """Defers real graph compilation until ``.invoke()`` is actually called.

    Compiling the graph requires a configured LLM provider and raises if one
    isn't set up. ``resolve_case`` short-circuits an injected ticket to
    REFUSE *before* it ever calls ``graph.invoke()`` — as a route-level
    dependency, ``get_graph`` would compile (and fail) before that guardrail
    runs at all, 500ing on injection tickets even with no API key configured.
    Wrapping the graph lazily means compilation only happens once a case
    actually needs the LLM.
    """

    def __init__(self, request: Request) -> None:
        self._request = request

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return get_graph(self._request).invoke(*args, **kwargs)


def create_app() -> FastAPI:
    app = FastAPI(
        title="TicketWarden",
        description="Multi-agent support case resolver (LangGraph + FastAPI).",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.graph = None

    @app.middleware("http")
    async def request_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed:.2f}"
        return response

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            llm_configured=settings.has_llm_credentials,
            tracing_enabled=tracing_enabled(),
        )

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        body, content_type = metrics.metrics_payload()
        return Response(content=body, media_type=content_type)

    @app.post("/resolve", response_model=ResolveResponse)
    def resolve(req: ResolveRequest, request: Request) -> ResolveResponse:
        graph = request.app.state.graph or _LazyGraph(request)
        try:
            return resolve_case(graph, req)
        except Exception as exc:  # noqa: BLE001
            logger.exception("resolve failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/tickets", response_model=list[TicketSummary])
    def tickets(limit: int = 10) -> list[TicketSummary]:
        limit = max(1, min(limit, 100))
        return [TicketSummary(**row) for row in repo.recent_tickets(limit)]

    @app.get("/security-events", response_model=list[SecurityEventSummary])
    def security_events(limit: int = 10) -> list[SecurityEventSummary]:
        """Independent audit trail: refusals, blocked tools, sanitized output,
        withheld leaks — separate from the functional tool-call log."""
        limit = max(1, min(limit, 100))
        return [
            SecurityEventSummary(
                id=row["id"],
                ticket_id=row["ticket_id"],
                event_type=row["event_type"],
                detail=row["detail"],
                created_at=row["created_at"],
            )
            for row in repo.recent_security_events(limit)
        ]

    return app


app = create_app()
