"""Tests for backend/db/audit_store.py (ФЗ-152 audit log)."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from backend.db.audit_store import (
    close_audit_store,
    count_audit,
    hash_query,
    init_audit_store,
    list_audit,
    record_audit,
)


@pytest.fixture()
def audit_db(tmp_path: Path):
    """Initialise a fresh in-temp audit store; teardown after test."""
    db = tmp_path / "test_audit.db"
    init_audit_store(db)
    yield
    close_audit_store()


def test_hash_query_is_sha256():
    q = "Как оформить отпуск?"
    assert hash_query(q) == hashlib.sha256(q.encode("utf-8")).hexdigest()
    assert len(hash_query(q)) == 64  # SHA-256 hex length


def test_hash_query_plain_text_not_stored(audit_db):
    """Verify the stored hash cannot be reversed to the original query."""
    q = "секретный запрос с персональными данными"
    record_audit(user_role="junior", access_level=1, query=q)
    records = list_audit()
    assert records[0]["query_hash"] != q
    assert len(records[0]["query_hash"]) == 64


def test_record_and_list(audit_db):
    record_audit(
        user_role="senior",
        access_level=3,
        query="Что такое архитектурный стандарт?",
        result_count=5,
        quality_score=3.5,
        gap_detected=False,
    )
    records = list_audit()
    assert len(records) == 1
    r = records[0]
    assert r["user_role"] == "senior"
    assert r["access_level"] == 3
    assert r["result_count"] == 5
    assert r["quality_score"] == 3.5
    assert r["gap_detected"] is False
    assert "timestamp" in r


def test_gap_detected_recorded(audit_db):
    record_audit(
        user_role="junior",
        access_level=1,
        query="Вопрос без ответа",
        result_count=0,
        quality_score=1.0,
        gap_detected=True,
    )
    records = list_audit()
    assert records[0]["gap_detected"] is True


def test_count_audit(audit_db):
    assert count_audit() == 0
    record_audit(user_role="middle", access_level=2, query="запрос 1")
    record_audit(user_role="admin", access_level=5, query="запрос 2")
    assert count_audit() == 2


def test_list_audit_newest_first(audit_db):
    record_audit(user_role="junior", access_level=1, query="первый")
    record_audit(user_role="admin", access_level=5, query="второй")
    records = list_audit()
    # newest first — admin record has higher id
    assert records[0]["user_role"] == "admin"
    assert records[1]["user_role"] == "junior"


def test_record_audit_graceful_without_init():
    """record_audit() must not raise if store was never initialised."""
    close_audit_store()  # ensure store is closed
    # Should log a warning and return silently — not raise
    record_audit(user_role="junior", access_level=1, query="тест без init")


def test_optional_fields_nullable(audit_db):
    """result_count, quality_score may be None (e.g. error path)."""
    record_audit(user_role="middle", access_level=2, query="запрос")
    r = list_audit()[0]
    assert r["result_count"] is None
    assert r["quality_score"] is None
