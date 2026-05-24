from pathlib import Path

from backend.core.config import Settings
from backend.ingestion.chunker import chunk_document
from backend.ingestion.corpus_loader import load_markdown_corpus
from backend.ingestion.models import IngestionResult
from backend.ingestion.storage import get_storage_writer


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
