"""
Agent state contract.

AgentState is the single shared TypedDict that flows through every node of the
LangGraph StateGraph. Defining it here — separate from node logic and graph
topology — makes it importable by tests without pulling in LangGraph or Settings.

make_initial_state() is the canonical factory for creating a blank slate;
use it in run_agent() and in unit tests to avoid scattered dict literals.
"""

from __future__ import annotations

from typing import TypedDict

from backend.query.pipeline import MergedSource
from backend.retrieval.graph_retriever import GraphResult
from backend.retrieval.vector_retriever import RetrievedChunk


class AgentState(TypedDict):
    query: str
    access_level: int
    entities: list[str]               # extracted once in prepare_query (FR-41a), stable across retries
    vector_chunks: list[RetrievedChunk]
    graph_results: list[GraphResult]
    sources: list[MergedSource]
    answer: str
    quality_score: float
    confidence_score: float
    iterations: int
    gap_detected: bool
    trace_id: str


def make_initial_state(query: str, access_level: int) -> AgentState:
    """Return a blank AgentState for the start of a new query."""
    return AgentState(
        query=query,
        access_level=access_level,
        entities=[],
        vector_chunks=[],
        graph_results=[],
        sources=[],
        answer="",
        quality_score=0.0,
        confidence_score=0.0,
        iterations=0,
        gap_detected=False,
        trace_id="",
    )
