"""
Graph CRUD repository.

GraphRepository is responsible for persisting and updating graph structure
(nodes and relationships). It knows about Neo4j MERGE semantics but has
no knowledge of domain entities (Document, Section, Concept) — those are
expressed by callers via label + properties dicts.

Two operation modes:
  - Single:  merge_node() / merge_relationship()  — simple upserts
  - Batch:   merge_nodes_batch() / merge_relationships_batch()  — UNWIND-based,
             replaces N+1 loop patterns in ingestion pipeline.

Usage:
    with Neo4jDriver(uri, user, password) as driver:
        repo = GraphRepository(driver)
        repo.merge_nodes_batch("Document", [{"id": "d1", "title": "..."}])
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from backend.db.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)

# ── Domain allowlists ─────────────────────────────────────────────────────────
# Labels and relationship types are interpolated directly into Cypher text
# (Neo4j does not support them as parameters), so we restrict them to a fixed
# set of known values.  Any caller that passes an unrecognised value gets a
# ValueError before a query reaches the driver.
#
# Update these constants here when the ontology grows — never pass raw
# user-controlled strings.

NodeLabel = Literal["Document", "Section", "Concept"]
RelType   = Literal["REFERENCES", "HAS_SECTION"]

_ALLOWED_LABELS:    frozenset[str] = frozenset({"Document", "Section", "Concept"})
_ALLOWED_REL_TYPES: frozenset[str] = frozenset({"REFERENCES", "HAS_SECTION"})


def _validated_label(label: str) -> str:
    """Return *label* if it is in the allowlist, otherwise raise ValueError."""
    if label not in _ALLOWED_LABELS:
        raise ValueError(
            f"label={label!r} is not in the node-label allowlist. "
            f"Allowed: {sorted(_ALLOWED_LABELS)}"
        )
    return label


def _validated_rel_type(rel_type: str) -> str:
    """Return *rel_type* if it is in the allowlist, otherwise raise ValueError."""
    if rel_type not in _ALLOWED_REL_TYPES:
        raise ValueError(
            f"rel_type={rel_type!r} is not in the relationship-type allowlist. "
            f"Allowed: {sorted(_ALLOWED_REL_TYPES)}"
        )
    return rel_type


# ── Cypher templates ──────────────────────────────────────────────────────────

_MERGE_NODE = (
    "MERGE (n:{label} {{id: $id}}) "
    "SET n += $props "
    "RETURN n.id AS node_id"
)

_MERGE_NODES_BATCH = (
    "UNWIND $rows AS row "
    "MERGE (n:{label} {{id: row.id}}) "
    "SET n += row "
    "RETURN count(n) AS merged"
)

_MERGE_RELATIONSHIP = (
    "MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
    "MERGE (a)-[r:{rel_type}]->(b) "
    "SET r += $props "
    "RETURN type(r) AS rel"
)

_MERGE_RELATIONSHIPS_BATCH = (
    "UNWIND $rows AS row "
    "MATCH (a {{id: row.from_id}}), (b {{id: row.to_id}}) "
    "MERGE (a)-[r:{rel_type}]->(b) "
    "RETURN count(r) AS merged"
)


class GraphRepository:
    """Persist and update graph nodes and relationships.

    Responsibilities:
      - MERGE nodes by id (idempotent upserts)
      - MERGE relationships by endpoint pair + type (idempotent)
      - Batch variants using UNWIND to avoid N+1 round-trips

    Does NOT run searches or traversals — see GraphQueryService for that.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    # ── Single operations ─────────────────────────────────────────────────────

    def merge_node(self, label: NodeLabel, properties: dict[str, Any]) -> str:
        """MERGE a node with *label* and *properties*.

        *properties* must contain an ``id`` key.
        Returns the id of the created/updated node.
        """
        if "id" not in properties:
            raise ValueError("properties must contain 'id'")
        query = _MERGE_NODE.format(label=_validated_label(label))
        result = self._driver.execute(
            query,
            {"id": properties["id"], "props": properties},
        )
        node_id: str = result[0]["node_id"] if result else properties["id"]
        logger.debug("[repo] merge_node %s(%s)", label, node_id)
        return node_id

    def merge_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: RelType,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """MERGE a directed relationship *from_id* -[rel_type]-> *to_id*."""
        query = _MERGE_RELATIONSHIP.format(rel_type=_validated_rel_type(rel_type))
        self._driver.execute(
            query,
            {"from_id": from_id, "to_id": to_id, "props": properties or {}},
        )
        logger.debug("[repo] merge_rel %s -[%s]-> %s", from_id, rel_type, to_id)

    # ── Batch operations (O(1) round-trips, replaces N+1 loops) ──────────────

    def merge_nodes_batch(self, label: NodeLabel, rows: list[dict[str, Any]]) -> int:
        """MERGE a batch of nodes with a single UNWIND query.

        Each element of *rows* must have an ``id`` key.
        Returns the count of merged nodes.

        Complexity: O(1) network round-trips regardless of len(rows).
        """
        if not rows:
            return 0
        if any("id" not in row for row in rows):
            raise ValueError("Every row must contain 'id'")
        query = _MERGE_NODES_BATCH.format(label=_validated_label(label))
        result = self._driver.execute(query, {"rows": rows})
        merged: int = result[0]["merged"] if result else 0
        logger.debug("[repo] merge_nodes_batch %s × %d → %d merged", label, len(rows), merged)
        return merged

    def merge_relationships_batch(
        self,
        rel_type: RelType,
        rows: list[dict[str, str]],
    ) -> int:
        """MERGE a batch of relationships with a single UNWIND query.

        Each element of *rows* must have ``from_id`` and ``to_id`` keys.
        Returns the count of merged relationships.

        Complexity: O(1) network round-trips regardless of len(rows).
        """
        if not rows:
            return 0
        query = _MERGE_RELATIONSHIPS_BATCH.format(rel_type=_validated_rel_type(rel_type))
        result = self._driver.execute(query, {"rows": rows})
        merged: int = result[0]["merged"] if result else 0
        logger.debug(
            "[repo] merge_rels_batch [%s] × %d → %d merged", rel_type, len(rows), merged
        )
        return merged
