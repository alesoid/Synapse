"""
SQLite-backed store for knowledge gaps (FR-31, FR-32a/b).

Design
------
One persistent connection per process (not opened/closed per call).
WAL journal mode: concurrent readers do not block each other or the writer.
Write lock: serialises INSERT within a single process; SQLite's own WAL
  locking handles concurrency between OS processes (multiple uvicorn workers).

Lifecycle
---------
Startup  → init_gap_store(path)   called from api/main.py lifespan
Shutdown → close_gap_store()      called from api/main.py lifespan

Graceful degradation
--------------------
If init_gap_store() was never called (e.g. in unit tests that don't boot
the full app), record_gap() logs a warning and returns silently so the
query pipeline is not disrupted.  list_gaps() / count_gaps() raise
RuntimeError — callers (admin endpoints) must have the store available.

Note: spec (FR-32a/b) prescribes PostgreSQL for production; SQLite is the
local-lite fallback.  Schema columns match the PostgreSQL target:
id, query, access_level, quality_score, iterations, timestamp.
"""

from __future__ import annotations

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
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    query         TEXT    NOT NULL,
    access_level  INTEGER NOT NULL,
    quality_score REAL    NOT NULL,
    iterations    INTEGER NOT NULL DEFAULT 0,
    timestamp     TEXT    NOT NULL
)
"""


# ── Lifecycle (called from lifespan) ──────────────────────────────────────────

def init_gap_store(path: str | Path = "gaps.db") -> None:
    """Open a persistent SQLite connection and ensure the schema exists.

    Must be called once during application startup (lifespan).
    Enables WAL mode for better concurrent-read performance.
    """
    global _conn
    db_path = Path(path)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL)
    conn.commit()
    _migrate(conn)
    _conn = conn
    logger.info("[gap_store] ready: %s (WAL mode)", db_path)


def close_gap_store() -> None:
    """Close the persistent connection. Called from lifespan on shutdown."""
    global _conn
    if _conn:
        _conn.close()
        _conn = None
        logger.info("[gap_store] closed")


def _migrate(conn: sqlite3.Connection) -> None:
    """Incremental schema migrations for existing databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_gaps)")}
    if "iterations" not in cols:
        conn.execute(
            "ALTER TABLE knowledge_gaps ADD COLUMN iterations INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
        logger.info("[gap_store] migrated: added 'iterations' column")


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError(
            "Gap store is not initialised. "
            "Call init_gap_store() during application startup."
        )
    return _conn


# ── Public API ────────────────────────────────────────────────────────────────

def record_gap(
    query: str,
    access_level: int,
    quality_score: float,
    iterations: int = 0,
) -> None:
    """Persist an unanswered query as a knowledge gap (FR-31, FR-32a/b).

    Silently skips if the store was not initialised (e.g. unit tests)
    so the query pipeline is never disrupted by storage unavailability.
    """
    if _conn is None:
        logger.warning("[gap_store] not initialised — gap not persisted for query=%r", query[:50])
        return
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        _get_conn().execute(
            "INSERT INTO knowledge_gaps "
            "(query, access_level, quality_score, iterations, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (query, access_level, round(quality_score, 2), iterations, ts),
        )
        _get_conn().commit()


def list_gaps(limit: int = 100) -> list[dict]:
    """Return the most recent *limit* gaps, newest first.

    Reads do not acquire the write lock — WAL allows concurrent reads
    alongside a writer without blocking.
    """
    rows = _get_conn().execute(
        "SELECT id, query, access_level, quality_score, iterations, timestamp "
        "FROM knowledge_gaps ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "query": r[1],
            "access_level": r[2],
            "quality_score": r[3],
            "iterations": r[4],
            "timestamp": r[5],
        }
        for r in rows
    ]


def count_gaps() -> int:
    """Return total number of recorded gaps. Reads do not acquire the write lock."""
    return _get_conn().execute("SELECT COUNT(*) FROM knowledge_gaps").fetchone()[0]
