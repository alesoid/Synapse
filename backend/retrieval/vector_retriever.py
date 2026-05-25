from dataclasses import dataclass
from typing import Any

from backend.core.config import Settings
from backend.embeddings.client import get_embeddings_client

__all__ = ["RetrievedChunk", "get_vector_retriever"]


@dataclass(frozen=True)
class RetrievedChunk:
    doc_id: str
    section_title: str
    text: str
    access_level: int
    last_updated: str | None
    score: float


def build_qdrant_rbac_filter(user_access_level: int) -> Any:
    from qdrant_client.models import FieldCondition, Filter, Range

    return Filter(
        must=[
            FieldCondition(
                key="access_level",
                range=Range(lte=user_access_level),
            )
        ]
    )


class QdrantVectorRetriever:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def search(self, query: str, user_access_level: int, limit: int = 10) -> list[RetrievedChunk]:
        from backend.core.connections import get_pool

        embeddings = get_embeddings_client(self._settings)
        client = get_pool().qdrant          # shared — no new connection per request
        vector = embeddings.embed_query(query)
        results = client.search(
            collection_name=self._settings.qdrant_collection,
            query_vector=vector,
            query_filter=build_qdrant_rbac_filter(user_access_level),
            limit=limit,
            with_payload=True,
        )
        chunks: list[RetrievedChunk] = []
        for result in results:
            payload = result.payload or {}
            chunks.append(
                RetrievedChunk(
                    doc_id=payload.get("doc_id", ""),
                    section_title=payload.get("section_title", ""),
                    text=payload.get("text", ""),
                    access_level=int(payload.get("access_level", 0)),
                    last_updated=payload.get("last_updated"),
                    score=float(result.score),
                )
            )
        return chunks


class MockVectorRetriever:
    def search(self, query: str, user_access_level: int, limit: int = 10) -> list[RetrievedChunk]:
        return []


def get_vector_retriever(settings: Settings) -> QdrantVectorRetriever | MockVectorRetriever:
    if settings.storage_backend == "mock":
        return MockVectorRetriever()
    if settings.storage_backend == "qdrant-neo4j":
        return QdrantVectorRetriever(settings)
    raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.storage_backend}")
