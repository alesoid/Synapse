"""
SQLite-backed audit log (ФЗ-152 / FR-security).

Records every /query request regardless of outcome — who queried (role +
access_level), a SHA-256 hash of the query text (plain text is NOT stored),
how many sources were retrieved, the quality score from CriticAgent, and
whether a knowledge gap was detected.

Design
------
Mirrors gap_store.py: one persistent connection per process, WAL journal mode,
write lock for concurrent INSERT safety.  PostgreSQL is the scale-target
(see data_architecture.md §6); SQLite is the local-lite fallback.

Graceful degradation
--------------------
If init_audit_store() was never called (e.g. unit tests), record_audit()
logs a warning and returns silently — the query pipeline is never disrupted
by storage unavailability.

Note: spec target is PostgreSQL for production; SQLite is the MVP fallback.
Schema columns are designed to match the PostgreSQL target.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Module-level persistent state ─────────────────────────────────────────────

_conn: sqlite3.Connection | None = None
_write_lock = threading.Lock()   # serialises INSERTs within one process

_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_role     TEXT    NOT NULL,
    access_level  INTEGER NOT NULL,
    query_hash    TEXT    NOT NULL,   -- SHA-256 hex of query text
    result_count  INTEGER,            -- number of sources returned
    quality_score REAL,               -- CriticAgent score (1.0–4.0)
    gap_detected  INTEGER DEFAULT 0,  -- 1 if knowledge gap was recorded
    timestamp     TEXT    NOT NULL    -- ISO UTC
)
"""

_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log (timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_role      ON audit_log (user_role)",
]


# ── Lifecycle (called from lifespan) ──────────────────────────────────────────

def init_audit_store(path: str | Path = "audit.db") -> None:
    """Open a persistent SQLite connection and ensure the schema exists.

    Must be called once during application startup (lifespan).
    Enables WAL mode for better concurrent-read performance.
    """
    global _conn
    db_path = Path(path)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL)
    for idx in _IDX:
        conn.execute(idx)
    conn.commit()
    _conn = conn
    logger.info("[audit_store] ready: %s (WAL mode)", db_path)


def close_audit_store() -> None:
    """Close the persistent connection. Called from lifespan on shutdown."""
    global _conn
    if _conn:
        _conn.close()
        _conn = None
        logger.info("[audit_store] closed")


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError(
            "Audit store is not initialised. "
            "Call init_audit_store() during application startup."
        )
    return _conn


# ── Helpers ───────────────────────────────────────────────────────────────────

def hash_query(query: str) -> str:
    """Return SHA-256 hex digest of the query text (plain text is not stored)."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


# ── Public API ────────────────────────────────────────────────────────────────

def record_audit(
    user_role: str,
    access_level: int,
    query: str,
    result_count: int | None = None,
    quality_score: float | None = None,
    gap_detected: bool = False,
) -> None:
    """Persist one audit record for a /query request (ФЗ-152 compliance).

    Silently skips if the store was not initialised (e.g. unit tests)
    so the query pipeline is never disrupted by storage unavailability.

    Args:
        user_role:     Raw X-User-Role header value (e.g. "junior").
        access_level:  Numeric RBAC level derived from role (1–5).
        query:         Original query text — only its SHA-256 hash is stored.
        result_count:  Number of sources returned to the user.
        quality_score: CriticAgent quality score (1.0–4.0).
        gap_detected:  True if a knowledge gap was recorded for this query.
    """
    if _conn is None:
        logger.warning(
            "[audit_store] not initialised — audit not persisted for role=%s", user_role
        )
        return
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        _get_conn().execute(
            "INSERT INTO audit_log "
            "(user_role, access_level, query_hash, result_count, quality_score, gap_detected, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_role,
                access_level,
                hash_query(query),
                result_count,
                round(quality_score, 2) if quality_score is not None else None,
                1 if gap_detected else 0,
                ts,
            ),
        )
        _get_conn().commit()


def list_audit(limit: int = 200) -> list[dict]:
    """Return the most recent *limit* audit records, newest first (admin only)."""
    rows = _get_conn().execute(
        "SELECT id, user_role, access_level, query_hash, "
        "result_count, quality_score, gap_detected, timestamp "
        "FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "user_role": r[1],
            "access_level": r[2],
            "query_hash": r[3],
            "result_count": r[4],
            "quality_score": r[5],
            "gap_detected": bool(r[6]),
            "timestamp": r[7],
        }
        for r in rows
    ]


def count_audit() -> int:
    """Return total number of audit records."""
    return _get_conn().execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
