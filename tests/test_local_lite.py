from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.embeddings.client import MockEmbeddingsClient


def make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_query_uses_deterministic_mock_backend(monkeypatch):
    client = make_client(monkeypatch)
    payload = {"query": "Какие ветки используются в Git workflow?", "stream": False}
    headers = {"X-User-Role": "senior"}

    first = client.post("/query", json=payload, headers=headers)
    second = client.post("/query", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["answer"].startswith("[mock-llm]")
    assert first.json()["quality_score"] == 1.0  # MockCriticAgent: 1.0 + 0 sources
    assert first.json()["trace_id"].startswith("mock-3-")
    assert first.json()["trace_id"].endswith("-i3")  # 3 retry iterations exhausted

    get_settings.cache_clear()


def test_query_requires_known_user_role(monkeypatch):
    client = make_client(monkeypatch)

    missing = client.post("/query", json={"query": "test query"})
    unknown = client.post(
        "/query",
        json={"query": "test query"},
        headers={"X-User-Role": "owner"},
    )

    assert missing.status_code == 403
    assert unknown.status_code == 403

    get_settings.cache_clear()


def test_mock_embeddings_are_stable_and_normalized():
    client = MockEmbeddingsClient(dimension=16)

    first = client.embed_query("GitLab access policy")
    second = client.embed_query("GitLab access policy")

    assert first == second
    assert len(first) == 16
    assert all(-1.0 <= value <= 1.0 for value in first)
