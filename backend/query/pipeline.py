"""
Shared query utilities used by graph_agent.py.

  MergedSource, QueryResult  — domain dataclasses
  extract_entities()         — tokenise + ontology-normalise query tokens (FR-41a)
  _merge()                   — hybrid vector+graph result fusion (FR-45)
  _compute_confidence()      — staleness-based confidence score (FR-36a)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from backend.ontology.loader import resolve_entity
from backend.retrieval.graph_retriever import GraphResult
from backend.retrieval.vector_retriever import RetrievedChunk

_STOPWORDS = frozenset(
    "и в на с по к за от до из при как для что это не но да же бы то "
    "под над без после ли уж бы ведь".split()
)
_TOKEN_RE = re.compile(r"[а-яёa-z]{3,}", re.IGNORECASE)


@dataclass(frozen=True)
class MergedSource:
    doc_id: str
    section_title: str
    text: str
    access_level: int
    last_updated: str | None
    score: float


@dataclass(frozen=True)
class QueryResult:
    answer: str
    sources: list[MergedSource]
    quality_score: float
    confidence_score: float
    gap_detected: bool
    trace_id: str


def extract_entities(query: str) -> list[str]:
    """Extract and ontology-normalise entities from query.

    FR-41a: each token is resolved against the domain ontology via fuzzy match.
    Canonical names replace raw tokens so the graph retriever uses consistent
    node identifiers (FR-41b: new nodes only for unknown terms).
    """
    tokens = _TOKEN_RE.findall(query.lower())
    raw = [t for t in tokens if t not in _STOPWORDS]
    # Resolve each token to its canonical ontology name (deduplicates synonyms)
    seen: set[str] = set()
    resolved: list[str] = []
    for token in raw:
        canonical, _is_new = resolve_entity(token)
        if canonical not in seen:
            seen.add(canonical)
            resolved.append(canonical)
    return resolved


def _merge(
    vector_chunks: list[RetrievedChunk],
    graph_results: list[GraphResult],
    alpha: float = 0.7,
) -> list[MergedSource]:
    """Merge vector and graph results with weighted score.

    alpha=1.0 → pure vector-only (HYBRID_ALPHA=1.0 in env).
    alpha=0.7 → default hybrid (70% vector + 30% graph).
    """
    graph_alpha = 1.0 - alpha
    graph_keys = {(r.doc_id, r.section_title) for r in graph_results}
    merged: dict[str, MergedSource] = {}

    for chunk in vector_chunks:
        in_graph = (chunk.doc_id, chunk.section_title) in graph_keys
        score = min(chunk.score * alpha + (graph_alpha if in_graph else 0.0), 1.0)
        key = f"{chunk.doc_id}::{chunk.section_title}"
        if key not in merged or merged[key].score < score:
            merged[key] = MergedSource(
                doc_id=chunk.doc_id,
                section_title=chunk.section_title,
                text=chunk.text,
                access_level=chunk.access_level,
                last_updated=chunk.last_updated,
                score=round(score, 4),
            )

    seen_keys = set(merged)
    for result in graph_results:
        key = f"{result.doc_id}::{result.section_title}"
        if key not in seen_keys:
            merged[key] = MergedSource(
                doc_id=result.doc_id,
                section_title=result.section_title,
                text=result.summary,
                access_level=result.access_level,
                last_updated=None,
                score=0.3,
            )

    return sorted(merged.values(), key=lambda s: s.score, reverse=True)


def _compute_confidence(sources: list[MergedSource]) -> float:
    if not sources:
        return 0.0

    today = date.today()
    scores: list[float] = []
    for source in sources:
        if not source.last_updated:
            scores.append(0.3)
            continue
        try:
            updated = datetime.strptime(source.last_updated, "%Y-%m-%d").date()
            days = (today - updated).days
            # FR-36a: linear formula 1 - (age_days / 365), clamped to [0, 1]
            scores.append(max(0.0, min(1.0, 1.0 - days / 365)))
        except ValueError:
            scores.append(0.0)

    return round(sum(scores) / len(scores), 2)
