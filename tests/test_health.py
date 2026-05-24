from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings


def test_health_returns_local_lite_configuration(monkeypatch):
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "mode": "test",
        "components": {
            "api": "ok",
            "llm_backend": "mock",
            "embeddings_backend": "mock",
            "storage_backend": "mock",
        },
    }

    get_settings.cache_clear()
