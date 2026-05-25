"""
FastAPI route handlers.

This module is intentionally thin — only HTTP transport logic lives here:
  - declare @router endpoints
  - authenticate via X-User-Role header
  - delegate to domain services
  - map domain results to response schemas

All Pydantic schemas  → api/schemas.py
Security utilities    → security/injection.py, security/pii.py, security/rbac.py
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status

logger = logging.getLogger(__name__)

from backend.agents.graph_agent import run_agent
from backend.ingestion.corpus_loader import get_doc_title
from backend.api.schemas import (
    AuditLogResponse,
    ComponentHealth,
    GraphResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    KnowledgeGapsResponse,
    OntologyResponse,
    QueryRequest,
    QueryResponse,
    SourceReference,
)
from backend.core.config import Settings, get_settings
from backend.db.audit_store import count_audit, list_audit, record_audit
from backend.db.gap_store import count_gaps, list_gaps
from backend.ingestion.service import ingest_markdown_corpus
from backend.ontology.loader import load_ontology
from backend.security.rbac import ROLES, require_admin, role_to_access_level

router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        mode=settings.app_mode,
        components=ComponentHealth(
            api="ok",
            llm_backend=settings.llm_backend,
            embeddings_backend=settings.embeddings_backend,
            storage_backend=settings.storage_backend,
        ),
    )


# ── Query ─────────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    settings: Settings = Depends(get_settings),
) -> QueryResponse:
    access_level = role_to_access_level(x_user_role)
    result = await run_agent(payload.query, access_level, settings)

    # ФЗ-152 audit: record every query regardless of outcome.
    # Wrapped in try/except so a storage failure never disrupts the response.
    try:
        record_audit(
            user_role=x_user_role or "unknown",
            access_level=access_level,
            query=payload.query,
            result_count=len(result.sources),
            quality_score=result.quality_score,
            gap_detected=result.gap_detected,
        )
    except Exception:  # noqa: BLE001
        logger.warning("[audit] failed to persist audit record", exc_info=True)

    return QueryResponse(
        answer=result.answer,
        sources=[
            SourceReference(
                doc_id=source.doc_id,
                doc_title=get_doc_title(source.doc_id),
                section=source.section_title,
                access_level=source.access_level,
                last_updated=source.last_updated,
                retrieval_score=source.score,
            )
            for source in result.sources[:5]   # top-5 most relevant only
        ],
        quality_score=result.quality_score,
        confidence_score=result.confidence_score,
        gap_detected=result.gap_detected,
        trace_id=result.trace_id,
    )


# ── Ingestion ─────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    payload: IngestRequest | None = None,
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    settings: Settings = Depends(get_settings),
) -> IngestResponse:
    access_level = role_to_access_level(x_user_role)
    if access_level < ROLES["manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or admin role is required to ingest documents.",
        )
    if payload and payload.content:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Single-document ingestion is not implemented yet; use corpus ingestion.",
        )
    # Run sync corpus ingestion in a thread pool so the event loop stays free
    # for concurrent /query and /health requests during ingestion.
    result = await asyncio.to_thread(ingest_markdown_corpus, settings)
    return IngestResponse(
        status="success",
        message="Markdown corpus ingestion completed.",
        documents_processed=result.documents_processed,
        chunks_created=result.chunks_created,
        graph_nodes_projected=result.graph_nodes_projected,
        graph_edges_projected=result.graph_edges_projected,
        storage_backend=result.storage_backend,
    )


# ── Graph explorer ────────────────────────────────────────────────────────────

@router.get("/graph", response_model=GraphResponse)
async def graph(
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    settings: Settings = Depends(get_settings),
) -> GraphResponse:
    """FR-07, AC-04: Return Knowledge Graph nodes/edges (Admin only).

    In gpu-demo (STORAGE_BACKEND=qdrant-neo4j) queries live Neo4j.
    In local-lite (mock) returns an empty graph — no Neo4j available.
    """
    require_admin(x_user_role)
    if settings.storage_backend != "qdrant-neo4j":
        return GraphResponse(nodes=[], edges=[])

    from backend.core.connections import get_pool
    from backend.db.graph_queries import GraphQueryService
    from backend.db.neo4j_driver import Neo4jDriver

    access_level = role_to_access_level(x_user_role)
    driver = Neo4jDriver.from_pool(get_pool().neo4j)   # non-owning pool wrapper
    data = GraphQueryService(driver).get_graph_for_explorer(access_level=access_level)
    return GraphResponse(nodes=data["nodes"], edges=data["edges"])


# ── Knowledge gaps ────────────────────────────────────────────────────────────

@router.get("/knowledge-gaps", response_model=KnowledgeGapsResponse)
async def knowledge_gaps(
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> KnowledgeGapsResponse:
    require_admin(x_user_role)  # FR-33: Admin only per spec
    return KnowledgeGapsResponse(items=list_gaps(limit=100), total=count_gaps())


# ── Audit log ────────────────────────────────────────────────────────────────

@router.get("/audit-log", response_model=AuditLogResponse)
async def audit_log(
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> AuditLogResponse:
    """ФЗ-152 audit log — Admin only (FR-security).

    Returns the most recent 200 audit records. Each record contains the
    SHA-256 hash of the query (plain text is never stored), the user role,
    access level, retrieval result count, quality score, and timestamp.
    """
    require_admin(x_user_role)
    return AuditLogResponse(items=list_audit(limit=200), total=count_audit())


# ── Ontology ──────────────────────────────────────────────────────────────────

@router.get("/ontology", response_model=OntologyResponse)
async def get_ontology(
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> OntologyResponse:
    """FR-39, FR-40a/b, FR-42: Return loaded domain ontology (all authenticated roles)."""
    role_to_access_level(x_user_role)  # any valid role can view
    ontology = load_ontology()
    entities = ontology.to_dict()
    return OntologyResponse(
        version="1.0",
        total_entities=len(entities),
        entities=entities,
    )


@router.post("/ontology", response_model=OntologyResponse)
async def update_ontology(
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> OntologyResponse:
    """FR-42: Reload ontology from disk (Admin only).

    Triggers lru_cache invalidation and re-read of docs/ontology.json
    without restarting the server.
    """
    require_admin(x_user_role)
    load_ontology.cache_clear()
    ontology = load_ontology()
    entities = ontology.to_dict()
    return OntologyResponse(
        version="1.0",
        total_entities=len(entities),
        entities=entities,
    )
