"""
Neo4j infrastructure layer.

Neo4jDriver is the *only* class that knows about bolt protocol, auth, and
connection lifecycle. All higher-level layers (GraphRepository, GraphQueryService)
receive a driver instance and call execute() — they never open connections directly.

Two construction modes
----------------------
Owned (default) — driver opens and closes its own bolt connection:
    with Neo4jDriver(uri, user, password) as driver:
        rows = driver.execute("MATCH (n) RETURN count(n) AS cnt", {})

Non-owning (pool mode) — wraps a shared driver from ConnectionPool:
    raw = get_pool().neo4j             # neo4j.Driver from the pool
    driver = Neo4jDriver.from_pool(raw)
    rows = driver.execute(...)
    # close() is a no-op — the pool owns the raw driver's lifecycle
"""

from __future__ import annotations

import logging
import os
from typing import Any

from neo4j import Driver, GraphDatabase, Result
from neo4j.exceptions import AuthError, ServiceUnavailable

logger = logging.getLogger(__name__)


class Neo4jDriver:
    """Thin bolt-connection wrapper.

    Responsibilities:
      - open / verify / close the driver  (owned mode)
      - wrap a shared pool driver          (non-owning mode, via from_pool())
      - execute arbitrary Cypher and return list[dict]
      - act as a context manager in both modes
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        *,
        _raw_driver: Driver | None = None,
    ) -> None:
        if _raw_driver is not None:
            # Non-owning: wrap a shared driver — do NOT close on exit
            self._driver: Driver | None = _raw_driver
            self._owned = False
        else:
            # Owned: open our own connection
            self._uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
            self._user = user or os.getenv("NEO4J_USER", "neo4j")
            self._password = password or os.getenv("NEO4J_PASSWORD", "synapse_secret")
            self._driver = None
            self._owned = True
            self._open()

    @classmethod
    def from_pool(cls, raw_driver: Driver) -> "Neo4jDriver":
        """Wrap a pool-managed raw neo4j.Driver (non-owning).

        The returned instance can be used as a context manager; close() / __exit__
        will NOT close the raw driver — the pool owns its lifecycle.
        """
        return cls(_raw_driver=raw_driver)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _open(self) -> None:
        try:
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
            )
            self._driver.verify_connectivity()
            logger.info("[neo4j] connected: %s", self._uri)
        except (ServiceUnavailable, AuthError) as exc:
            logger.error("[neo4j] connection failed: %s", exc)
            raise

    def close(self) -> None:
        if self._owned and self._driver:
            self._driver.close()
            self._driver = None
            logger.info("[neo4j] connection closed")
        # non-owning: no-op — pool is responsible for closing the raw driver

    def __enter__(self) -> "Neo4jDriver":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Query execution ───────────────────────────────────────────────────────

    def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Run *query* and return all rows as a list of plain dicts."""
        if self._driver is None:
            raise RuntimeError("Neo4jDriver is closed — cannot execute queries")
        with self._driver.session() as session:
            result: Result = session.run(query, parameters or {})
            return [record.data() for record in result]
