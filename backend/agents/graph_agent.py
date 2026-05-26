"""
GraphRAG StateGraph — topology, compilation cache, and public entry point.

Topology (ADR-004, FR-45):

  START → prepare_query → query_rewriter
        → [Send] vector_retriever ──┐  (uses query_rewritten for embedding)
        → [Send] graph_retriever  ──┤  (uses entities from prepare_query, parallel, FR-45)
                                    ↓
                              merge_results → role_context → generator → critic → confidence_score
                                    → ┌ retry (quality < threshold, iter < max) → [Send] re-dispatch
                                      ├ knowledge_gap (quality < gap_threshold)  → END
                                      └ output_guard  (quality ≥ threshold)      → END

Security layers (see agents/nodes.py for the full diagram):
  • API layer  — QueryRequest.strip_and_guard_query (api/schemas.py)
                 blocks injection, masks input PII; runs before run_agent().
  • Agent output — output_guard node masks PII in the LLM answer (FR-27).
  prepare_query is preprocessing only (strip + entity extraction), not security.

This module is intentionally thin: it only wires nodes to edges.
All node logic lives in agents/nodes.py.
All state types live in agents/state.py.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from backend.agents.nodes import AgentNodes
from backend.agents.state import AgentState, make_initial_state
from backend.core.config import Settings
from backend.observability.tracing import get_langfuse_callbacks
from backend.query.pipeline import QueryResult

logger = logging.getLogger(__name__)


# ── Graph construction ────────────────────────────────────────────────────────

def build_graph(settings: Settings):
    """Wire AgentNodes into a compiled LangGraph StateGraph.

    Called once; the result is cached in _get_compiled_graph().
    """
    nodes = AgentNodes(settings)

    workflow = StateGraph(AgentState)

    # Register all nodes
    workflow.add_node("prepare_query",    nodes.prepare_query)   # strip + entity extraction
    workflow.add_node("query_rewriter",   nodes.query_rewriter)  # LLM query → document-style terms
    workflow.add_node("vector_retriever", nodes.vector_retriever)
    workflow.add_node("graph_retriever",  nodes.graph_retriever)
    workflow.add_node("merge_results",    nodes.merge_results)
    workflow.add_node("role_context",     nodes.role_context)    # role-aware focus hint
    workflow.add_node("generator",        nodes.generator)
    workflow.add_node("critic",           nodes.critic)
    workflow.add_node("confidence_score", nodes.confidence_score)
    workflow.add_node("output_guard",     nodes.output_guard)    # security: PII mask on answer
    workflow.add_node("knowledge_gap",    nodes.knowledge_gap)

    # Wire edges
    workflow.add_edge(START, "prepare_query")
    workflow.add_edge("prepare_query", "query_rewriter")
    workflow.add_conditional_edges("query_rewriter", nodes.dispatch_retrievers)  # fan-out
    workflow.add_edge("vector_retriever", "merge_results")                       # fan-in
    workflow.add_edge("graph_retriever",  "merge_results")                       # fan-in
    workflow.add_edge("merge_results",    "role_context")
    workflow.add_edge("role_context",     "generator")
    workflow.add_edge("generator",        "critic")
    workflow.add_edge("critic",           "confidence_score")
    workflow.add_conditional_edges(
        "confidence_score",
        nodes.should_retry,
        {"knowledge_gap": "knowledge_gap", "output_guard": "output_guard"},
    )
    workflow.add_edge("output_guard",   END)
    workflow.add_edge("knowledge_gap",  END)

    graph = workflow.compile()
    try:
        logger.info("Agent graph compiled:\n%s", graph.get_graph().draw_ascii())
    except Exception:
        logger.info("Agent graph compiled (install grandalf for ASCII art)")
    return graph


# ── Compiled graph cache ──────────────────────────────────────────────────────
#
# Cache key: the Settings *object* itself (by identity, not equality).
#
# Within a running process, get_settings() is lru_cached — it always returns
# the same object, so the graph is built exactly once per application lifecycle.
#
# In tests, get_settings.cache_clear() creates a new Settings object with a
# new id().  The identity check (`cached_settings is not settings`) detects
# this and rebuilds the graph with the new settings, so test isolation is
# maintained without requiring an explicit cache-clear call.
#
# Stored as a (Settings, compiled_graph) pair — no dict, no weakref needed.

_COMPILED_GRAPH_CACHE: tuple[Settings, object] | None = None


def _get_compiled_graph(settings: Settings):
    """Return the compiled graph, building it on first call or when settings change.

    Uses object identity (``is``) so that a new Settings object produced by
    get_settings.cache_clear() triggers a rebuild while the same lru_cached
    object reuses the existing compiled graph.
    """
    global _COMPILED_GRAPH_CACHE
    if _COMPILED_GRAPH_CACHE is None or _COMPILED_GRAPH_CACHE[0] is not settings:
        _COMPILED_GRAPH_CACHE = (settings, build_graph(settings))
    return _COMPILED_GRAPH_CACHE[1]


# ── Public entry point ────────────────────────────────────────────────────────

async def run_agent(query: str, access_level: int, settings: Settings) -> QueryResult:
    """Run the GraphRAG agent and return a QueryResult.

    Async so that the LLM I/O (generator node) does not block the event loop.
    LangGraph routes sync nodes through the default executor automatically;
    the async generator node is awaited natively via ainvoke().

    Called by POST /query. The compiled graph is reused across requests.
    """
    graph = _get_compiled_graph(settings)
    callbacks = get_langfuse_callbacks(settings)

    initial = make_initial_state(query, access_level)
    invoke_config = {"callbacks": callbacks} if callbacks else {}
    final = await graph.ainvoke(initial, config=invoke_config)

    trace_id = (
        f"{final['trace_id']}"
        f"-v{len(final['vector_chunks'])}"
        f"g{len(final['graph_results'])}"
        f"-i{final['iterations']}"
    )
    return QueryResult(
        answer=final["answer"],
        sources=final["sources"],
        quality_score=final["quality_score"],
        confidence_score=final["confidence_score"],
        gap_detected=final["gap_detected"],
        trace_id=trace_id,
    )
