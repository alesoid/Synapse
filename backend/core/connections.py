"""
Application-scoped connection pool.

Initialised once during FastAPI lifespan startup; closed on shutdown.
All long-lived clients (Qdrant, Neo4j driver, httpx) live here so that
retriever and LLM code reuses existing connections instead of opening
new ones per request.

Usage
-----
Startup (api/main.py lifespan):
    init_pool(settings)

Per-request access (retrievers, LLM client, storage):
    from backend.core.connections import get_pool
    client     = get_pool().qdrant      # QdrantClient
    driver     = get_pool().neo4j       # neo4j.Driver  (raw bolt driver)
    http       = get_pool().http        # httpx.Client  (sync, kept for compat)
    async_http = get_pool().async_http  # httpx.AsyncClient (async LLM calls)

Shutdown (async-safe):
    await pool.aclose()   — closes async_http then delegates to close()

Mock mode
---------
In local-lite (storage_backend="mock", llm_backend="mock") the pool is
initialised but all slots remain None — mock retrievers never call get_pool(),
so no RuntimeError is raised.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.core.config import Settings

if TYPE_CHECKING:
    import httpx
    from neo4j import Driver
    from qdrant_client import QdrantClient

    _AsyncClient = httpx.AsyncClient

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Holds one shared instance of each external client.

    Clients that require GPU/network services (Qdrant, Neo4j, vLLM) are
    initialised only when the corresponding backend is active, so the pool
    stays empty (and safe) in local-lite / mock mode.
    """

    def __init__(self) -> None:
        self._qdrant: QdrantClient | None = None
        self._neo4j: Driver | None = None
        self._http: httpx.Client | None = None
        self._async_http: httpx.AsyncClient | None = None
        self._ollama_http: httpx.Client | None = None   # persistent keep-alive for Ollama

    # ── Initialisation ────────────────────────────────────────────────────────

    def initialize(self, settings: Settings) -> None:
        if settings.storage_backend == "qdrant-neo4j":
            self._init_qdrant(settings)
            self._init_neo4j(settings)
        if settings.llm_backend == "vllm":
            self._init_http()
        if settings.embeddings_backend == "local":
            self._init_ollama_http(settings)
        logger.info(
            "[pool] initialized — qdrant=%s neo4j=%s http=%s async_http=%s ollama_http=%s",
            self._qdrant is not None,
            self._neo4j is not None,
            self._http is not None,
            self._async_http is not None,
            self._ollama_http is not None,
        )

    def _init_qdrant(self, settings: Settings) -> None:
        from qdrant_client import QdrantClient
        self._qdrant = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        logger.info("[pool] QdrantClient ready → %s:%d", settings.qdrant_host, settings.qdrant_port)

    def _init_neo4j(self, settings: Settings) -> None:
        from neo4j import GraphDatabase
        from neo4j.exceptions import AuthError, ServiceUnavailable
        try:
            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            driver.verify_connectivity()
            self._neo4j = driver
            logger.info("[pool] Neo4j Driver ready → %s", settings.neo4j_uri)
        except (ServiceUnavailable, AuthError) as exc:
            logger.error("[pool] Neo4j connection failed: %s", exc)
            raise

    def _init_http(self) -> None:
        import httpx
        self._http = httpx.Client(timeout=90.0)
        self._async_http = httpx.AsyncClient(timeout=90.0)
        logger.info("[pool] httpx.Client + AsyncClient ready (timeout=90s)")

    def _init_ollama_http(self, settings: Settings) -> None:
        import httpx
        # Ollama embedding calls are synchronous and can be slow for large batches;
        # timeout=60 s per batch.  A persistent client reuses the TCP connection
        # across ingestion chunks instead of opening a new one per embed_query() call.
        base_url = settings.ollama_host.rstrip("/")
        self._ollama_http = httpx.Client(base_url=base_url, timeout=60.0)
        logger.info("[pool] Ollama httpx.Client ready → %s (timeout=60s)", base_url)

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def qdrant(self) -> QdrantClient:
        if self._qdrant is None:
            raise RuntimeError(
                "QdrantClient is not in the pool. "
                "Ensure STORAGE_BACKEND=qdrant-neo4j and the pool is initialised."
            )
        return self._qdrant

    @property
    def neo4j(self) -> Driver:
        if self._neo4j is None:
            raise RuntimeError(
                "Neo4j Driver is not in the pool. "
                "Ensure STORAGE_BACKEND=qdrant-neo4j and the pool is initialised."
            )
        return self._neo4j

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            raise RuntimeError(
                "httpx.Client is not in the pool. "
                "Ensure LLM_BACKEND=vllm and the pool is initialised."
            )
        return self._http

    @property
    def async_http(self) -> httpx.AsyncClient:
        if self._async_http is None:
            raise RuntimeError(
                "httpx.AsyncClient is not in the pool. "
                "Ensure LLM_BACKEND=vllm and the pool is initialised."
            )
        return self._async_http

    @property
    def ollama_http(self) -> httpx.Client:
        if self._ollama_http is None:
            raise RuntimeError(
                "Ollama httpx.Client is not in the pool. "
                "Ensure EMBEDDINGS_BACKEND=local and the pool is initialised."
            )
        return self._ollama_http

    # ── Teardown ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close all clients (synchronous path).

        AsyncClient requires an await for proper teardown. This method handles
        it best-effort: creates a temporary event loop when none is running.
        For production shutdown from an async context, prefer aclose() which
        awaits AsyncClient.aclose() correctly.
        """
        if self._qdrant:
            self._qdrant.close()
            logger.info("[pool] QdrantClient closed")
        if self._neo4j:
            self._neo4j.close()
            logger.info("[pool] Neo4j Driver closed")
        if self._http:
            self._http.close()
            logger.info("[pool] httpx.Client closed")
        if self._ollama_http:
            self._ollama_http.close()
            logger.info("[pool] Ollama httpx.Client closed")
        if self._async_http:
            import asyncio
            try:
                asyncio.get_running_loop()
                # A loop is already running (e.g. called from a sync test inside pytest-asyncio).
                # aclose() is a coroutine — we cannot block here. Log and leave GC to handle it.
                # Production code reaches this branch only if close() is mistakenly called
                # instead of aclose() during async shutdown; aclose() sets _async_http=None first.
                logger.warning(
                    "[pool] close() called while event loop is running — "
                    "AsyncClient will be closed by GC. Use aclose() for proper async teardown."
                )
            except RuntimeError:
                # No running loop — safe to run a temporary one for teardown.
                asyncio.run(self._async_http.aclose())
                logger.info("[pool] httpx.AsyncClient closed (sync path)")
            self._async_http = None
        self._qdrant = self._neo4j = self._http = self._ollama_http = None

    async def aclose(self) -> None:
        """Async-safe teardown: awaits AsyncClient.aclose(), then calls close()."""
        if self._async_http:
            await self._async_http.aclose()
            logger.info("[pool] httpx.AsyncClient closed")
            self._async_http = None
        self.close()


# ── Module-level singleton ────────────────────────────────────────────────────

_pool: ConnectionPool | None = None


def init_pool(settings: Settings) -> ConnectionPool:
    """Create and initialise the global pool. Called once from lifespan.

    If a pool is already active (e.g. app recreated in tests or a double-init
    bug), the old pool is closed synchronously before the new one is created so
    that no Qdrant / Neo4j / httpx connections are leaked.
    """
    global _pool
    if _pool is not None:
        logger.warning(
            "[pool] init_pool() called while a pool is already active — "
            "closing old pool to prevent connection leak"
        )
        _pool.close()
        _pool = None
    _pool = ConnectionPool()
    _pool.initialize(settings)
    return _pool


def get_pool() -> ConnectionPool:
    """Return the active pool. Raises if init_pool() was never called."""
    if _pool is None:
        raise RuntimeError(
            "ConnectionPool is not initialised. "
            "init_pool(settings) must be called during application startup."
        )
    return _pool


def close_pool() -> None:
    """Close all pooled clients (sync). Called from sync contexts or tests."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None


async def aclose_pool() -> None:
    """Async-safe pool teardown. Called from FastAPI lifespan (async context)."""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
