"""
Domain graph query service.

GraphQueryService answers domain questions against the knowledge graph:
  - find related sections for a list of entity names (retrieval)
  - traverse neighbours of a node (exploration)
  - return the full graph for the Admin explorer UI
  - report graph statistics

All queries are defined as module-level constants so they can be read,
reviewed, and tested independently from the service class.

Usage:
    with Neo4jDriver(uri, user, password) as driver:
        svc = GraphQueryService(driver)
        rows = svc.graph_search(["Docker", "CI/CD"], access_level=3)
"""

from __future__ import annotations

import logging

from backend.db.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)

# Re-export the shared allowlist so callers and tests can import from one place
from backend.db.graph_repository import NodeLabel, _ALLOWED_LABELS, _validated_label  # noqa: E402

# ── Cypher query constants ────────────────────────────────────────────────────

# FR-RBAC: every query filters by access_level so lower-privileged users
# cannot see nodes above their clearance level.
#
# NULL access_level policy
# ------------------------
# Every node MUST have access_level set at ingestion time (see storage.py).
# To prevent a mis-ingested NULL from leaking data to all users, every RBAC
# filter uses COALESCE(n.access_level, 1) — NULL is treated as level 1
# (public / junior) rather than "skip the check".
# This is the most conservative safe default: a forgotten label makes the node
# visible only at the lowest clearance, not to everybody.
# Existing NULL nodes are back-filled to 1 by ensure_access_levels() at startup.

# NOTE: $depth is a placeholder, not a Cypher parameter.
# Neo4j does not accept variable-length range bounds as parameters — only
# literal integers are valid (e.g. [*1..2]).  graph_search() replaces
# "$depth" with a validated literal before passing the query to the driver.
# See also get_neighbors() which uses the same approach.
_GRAPH_SEARCH = """
    UNWIND $names AS name
    MATCH (start)
    WHERE toLower(start.name) CONTAINS toLower(name)
      AND COALESCE(start.access_level, 1) <= $access_level
    MATCH (start)-[*1..$depth]-(related)
    WHERE COALESCE(related.access_level, 1) <= $access_level
    WITH DISTINCT related
    WHERE related.doc_id IS NOT NULL
    RETURN
        related.doc_id        AS doc_id,
        related.id            AS section_id,
        related.title         AS section_title,
        related.content_summary AS summary,
        related.access_level  AS access_level
    LIMIT 20
"""

# Allowed depth values — prevents arbitrary string injection into the Cypher
# literal.  Range is 1-3: depth=1 is a direct match; depth=3 is the practical
# limit for a knowledge-graph hop before result quality degrades.
_ALLOWED_DEPTHS = frozenset({1, 2, 3})

_GET_NEIGHBORS = """
    MATCH (start {id: $node_id})-[*1..$depth]-(neighbor)
    WHERE COALESCE(neighbor.access_level, 1) <= $access_level
    RETURN DISTINCT
        neighbor.id           AS id,
        neighbor.name         AS name,
        labels(neighbor)[0]   AS label,
        neighbor.access_level AS access_level
    LIMIT 50
"""

_SEARCH_BY_PROPERTY = """
    MATCH (n:{label})
    WHERE n[$key] = $value
      AND COALESCE(n.access_level, 1) <= $access_level
    RETURN n {.*} AS node
    LIMIT 20
"""

_EXPLORER_NODES = """
    MATCH (n)
    WHERE COALESCE(n.access_level, 1) <= $access_level
    RETURN
        n.id                              AS id,
        COALESCE(n.name, n.title, n.id)   AS label,
        labels(n)[0]                      AS type,
        n.access_level                    AS access_level
    LIMIT 200
"""

_EXPLORER_EDGES = """
    MATCH (a)-[r]->(b)
    WHERE COALESCE(a.access_level, 1) <= $access_level
      AND COALESCE(b.access_level, 1) <= $access_level
    RETURN
        a.id       AS source,
        b.id       AS target,
        type(r)    AS type
    LIMIT 500
"""

_GRAPH_STATS = """
    MATCH (n) WITH count(n) AS nodes
    MATCH ()-[r]->()
    RETURN nodes, count(r) AS edges
"""

# ── Index DDL constants ───────────────────────────────────────────────────────
# Idempotent IF NOT EXISTS — safe to run on every startup.
# access_level is the primary RBAC filter; indexing it turns every retrieval
# query from a full label scan into an index seek.

_INDEX_STATEMENTS = [
    "CREATE INDEX document_access_level IF NOT EXISTS FOR (n:Document) ON (n.access_level)",
    "CREATE INDEX section_access_level  IF NOT EXISTS FOR (n:Section)  ON (n.access_level)",
    "CREATE INDEX concept_access_level  IF NOT EXISTS FOR (n:Concept)  ON (n.access_level)",
    "CREATE INDEX document_id           IF NOT EXISTS FOR (n:Document) ON (n.id)",
    "CREATE INDEX section_id            IF NOT EXISTS FOR (n:Section)  ON (n.id)",
    "CREATE INDEX concept_id            IF NOT EXISTS FOR (n:Concept)  ON (n.id)",
]

# ── NULL access_level backfill ────────────────────────────────────────────────
# Any node that reached the graph without access_level (manual writes, legacy
# migrations, Cypher bugs) is set to 1 (public/junior).
# This is idempotent: nodes that already have access_level are untouched
# (SET n.access_level = 1 WHERE n.access_level IS NULL).
_BACKFILL_NULL_ACCESS_LEVEL = (
    "MATCH (n) WHERE n.access_level IS NULL "
    "SET n.access_level = 1 "
    "RETURN count(n) AS fixed"
)


def ensure_indexes(driver: Neo4jDriver) -> None:
    """Create Neo4j indexes and back-fill NULL access_level values.

    Should be called once during application startup (lifespan) after the
    connection pool is initialised.  All operations are idempotent, so
    re-running is safe on restarts or rolling deploys.

    Operations performed:
      • CREATE INDEX … IF NOT EXISTS for access_level and id on all three labels
        — turns every RBAC WHERE clause from a full scan into an index seek
      • SET n.access_level = 1 WHERE n.access_level IS NULL
        — ensures no node can bypass RBAC via a missing access_level property
    """
    for ddl in _INDEX_STATEMENTS:
        try:
            driver.execute(ddl)
            logger.debug("[graph_queries] index DDL executed: %s", ddl.split("FOR")[0].strip())
        except Exception as exc:   # pragma: no cover — Neo4j-version-specific errors
            logger.warning("[graph_queries] index DDL warning (ignored): %s", exc)
    logger.info("[graph_queries] Neo4j indexes verified (%d statements)", len(_INDEX_STATEMENTS))

    # Back-fill nodes that are missing access_level → treat as public (level 1)
    try:
        result = driver.execute(_BACKFILL_NULL_ACCESS_LEVEL)
        fixed = result[0]["fixed"] if result else 0
        if fixed:
            logger.warning(
                "[graph_queries] back-filled access_level=1 on %d node(s) that had NULL — "
                "check ingestion pipeline for missing access_level",
                fixed,
            )
        else:
            logger.info("[graph_queries] access_level NULL check: all nodes OK")
    except Exception as exc:   # pragma: no cover
        logger.warning("[graph_queries] access_level back-fill warning (ignored): %s", exc)


# ── Service class ─────────────────────────────────────────────────────────────

class GraphQueryService:
    """Read-only graph traversal and search queries.

    Responsibilities:
      - graph_search()           retrieval for GraphRetrieverAgent (FR-45)
      - get_neighbors()          neighbourhood exploration
      - search_by_property()     property-based lookup with RBAC
      - get_graph_for_explorer() Admin graph explorer data (FR-07)
      - get_stats()              node/edge counts for health checks (AC-04)

    Does NOT mutate the graph — see GraphRepository for write operations.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def graph_search(
        self,
        entity_names: list[str],
        access_level: int,
        depth: int = 2,
    ) -> list[dict]:
        """Find knowledge graph sections related to *entity_names*.

        Traverses the graph up to *depth* hops from each matching start node.
        RBAC: only nodes with access_level <= user's level are returned.

        depth must be 1, 2, or 3.  Neo4j does not accept variable-length range
        bounds as Cypher parameters (only literals are valid), so depth is
        injected as a string literal after whitelist validation.
        """
        if depth not in _ALLOWED_DEPTHS:
            raise ValueError(
                f"depth={depth!r} is not allowed. "
                f"Valid values: {sorted(_ALLOWED_DEPTHS)}"
            )
        # Replace placeholder with a validated integer literal — never user input
        query = _GRAPH_SEARCH.replace("$depth", str(depth))
        logger.debug(
            "[graph_queries] graph_search entities=%r access_level=%d depth=%d",
            entity_names[:3], access_level, depth,
        )
        return self._driver.execute(
            query,
            {"names": entity_names, "access_level": access_level},
        )

    def get_neighbors(
        self,
        node_id: str,
        access_level: int,
        depth: int = 2,
    ) -> list[dict]:
        """Return up to 50 neighbours of *node_id* within RBAC access."""
        if depth not in _ALLOWED_DEPTHS:
            raise ValueError(
                f"depth={depth!r} is not allowed. "
                f"Valid values: {sorted(_ALLOWED_DEPTHS)}"
            )
        # depth is injected as a literal (Cypher doesn't accept variable-length
        # range bounds as parameters — only literals are valid)
        query = _GET_NEIGHBORS.replace("$depth", str(depth))
        return self._driver.execute(
            query,
            {"node_id": node_id, "access_level": access_level},
        )

    def search_by_property(
        self,
        label: NodeLabel,
        key: str,
        value: object,
        access_level: int = 5,
    ) -> list[dict]:
        """Find nodes of *label* where *key* == *value*, filtered by RBAC."""
        query = _SEARCH_BY_PROPERTY.format(label=_validated_label(label))
        return self._driver.execute(
            query,
            {"key": key, "value": value, "access_level": access_level},
        )

    def get_graph_for_explorer(self, access_level: int = 5) -> dict:
        """Return ``{"nodes": [...], "edges": [...]}`` for the Admin graph explorer.

        Suitable for react-force-graph or similar visualisation libraries.
        Capped at 200 nodes / 500 edges to keep the payload manageable.
        """
        params = {"access_level": access_level}
        nodes = self._driver.execute(_EXPLORER_NODES, params)
        edges = self._driver.execute(_EXPLORER_EDGES, params)
        logger.debug(
            "[graph_queries] explorer returned %d nodes, %d edges",
            len(nodes), len(edges),
        )
        return {"nodes": nodes, "edges": edges}

    def get_stats(self) -> dict:
        """Return total node and edge counts (used by AC-04 health checks)."""
        result = self._driver.execute(_GRAPH_STATS)
        return result[0] if result else {"nodes": 0, "edges": 0}
