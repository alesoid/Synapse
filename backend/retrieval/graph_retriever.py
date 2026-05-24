from dataclasses import dataclass

from backend.core.config import Settings
from backend.db.graph_queries import GraphQueryService
from backend.db.neo4j_driver import Neo4jDriver

__all__ = ["GraphResult", "get_graph_retriever"]


@dataclass(frozen=True)
class GraphResult:
    doc_id: str
    section_title: str
    summary: str
    access_level: int


class Neo4jGraphRetriever:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def search(
        self,
        entity_names: list[str],
        user_access_level: int,
        depth: int = 2,
    ) -> list[GraphResult]:
        from backend.core.connections import get_pool

        # Non-owning wrapper: reuses the pooled bolt driver, no new TCP connection
        with Neo4jDriver.from_pool(get_pool().neo4j) as driver:
            rows = GraphQueryService(driver).graph_search(
                entity_names=entity_names,
                access_level=user_access_level,
                depth=depth,
            )
        return [
            GraphResult(
                doc_id=row.get("doc_id", ""),
                section_title=row.get("section_title", ""),
                summary=row.get("summary", ""),
                access_level=int(row.get("access_level", 0)),
            )
            for row in rows
        ]


class MockGraphRetriever:
    def search(
        self,
        entity_names: list[str],
        user_access_level: int,
        depth: int = 2,
    ) -> list[GraphResult]:
        return []


def get_graph_retriever(settings: Settings) -> Neo4jGraphRetriever | MockGraphRetriever:
    if settings.storage_backend == "mock":
        return MockGraphRetriever()
    if settings.storage_backend == "qdrant-neo4j":
        return Neo4jGraphRetriever(settings)
    raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.storage_backend}")
