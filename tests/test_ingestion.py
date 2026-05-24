from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.ingestion.chunker import chunk_document
from backend.ingestion.corpus_loader import load_markdown_corpus
from backend.ingestion.service import ingest_markdown_corpus


MANIFEST_PATH = Path("docs/corpus/corpus_manifest.json")
CORPUS_DIR = Path("docs/corpus/adapted")


def configure_mock_ingestion(monkeypatch):
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    monkeypatch.setenv("CORPUS_MANIFEST_PATH", str(MANIFEST_PATH))
    monkeypatch.setenv("CORPUS_ADAPTED_DIR", str(CORPUS_DIR))
    get_settings.cache_clear()


def test_loads_markdown_documents_from_manifest():
    documents = load_markdown_corpus(MANIFEST_PATH, CORPUS_DIR)

    assert len(documents) == 15
    assert {document.metadata.doc_id for document in documents}
    assert all(document.path.suffix == ".md" for document in documents)
    assert all(document.metadata.access_level in {1, 2, 3, 4, 5} for document in documents)


def test_chunks_have_required_metadata():
    document = load_markdown_corpus(MANIFEST_PATH, CORPUS_DIR)[0]
    chunks = chunk_document(document, chunk_size=500, overlap=50)

    assert chunks
    first = chunks[0]
    assert first.doc_id == document.metadata.doc_id
    assert first.doc_type == document.metadata.doc_type
    assert first.access_level == document.metadata.access_level
    assert first.last_updated == document.metadata.last_updated
    assert first.section_title
    assert first.text


def test_mock_ingestion_projects_graph_large_enough(monkeypatch):
    configure_mock_ingestion(monkeypatch)

    result = ingest_markdown_corpus(get_settings())

    assert result.documents_processed == 15
    assert result.chunks_created > 50
    assert result.graph_nodes_projected > 50
    assert result.graph_edges_projected > 100
    assert result.storage_backend == "mock"

    get_settings.cache_clear()


def test_ingest_endpoint_runs_corpus_ingestion_in_mock_mode(monkeypatch):
    configure_mock_ingestion(monkeypatch)
    client = TestClient(create_app())

    response = client.post("/ingest", headers={"X-User-Role": "admin"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["documents_processed"] == 15
    assert body["chunks_created"] > 50
    assert body["graph_nodes_projected"] > 50
    assert body["graph_edges_projected"] > 100
    assert body["storage_backend"] == "mock"

    get_settings.cache_clear()
