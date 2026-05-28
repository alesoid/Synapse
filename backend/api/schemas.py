"""
API request / response schemas.

All Pydantic models used by the FastAPI routes live here so that
routes.py contains only HTTP transport logic (decorators + handlers).

Security boundary
-----------------
QueryRequest.strip_and_guard_query is the HTTP transport security gate.
It runs before run_agent() is ever called and enforces:
  • FR-26 : prompt injection detection — blocked queries return HTTP 422
  • FR-25a/b/c : PII masking in the query — masked before reaching the LLM

The LangGraph pipeline itself does NOT re-run these checks; its first node
(prepare_query) is preprocessing only (strip + entity extraction).
Output PII masking (FR-27) is handled separately by the output_guard node
inside the agent (agents/nodes.py).

If run_agent() is invoked outside of HTTP context (e.g. in scripts or tests),
callers are responsible for sanitising input themselves.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.security.injection import is_injection
from backend.security.pii import mask_pii


# ── Health ────────────────────────────────────────────────────────────────────

class ComponentHealth(BaseModel):
    api: Literal["ok"]
    llm_backend: str
    embeddings_backend: str
    storage_backend: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    mode: str
    components: ComponentHealth


# ── Query ─────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)  # spec: max 1000 chars
    stream: bool = False

    @field_validator("query", mode="before")
    @classmethod
    def strip_and_guard_query(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError("Query must contain at least 3 non-whitespace characters.")
        if is_injection(stripped):                   # FR-26: block, return HTTP 422
            raise ValueError("Query blocked by security policy.")
        return mask_pii(stripped)                    # FR-25a/b/c: mask, pass through


class SourceReference(BaseModel):
    doc_id: str
    doc_title: str | None = None   # human-readable document name from corpus manifest
    section: str
    access_level: int
    last_updated: str | None = None
    retrieval_score: float | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    quality_score: float
    confidence_score: float
    gap_detected: bool
    trace_id: str | None = None
    critic_feedback: str | None = None   # one-sentence quality explanation from critic agent


# ── Ingestion ─────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    doc_id: str | None = None
    content: str | None = None
    access_level: int | None = Field(default=None, ge=1, le=5)
    doc_type: str = "document"
    last_updated: str | None = None


class IngestResponse(BaseModel):
    status: Literal["success", "accepted"]
    message: str
    documents_processed: int = 0
    chunks_created: int = 0
    graph_nodes_projected: int = 0
    graph_edges_projected: int = 0
    storage_backend: str


# ── Graph explorer ────────────────────────────────────────────────────────────

class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


# ── Knowledge gaps ────────────────────────────────────────────────────────────

class KnowledgeGapsResponse(BaseModel):
    items: list[dict]
    total: int


# ── Audit log ─────────────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    items: list[dict]
    total: int


# ── Ontology ──────────────────────────────────────────────────────────────────

class OntologyResponse(BaseModel):
    version: str
    total_entities: int
    entities: list[dict]
