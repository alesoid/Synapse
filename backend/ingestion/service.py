from datetime import date
from pathlib import Path

from backend.core.config import Settings
from backend.ingestion.chunker import chunk_document
from backend.ingestion.corpus_loader import load_markdown_corpus
from backend.ingestion.models import DocumentMetadata, IngestionResult, PreparedDocument
from backend.ingestion.storage import get_storage_writer

_LEVEL_TO_ROLE = {1: "junior", 2: "middle", 3: "senior", 4: "manager", 5: "admin"}


def _extract_title(content: str, fallback: str) -> str:
    """Return the text of the first Markdown heading, or fallback."""
    for line in content.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title
    return fallback


def ingest_single_document(
    settings: Settings,
    *,
    doc_id: str,
    content: str,
    access_level: int,
    doc_type: str = "document",
    last_updated: str | None = None,
) -> IngestionResult:
    """Ingest a single Markdown document supplied as a string (FR-28).

    Builds DocumentMetadata from the provided fields, chunks the content,
    and writes it to the active storage backend (mock or qdrant-neo4j).
    Does NOT touch the on-disk corpus — the document lives only in the
    vector/graph stores after this call.
    """
    metadata = DocumentMetadata(
        doc_id=doc_id,
        filename=f"{doc_id}.md",
        title=_extract_title(content, fallback=doc_id),
        doc_type=doc_type,
        access_level=access_level,
        role_min=_LEVEL_TO_ROLE.get(access_level, "junior"),
        owner_department="manual",
        last_updated=last_updated or date.today().isoformat(),
        topics=[],
    )
    document = PreparedDocument(
        metadata=metadata,
        path=Path(f"manual/{doc_id}.md"),
        text=content,
    )
    chunks = chunk_document(document, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
    writer = get_storage_writer(settings)
    return writer.write([metadata], chunks)


def ingest_markdown_corpus(settings: Settings) -> IngestionResult:
    manifest_path = Path(settings.corpus_manifest_path)
    corpus_dir = Path(settings.corpus_adapted_dir)
    documents = load_markdown_corpus(manifest_path=manifest_path, corpus_dir=corpus_dir)
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(
            document,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
    ]
    writer = get_storage_writer(settings)
    return writer.write([document.metadata for document in documents], chunks)
