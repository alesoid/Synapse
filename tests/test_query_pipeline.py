import asyncio

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.query.pipeline import (
    MergedSource,
    _compute_confidence,
    _merge,
    extract_entities,
)
from backend.retrieval.vector_retriever import RetrievedChunk


def make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()
    return TestClient(create_app())


# ── entity extraction ──────────────────────────────────────────────────────────


def test_extract_entities_filters_stopwords():
    entities = extract_entities("Как получить доступ к GitLab?")
    lowered = [e.lower() for e in entities]
    assert "как" not in lowered
    assert "gitlab" in lowered
    assert "доступ" in lowered


def test_extract_entities_empty_on_stopwords_only():
    entities = extract_entities("и в на с")
    assert entities == []


# ── merge ──────────────────────────────────────────────────────────────────────


def _make_chunk(doc_id: str, section: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        doc_id=doc_id,
        section_title=section,
        text="chunk text",
        access_level=1,
        last_updated="2025-10-01",
        score=score,
    )


def test_merge_boosts_vector_chunk_found_in_graph():
    """RRF: chunk present in both lists scores higher than chunk only in vector."""
    from backend.retrieval.graph_retriever import GraphResult

    # chunk in both vector + graph
    vector_chunks = [_make_chunk("doc1", "intro", 0.8)]
    graph_results = [GraphResult(doc_id="doc1", section_title="intro", summary="...", access_level=1)]
    merged_both = _merge(vector_chunks, graph_results)

    # same chunk, vector only (no graph match)
    merged_vector_only = _merge(vector_chunks, [])

    assert len(merged_both) == 1
    assert merged_both[0].score > merged_vector_only[0].score, (
        "RRF: graph presence should boost score above vector-only"
    )


def test_merge_graph_only_result_has_positive_score():
    """RRF: graph-only result gets a positive score (not a constant 0.3)."""
    from backend.retrieval.graph_retriever import GraphResult

    vector_chunks: list[RetrievedChunk] = []
    graph_results = [
        GraphResult(doc_id="doc2", section_title="sec", summary="...", access_level=1,
                    match_count=1, hop_distance=2),
    ]
    merged = _merge(vector_chunks, graph_results)

    assert len(merged) == 1
    assert merged[0].score > 0.0


def test_merge_higher_match_count_ranks_first():
    """RRF: graph result with more entity matches ranks above one with fewer."""
    from backend.retrieval.graph_retriever import GraphResult

    vector_chunks: list[RetrievedChunk] = []
    graph_results = [
        GraphResult(doc_id="doc_low",  section_title="s", summary="", access_level=1,
                    match_count=1, hop_distance=2),
        GraphResult(doc_id="doc_high", section_title="s", summary="", access_level=1,
                    match_count=3, hop_distance=1),
    ]
    merged = _merge(vector_chunks, graph_results)

    assert len(merged) == 2
    assert merged[0].doc_id == "doc_high", "Higher match_count should rank first"


def test_merge_deduplicates_by_doc_and_section():
    from backend.retrieval.graph_retriever import GraphResult

    vector_chunks = [_make_chunk("doc1", "sec", 0.6)]
    graph_results = [GraphResult(doc_id="doc1", section_title="sec", summary="...", access_level=1)]

    merged = _merge(vector_chunks, graph_results)

    assert len(merged) == 1


# ── confidence ─────────────────────────────────────────────────────────────────


def _make_source(last_updated: str | None) -> MergedSource:
    return MergedSource(
        doc_id="d", section_title="s", text="t",
        access_level=1, last_updated=last_updated, score=0.5,
    )


def test_confidence_zero_when_no_sources():
    assert _compute_confidence([]) == 0.0


def test_confidence_high_for_recent_sources():
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=30)).isoformat()  # 30 days ago → always ≥ 0.9
    score = _compute_confidence([_make_source(recent)])
    assert score >= 0.7


def test_confidence_low_for_old_sources():
    score = _compute_confidence([_make_source("2020-01-01")])
    assert score <= 0.5


# ── agent integration (mock mode) ─────────────────────────────────────────────


def test_agent_returns_gap_detected_in_mock_mode(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    get_settings.cache_clear()

    from backend.query.service import QueryService
    result = asyncio.run(
        QueryService(get_settings()).ask("Как получить доступ к GitLab?", access_level=3)
    )

    assert result.gap_detected is True  # no sources → quality_score = 1.0 < 2.0
    assert result.confidence_score == 0.0
    assert result.quality_score == 1.0
    assert result.sources == []

    get_settings.cache_clear()


def test_query_endpoint_returns_full_response_structure(monkeypatch):
    client = make_client(monkeypatch)

    response = client.post(
        "/query",
        json={"query": "Какова политика доступа к репозиториям?"},
        headers={"X-User-Role": "manager"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "sources" in body
    assert "quality_score" in body
    assert "confidence_score" in body
    assert "gap_detected" in body
    assert body["gap_detected"] is True

    get_settings.cache_clear()


def test_query_endpoint_rejects_blank_query(monkeypatch):
    client = make_client(monkeypatch)

    response = client.post(
        "/query",
        json={"query": "   "},
        headers={"X-User-Role": "junior"},
    )

    assert response.status_code == 422

    get_settings.cache_clear()
