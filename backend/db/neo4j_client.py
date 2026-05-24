"""
Neo4j backward-compatibility facade.

Neo4jClient composes Neo4jDriver + GraphRepository + GraphQueryService
and re-exports their methods under the original flat API.

New code should import the focused classes directly:
    from backend.db.neo4j_driver      import Neo4jDriver
    from backend.db.graph_repository  import GraphRepository
    from backend.db.graph_queries     import GraphQueryService

This facade exists only for test_neo4j.py and any external code
that still depends on the old monolithic interface.
"""

from __future__ import annotations

from typing import Any

from backend.db.graph_queries import GraphQueryService
from backend.db.graph_repository import GraphRepository
from backend.db.neo4j_driver import Neo4jDriver


class Neo4jClient:
    """Thin facade over Neo4jDriver + GraphRepository + GraphQueryService.

    Provides the original monolithic API; all calls are delegated
    to the appropriate focused class.
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._driver = Neo4jDriver(uri=uri, user=user, password=password)
        self._repo = GraphRepository(self._driver)
        self._queries = GraphQueryService(self._driver)

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._driver.close()

    # ── Delegated: GraphRepository ────────────────────────────────────────────

    def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict]:
        return self._driver.execute(query, parameters)

    def create_node(self, label: str, properties: dict[str, Any]) -> str:
        return self._repo.merge_node(label, properties)

    def create_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        self._repo.merge_relationship(from_id, to_id, rel_type, properties)

    # ── Delegated: GraphQueryService ──────────────────────────────────────────

    def graph_search(
        self,
        entity_names: list[str],
        access_level: int,
        depth: int = 2,
    ) -> list[dict]:
        return self._queries.graph_search(entity_names, access_level, depth)

    def get_neighbors(
        self,
        node_id: str,
        access_level: int,
        depth: int = 2,
    ) -> list[dict]:
        return self._queries.get_neighbors(node_id, access_level, depth)

    def search_by_property(
        self,
        label: str,
        key: str,
        value: Any,
        access_level: int = 5,
    ) -> list[dict]:
        return self._queries.search_by_property(label, key, value, access_level)

    def get_graph_for_explorer(self, access_level: int = 5) -> dict:
        return self._queries.get_graph_for_explorer(access_level)

    def get_stats(self) -> dict:
        return self._queries.get_stats()
