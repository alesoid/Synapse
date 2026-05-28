"""
Domain query service — single authoritative entry point for all query execution.

Security boundary
-----------------
The injection check (FR-26) and PII masking (FR-25a/b/c) run here,
not only in the HTTP transport layer (api/schemas.py).  This guarantees
that every caller — HTTP routes, scripts, background jobs, tests — goes
through the same security gate.

Previously the guard lived exclusively in ``QueryRequest.strip_and_guard_query``
(a Pydantic field validator).  That protected the HTTP surface but allowed
``run_agent()`` to be called directly without sanitisation.  ``QueryService``
closes that gap: all non-trivial callers must go through ``QueryService.ask()``.

The Pydantic validator in ``QueryRequest`` is intentionally kept as the
*first-line* HTTP boundary check — it returns proper HTTP 422 responses with
Pydantic validation context before the request even reaches a route handler.
``QueryService`` is the *authoritative* domain-layer enforcement.
"""

from __future__ import annotations

from backend.agents.graph_agent import run_agent
from backend.core.config import Settings
from backend.query.pipeline import QueryResult
from backend.security.injection import is_injection
from backend.security.pii import mask_pii


class QueryBlockedError(ValueError):
    """Raised when a query matches a known prompt-injection pattern (FR-26)."""


class QueryService:
    """Sanitise a query and run the GraphRAG agent pipeline.

    Usage::

        service = QueryService(settings)
        result = await service.ask(query, access_level)

    Raises:
        QueryBlockedError: if ``query`` matches an injection pattern (FR-26).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def ask(self, query: str, access_level: int) -> QueryResult:
        """Apply security guard and delegate to the agent pipeline.

        Steps:
        1. Strip leading/trailing whitespace.
        2. Injection detection (FR-26) — raise ``QueryBlockedError`` if matched.
        3. PII masking (FR-25a/b/c) — replace before reaching the LLM.
        4. Delegate to ``run_agent()``.

        Args:
            query:        Raw user query string (not yet sanitised).
            access_level: RBAC access level 1–5 (derived from user role).

        Returns:
            ``QueryResult`` from the agent pipeline.
        """
        query = query.strip()
        if is_injection(query):                 # FR-26: block, raise domain error
            raise QueryBlockedError("Query blocked by security policy.")
        query = mask_pii(query)                 # FR-25a/b/c: mask, pass through
        return await run_agent(query, access_level, self._settings)
