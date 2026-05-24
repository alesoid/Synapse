import uuid
from typing import Protocol

from backend.core.config import Settings
from backend.embeddings.client import get_embeddings_client
from backend.ingestion.models import DocumentChunk, DocumentMetadata, IngestionResult


class IngestionStorageWriter(Protocol):
    def write(self, documents: list[DocumentMetadata], chunks: list[DocumentChunk]) -> IngestionResult:
        """Persist chunks and graph projection."""


def topic_id(topic: str) -> str:
    normalized = topic.strip().lower().replace(" ", "-")
    return f"topic::{normalized}"


def _compute_projection_stats(
    documents: list[DocumentMetadata],
    chunks: list[DocumentChunk],
    storage_backend: str,
) -> IngestionResult:
    """Calculate graph projection counters independent of storage backend.

    Extracted to avoid instantiating MockStorageWriter inside production code.
    """
    document_nodes = {doc.doc_id for doc in documents}
    section_nodes = {chunk.chunk_id for chunk in chunks}
    topic_nodes = {topic_id(t) for doc in documents for t in doc.topics}
    section_edges = len(chunks)
    doc_topic_edges = sum(len(doc.topics) for doc in documents)
    section_topic_edges = sum(len(chunk.topics) for chunk in chunks)
    return IngestionResult(
        documents_processed=len(documents),
        chunks_created=len(chunks),
        graph_nodes_projected=len(document_nodes | section_nodes | topic_nodes),
        graph_edges_projected=section_edges + doc_topic_edges + section_topic_edges,
        storage_backend=storage_backend,
    )


class MockStorageWriter:
    def write(self, documents: list[DocumentMetadata], chunks: list[DocumentChunk]) -> IngestionResult:
        return _compute_projection_stats(documents, chunks, storage_backend="mock")


class QdrantNeo4jStorageWriter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def write(self, documents: list[DocumentMetadata], chunks: list[DocumentChunk]) -> IngestionResult:
        self._write_qdrant(chunks)
        self._write_neo4j(documents, chunks)
        return _compute_projection_stats(documents, chunks, storage_backend="qdrant-neo4j")

    def _write_qdrant(self, chunks: list[DocumentChunk]) -> None:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        from backend.core.connections import get_pool

        emb_client = get_embeddings_client(self._settings)
        qdrant = get_pool().qdrant          # shared — no new connection per ingestion
        vector_size = self._settings.embedding_dimension
        collection_names = {c.name for c in qdrant.get_collections().collections}
        if self._settings.qdrant_collection not in collection_names:
            qdrant.create_collection(
                collection_name=self._settings.qdrant_collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

        if not chunks:
            return

        # Single batch call → 1 HTTP round-trip to Ollama instead of N.
        # MockEmbeddingsClient.embed_batch() maps embed_query() locally (no I/O).
        vectors = emb_client.embed_batch([chunk.text for chunk in chunks])

        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
                vector=vector,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "doc_type": chunk.doc_type,
                    "access_level": chunk.access_level,
                    "last_updated": chunk.last_updated,
                    "section_title": chunk.section_title,
                    "text": chunk.text,
                    "chunk_index": chunk.chunk_index,
                    "source": chunk.source,
                    "topics": chunk.topics,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        qdrant.upsert(collection_name=self._settings.qdrant_collection, points=points)

    def _write_neo4j(self, documents: list[DocumentMetadata], chunks: list[DocumentChunk]) -> None:
        """Write graph structure using UNWIND batch queries — O(1) round-trips.

        Old N+1 pattern (O(N×M + K×L) queries) replaced with 5 batched UNWIND
        statements regardless of corpus size.
        """
        from backend.db.graph_repository import GraphRepository
        from backend.db.neo4j_driver import Neo4jDriver

        # ── Build batches in Python first (zero network calls) ───────────────
        doc_rows = [
            {
                "id": doc.doc_id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "access_level": doc.access_level,
                "last_updated": doc.last_updated,
                "owner_department": doc.owner_department,
            }
            for doc in documents
        ]

        # Deduplicate concepts across all documents
        seen_concepts: set[str] = set()
        concept_rows: list[dict] = []
        doc_concept_rels: list[dict] = []
        for doc in documents:
            for t in doc.topics:
                tid = topic_id(t)
                if tid not in seen_concepts:
                    seen_concepts.add(tid)
                    concept_rows.append(
                        {"id": tid, "name": t, "canonical_name": t, "access_level": doc.access_level}
                    )
                doc_concept_rels.append({"from_id": doc.doc_id, "to_id": tid})

        section_rows = [
            {
                "id": chunk.chunk_id,
                "title": chunk.section_title,
                "content_summary": chunk.text[:500],
                "doc_id": chunk.doc_id,
                "doc_type": chunk.doc_type,
                "access_level": chunk.access_level,
                "last_updated": chunk.last_updated,
                "chunk_index": chunk.chunk_index,
            }
            for chunk in chunks
        ]

        has_section_rels = [{"from_id": c.doc_id, "to_id": c.chunk_id} for c in chunks]

        section_concept_rels = [
            {"from_id": c.chunk_id, "to_id": topic_id(t)}
            for c in chunks
            for t in c.topics
        ]

        # ── 5 round-trips regardless of corpus size ───────────────────────────
        from backend.core.connections import get_pool

        # Non-owning wrapper: pool owns the bolt driver lifecycle
        with Neo4jDriver.from_pool(get_pool().neo4j) as driver:
            repo = GraphRepository(driver)
            repo.merge_nodes_batch("Document", doc_rows)
            repo.merge_nodes_batch("Concept", concept_rows)
            repo.merge_nodes_batch("Section", section_rows)
            repo.merge_relationships_batch("REFERENCES", doc_concept_rels)
            repo.merge_relationships_batch("HAS_SECTION", has_section_rels)
            if section_concept_rels:
                repo.merge_relationships_batch("REFERENCES", section_concept_rels)


def get_storage_writer(settings: Settings) -> IngestionStorageWriter:
    if settings.storage_backend == "mock":
        return MockStorageWriter()
    if settings.storage_backend == "qdrant-neo4j":
        return QdrantNeo4jStorageWriter(settings)
    raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.storage_backend}")
