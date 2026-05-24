from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.retrieval.vector_retriever import build_qdrant_rbac_filter
from backend.security.rbac import ROLES, filter_authorized_items, role_to_access_level


def make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_role_to_access_level_mapping():
    assert role_to_access_level("junior") == 1
    assert role_to_access_level("middle") == 2
    assert role_to_access_level("senior") == 3
    assert role_to_access_level("manager") == 4
    assert role_to_access_level("admin") == 5
    assert role_to_access_level("Senior") == 3
    assert set(ROLES) == {"junior", "middle", "senior", "manager", "admin"}


def test_graph_endpoint_is_admin_only(monkeypatch):
    client = make_client(monkeypatch)

    junior_response = client.get("/graph", headers={"X-User-Role": "junior"})
    admin_response = client.get("/graph", headers={"X-User-Role": "admin"})

    assert junior_response.status_code == 403
    assert admin_response.status_code == 200

    get_settings.cache_clear()


def test_knowledge_gaps_endpoint_is_admin_only(monkeypatch):
    """FR-33: /knowledge-gaps is restricted to admin role only."""
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDINGS_BACKEND", "mock")
    monkeypatch.setenv("STORAGE_BACKEND", "mock")
    get_settings.cache_clear()

    # Use context manager so FastAPI lifespan runs → gap store gets initialised
    with TestClient(create_app()) as client:
        junior_response = client.get("/knowledge-gaps", headers={"X-User-Role": "junior"})
        manager_response = client.get("/knowledge-gaps", headers={"X-User-Role": "manager"})
        admin_response = client.get("/knowledge-gaps", headers={"X-User-Role": "admin"})

    assert junior_response.status_code == 403   # not enough clearance
    assert manager_response.status_code == 403  # FR-33: Admin only (not manager)
    assert admin_response.status_code == 200    # admin passes

    get_settings.cache_clear()


def test_junior_filter_excludes_level_4_and_5_items():
    items = [
        {"doc_id": "public", "access_level": 1},
        {"doc_id": "standard", "access_level": 2},
        {"doc_id": "manager", "access_level": 4},
        {"doc_id": "admin", "access_level": 5},
    ]

    authorized = filter_authorized_items(items, user_access_level=1)

    assert authorized == [{"doc_id": "public", "access_level": 1}]


def test_filter_treats_null_access_level_as_public():
    """NULL access_level → treated as level 1 (public), consistent with Cypher COALESCE."""
    items = [
        {"doc_id": "unlabelled"},           # no access_level key at all
        {"doc_id": "explicit_null", "access_level": None},
        {"doc_id": "public", "access_level": 1},
        {"doc_id": "restricted", "access_level": 3},
    ]

    # Junior (level 1) should see unlabelled, explicit_null, and public — not restricted
    authorized = filter_authorized_items(items, user_access_level=1)
    doc_ids = [item["doc_id"] for item in authorized]
    assert "unlabelled" in doc_ids
    assert "explicit_null" in doc_ids
    assert "public" in doc_ids
    assert "restricted" not in doc_ids

    # Senior (level 3) sees everything
    all_items = filter_authorized_items(items, user_access_level=3)
    assert len(all_items) == 4


def test_qdrant_rbac_filter_uses_access_level_lte():
    query_filter = build_qdrant_rbac_filter(user_access_level=3)
    data = query_filter.model_dump(mode="json", exclude_none=True)

    assert data == {
        "must": [
            {
                "key": "access_level",
                "range": {"lte": 3.0},
            }
        ]
    }
