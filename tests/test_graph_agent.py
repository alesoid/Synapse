import asyncio

from fastapi.testclient import TestClient

from backend.agents.graph_agent import build_graph, run_agent
from backend.agents.state import AgentState
from backend.api.main import create_app
from backend.core.config import get_settings


def mock_settings(monkeypatch):
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()
    return get_settings()


def _initial_state(query: str = "Какова политика доступа?", access_level: int = 3) -> AgentState:
    return {
        "query": query,
        "access_level": access_level,
        "vector_chunks": [],
        "graph_results": [],
        "sources": [],
        "answer": "",
        "quality_score": 0.0,
        "confidence_score": 0.0,
        "iterations": 0,
        "gap_detected": False,
        "trace_id": "",
    }


# ── graph topology ─────────────────────────────────────────────────────────────


def test_graph_contains_all_required_nodes(monkeypatch):
    settings = mock_settings(monkeypatch)
    graph = build_graph(settings)
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "prepare_query",    # preprocessing: strip + entity extraction (not security)
        "vector_retriever",
        "graph_retriever",
        "merge_results",
        "generator",
        "critic",
        "confidence_score",
        "output_guard",     # security: PII mask on LLM answer (FR-27)
        "knowledge_gap",
    }
    assert expected.issubset(node_names)
    get_settings.cache_clear()


# ── execution in mock mode ─────────────────────────────────────────────────────


def test_agent_returns_gap_detected_when_no_sources(monkeypatch):
    settings = mock_settings(monkeypatch)
    result = asyncio.run(run_agent("Какова политика доступа?", access_level=3, settings=settings))

    assert result.gap_detected is True
    assert result.quality_score == 1.0
    assert result.confidence_score == 0.0
    assert result.sources == []
    get_settings.cache_clear()


def test_agent_exhausts_retries_in_mock_mode(monkeypatch):
    settings = mock_settings(monkeypatch)
    graph = build_graph(settings)
    final = asyncio.run(graph.ainvoke(_initial_state()))

    assert final["iterations"] == settings.agent_max_iterations
    assert final["gap_detected"] is True
    get_settings.cache_clear()


def test_agent_is_deterministic(monkeypatch):
    settings = mock_settings(monkeypatch)
    query = "Что такое онбординг в компании?"

    first = asyncio.run(run_agent(query, access_level=2, settings=settings))
    second = asyncio.run(run_agent(query, access_level=2, settings=settings))

    assert first.answer == second.answer
    assert first.trace_id == second.trace_id
    assert first.quality_score == second.quality_score
    get_settings.cache_clear()


def test_agent_trace_id_encodes_counts_and_iterations(monkeypatch):
    settings = mock_settings(monkeypatch)
    result = asyncio.run(run_agent("Какова политика доступа?", access_level=1, settings=settings))

    assert "-v0g0-" in result.trace_id
    assert result.trace_id.endswith(f"-i{settings.agent_max_iterations}")
    get_settings.cache_clear()


# ── route integration ──────────────────────────────────────────────────────────


def test_query_endpoint_returns_gap_after_retries(monkeypatch):
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/query",
        json={"query": "Что такое онбординг в компании?"},
        headers={"X-User-Role": "senior"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["gap_detected"] is True
    assert body["quality_score"] == 1.0
    assert "-i3" in body["trace_id"]

    get_settings.cache_clear()
