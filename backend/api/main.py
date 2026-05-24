from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.agents.graph_agent import _get_compiled_graph
from backend.api.routes import router
from backend.core.config import get_settings
from backend.core.connections import aclose_pool, init_pool
from backend.db.audit_store import close_audit_store, init_audit_store
from backend.db.gap_store import close_gap_store, init_gap_store
from backend.db.graph_queries import ensure_indexes
from backend.db.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared resources on startup; release them on shutdown.

    ConnectionPool opens Qdrant / Neo4j / httpx clients once and reuses
    them across all requests — eliminates per-request connection overhead.
    In mock/local-lite mode the pool initialises with empty slots (no-op).
    """
    settings = get_settings()
    init_pool(settings)
    logger.info("[startup] connection pool ready (mode=%s)", settings.app_mode)
    init_gap_store(settings.gap_store_path)
    init_audit_store(settings.audit_store_path)

    # Ensure Neo4j indexes exist (idempotent; skipped in mock mode)
    if settings.storage_backend == "qdrant-neo4j":
        from backend.core.connections import get_pool
        ensure_indexes(Neo4jDriver.from_pool(get_pool().neo4j))
        logger.info("[startup] Neo4j indexes verified")

    # Pre-warm the compiled LangGraph — eliminates cold-start latency (~2-3 s)
    # on the first /query request.  build_graph() is CPU-only; safe to call here.
    _get_compiled_graph(settings)
    logger.info("[startup] agent graph pre-warmed")

    yield

    close_gap_store()
    close_audit_store()
    await aclose_pool()
    logger.info("[shutdown] resources released")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Synapse GraphRAG Knowledge Platform API",
        version=settings.app_version,
        description="Local-first GraphRAG MVP backend.",
        lifespan=lifespan,
    )
    app.include_router(router)

    # Prometheus metrics at /metrics
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            excluded_handlers=["/metrics", "/health"],
        ).instrument(app).expose(app, include_in_schema=False)
    except ImportError:
        pass

    if _FRONTEND_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
