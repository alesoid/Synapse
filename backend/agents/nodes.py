"""
LangGraph node implementations for the GraphRAG agent.

Each node is a method of AgentNodes so that:
  1. Settings is injected once via __init__ — no closure capture, explicit dependency.
  2. Every method can be unit-tested in isolation:
         nodes = AgentNodes(mock_settings)
         result = nodes.prepare_query({"query": "Docker CI/CD", "access_level": 2, ...})
  3. Routing functions (dispatch_retrievers, should_retry) live alongside the nodes
     they route — same class, same settings, same test surface.

Node topology is defined separately in graph_agent.py.

Security-layer architecture
---------------------------
There are two distinct security boundaries in the pipeline:

  1. API / transport layer  — api/schemas.py :: QueryRequest.strip_and_guard_query
       • blocks prompt injection (FR-26, HTTP 422)
       • masks PII in the query (FR-25a/b/c)
       This runs *before* run_agent() is called and is specific to HTTP transport.

  2. Agent output layer     — AgentNodes.output_guard
       • masks PII that the LLM may have introduced in its answer (FR-27)
       This runs at the end of the LangGraph pipeline regardless of transport.

  prepare_query (the first graph node) is NOT a security gate — it performs
  query preprocessing (strip + entity extraction) and has no security role.
  The name is intentionally distinct from "guard" to avoid confusion.
"""

from __future__ import annotations

import logging

from langgraph.constants import Send

from backend.agents.state import AgentState
from backend.core.config import Settings
from backend.db.gap_store import record_gap
from backend.llm.client import get_llm_client
from backend.query.critic import get_critic
from backend.query.pipeline import _compute_confidence, _merge, extract_entities
from backend.ingestion.corpus_loader import get_doc_title
from backend.query.rewriter import get_query_rewriter
from backend.retrieval.graph_retriever import get_graph_retriever
from backend.retrieval.vector_retriever import get_vector_retriever
from backend.observability.tracing import tracer
from backend.security.pii import mask_pii

logger = logging.getLogger(__name__)


class AgentNodes:
    """All node and routing functions for the GraphRAG StateGraph.

    Instantiate once per compiled graph; the same instance is reused for every
    request (graph is compiled once and cached at module level in graph_agent.py).
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings  # short alias — used in every method

    # ── Node: query preprocessing ─────────────────────────────────────────────

    def prepare_query(self, state: AgentState) -> dict:
        """Normalise the query and extract ontology-resolved entities (FR-41a).

        Security note: injection blocking and PII masking are enforced upstream
        by QueryRequest.strip_and_guard_query (api/schemas.py) before
        run_agent() is ever called.  This node is preprocessing only.

        Entities are extracted once here, before the parallel fan-out, so that
        graph_retriever can reuse them on every retry without re-running
        extract_entities() against the same unchanged query.
        """
        with tracer.start_as_current_span("prepare_query") as span:
            span.set_attribute("query.length", len(state["query"]))
            span.set_attribute("user.access_level", state["access_level"])
            # query is already stripped by the Pydantic validator at the API layer;
            # strip() here is a defensive no-op for direct (non-HTTP) callers.
            query = state["query"].strip()
            entities = extract_entities(query)
            span.set_attribute("entities.count", len(entities))
            logger.info(
                "[prepare_query] query=%r access_level=%d entities=%r",
                query, state["access_level"], entities[:5],
            )
            return {"query": query, "entities": entities}

    # ── Node: query rewriting ─────────────────────────────────────────────────

    def query_rewriter(self, state: AgentState) -> dict:
        """Rewrite the user query into document-search style for better recall.

        Converts question-phrased queries ("Как проходит онбординг?") into
        keyword/term-rich document-style phrases ("процедура адаптации этапы
        документы ответственные") before vector embedding. The original query
        is preserved in state["query"] for the generator and critic.

        Graph retrieval is unaffected — it uses entities from prepare_query,
        which are already ontology-resolved canonical terms.
        """
        with tracer.start_as_current_span("query_rewriter") as span:
            span.set_attribute("query.length", len(state["query"]))
            rewriter = get_query_rewriter(self._s)
            rewritten = rewriter.rewrite(state["query"])
            span.set_attribute("rewritten.length", len(rewritten))
            return {"query_rewritten": rewritten}

    # ── Node: parallel retrieval (FR-45) ──────────────────────────────────────

    def vector_retriever(self, state: AgentState) -> dict:
        """VectorRetrieverAgent — runs in parallel with graph_retriever (FR-45)."""
        with tracer.start_as_current_span("vector_retriever") as span:
            span.set_attribute("user.access_level", state["access_level"])
            span.set_attribute("iteration", state["iterations"])
            retriever = get_vector_retriever(self._s)
            # Use rewritten query for embedding if available — better recall via
            # document-style phrasing. Falls back to original query transparently.
            search_query = state.get("query_rewritten") or state["query"]
            span.set_attribute("query.length", len(search_query))
            chunks = retriever.search(search_query, state["access_level"])
            span.set_attribute("retrieval.results_count", len(chunks))
            logger.info(
                "[vector_retriever] found %d chunks (iter=%d)",
                len(chunks), state["iterations"],
            )
            return {"vector_chunks": chunks}

    def graph_retriever(self, state: AgentState) -> dict:
        """GraphRetrieverAgent — runs in parallel with vector_retriever (FR-45)."""
        with tracer.start_as_current_span("graph_retriever") as span:
            entities = state["entities"]  # pre-computed in prepare_query; stable across retries
            span.set_attribute("entities.count", len(entities))
            span.set_attribute("user.access_level", state["access_level"])
            retriever = get_graph_retriever(self._s)
            results = retriever.search(entities, state["access_level"]) if entities else []
            span.set_attribute("retrieval.results_count", len(results))
            logger.info(
                "[graph_retriever] entities=%r found %d",
                entities[:3], len(results),
            )
            return {"graph_results": results}

    # ── Node: merge ───────────────────────────────────────────────────────────

    def merge_results(self, state: AgentState) -> dict:
        """Hybrid merge: alpha × vector_score + (1-alpha) × graph_boost (FR-45)."""
        with tracer.start_as_current_span("merge_results") as span:
            span.set_attribute("vector.chunks_count", len(state["vector_chunks"]))
            span.set_attribute("graph.results_count", len(state["graph_results"]))
            span.set_attribute("merge.alpha", self._s.hybrid_alpha)
            sources = _merge(
                state["vector_chunks"],
                state["graph_results"],
                alpha=self._s.hybrid_alpha,
            )
            span.set_attribute("sources.count", len(sources))
            logger.info(
                "[merge_results] %d sources merged (alpha=%.2f)",
                len(sources), self._s.hybrid_alpha,
            )
            return {"sources": sources}

    # ── Node: role-aware context ──────────────────────────────────────────────

    # Deterministic focus hints per access level — no extra LLM call, O(1) latency.
    # Each hint steers the generator to surface the nuances most relevant to the role.
    _ROLE_HINTS: dict[int, str] = {
        1: (
            "Пользователь — Junior (L1). "
            "Давай пошаговые инструкции: что делать, в каком порядке, куда обращаться. "
            "Называй конкретные документы и ответственных лиц. "
            "Избегай сложных технических деталей и финансовых показателей."
        ),
        2: (
            "Пользователь — Middle (L2). "
            "Включай технические детали и рабочие инструменты. "
            "Упоминай связи между процессами и командами. "
            "Фокус: как работает процесс, какие стандарты применяются."
        ),
        3: (
            "Пользователь — Senior (L3). "
            "Раскрывай архитектурные решения, технические стандарты и ограничения. "
            "Описывай зависимости между системами и командами, объясняй причины решений. "
            "Фокус: технические нюансы, trade-offs, лучшие практики."
        ),
        4: (
            "Пользователь — Manager (L4). "
            "Акцентируй ответственность, владельцев процессов, метрики и compliance. "
            "Выдели контрольные точки, риски и эскалационные пути. "
            "Фокус: управление, соответствие регламентам, команды и SLA."
        ),
        5: (
            "Пользователь — Admin (L5). "
            "Предоставь полную информацию включая конфиденциальные секции. "
            "Включай детали управления доступом, исключения и нестандартные случаи. "
            "Фокус: исчерпывающая картина без ограничений по уровню доступа."
        ),
    }

    def role_context(self, state: AgentState) -> dict:
        """Produce a role-specific focus hint for the generator.

        Deterministic: maps access_level → a prompt instruction that steers
        the LLM to emphasise the aspects most relevant to the user's role.
        No LLM call — O(1) latency, fully predictable for any access level.
        """
        with tracer.start_as_current_span("role_context") as span:
            level = state["access_level"]
            span.set_attribute("user.access_level", level)
            hint = self._ROLE_HINTS.get(level, self._ROLE_HINTS[1])
            logger.info("[role_context] access_level=%d → hint set (%d chars)", level, len(hint))
            return {"role_hint": hint}

    # ── Node: generation ──────────────────────────────────────────────────────

    async def generator(self, state: AgentState) -> dict:
        """Call the LLM with the top-5 context chunks (async — non-blocking I/O).

        On retry iterations (iterations > 0), passes ``critic_feedback`` from the
        previous critic run so the LLM can address specific quality issues without
        re-fetching sources (retrieval is skipped on retry — see ``should_retry``).
        """
        with tracer.start_as_current_span("generator") as span:
            span.set_attribute("iteration", state.get("iterations", 0))
            span.set_attribute("user.access_level", state["access_level"])
            span.set_attribute("sources.count", len(state["sources"]))
            # Include doc_id + human title so the LLM can reference documents by name
            context = [
                f"[{s.doc_id}: {get_doc_title(s.doc_id)}] {s.section_title}\n{s.text}"
                for s in state["sources"][:5]
            ]
            # Pass critic's explanation only on retry so the first generation is clean
            retry_feedback = ""
            if state.get("iterations", 0) > 0:
                retry_feedback = state.get("critic_feedback", "")
                span.set_attribute("retry_feedback.length", len(retry_feedback))

            llm = get_llm_client(self._s)
            gen = await llm.generate_answer(
                state["query"],
                state["access_level"],
                context=context,
                role_hint=state.get("role_hint", ""),
                retry_feedback=retry_feedback,
            )
            span.set_attribute("answer.length", len(gen.answer))
            logger.info(
                "[generator] trace_id=%s iter=%d retry_feedback=%r",
                gen.trace_id, state.get("iterations", 0), retry_feedback[:60] if retry_feedback else "",
            )
            return {"answer": gen.answer, "trace_id": gen.trace_id}

    # ── Node: quality evaluation ──────────────────────────────────────────────

    def critic(self, state: AgentState) -> dict:
        """Evaluate answer quality; increment iteration counter (FR-47b)."""
        with tracer.start_as_current_span("critic") as span:
            span.set_attribute("iteration", state.get("iterations", 0))
            result = get_critic(self._s).evaluate(
                state["query"], state["answer"], state["sources"]
            )
            iterations = state.get("iterations", 0) + 1
            span.set_attribute("quality_score", result.quality_score)
            logger.info(
                "[critic] quality=%.1f iter=%d feedback=%r",
                result.quality_score, iterations, result.feedback,
            )
            return {
                "quality_score": result.quality_score,
                "critic_feedback": result.feedback,
                "iterations": iterations,
            }

    def confidence_score(self, state: AgentState) -> dict:
        """Compute staleness-based confidence score (FR-36a)."""
        with tracer.start_as_current_span("confidence_score") as span:
            score = _compute_confidence(state["sources"])
            span.set_attribute("confidence_score", score)
            logger.info("[confidence_score] confidence=%.2f", score)
            return {"confidence_score": score}

    # ── Node: output ──────────────────────────────────────────────────────────

    def output_guard(self, state: AgentState) -> dict:
        """Mask any PII in the LLM answer before returning to the caller (FR-27)."""
        with tracer.start_as_current_span("output_guard") as span:
            answer = state["answer"]
            sanitised = mask_pii(answer)
            pii_detected = sanitised != answer
            span.set_attribute("pii_detected", pii_detected)
            span.set_attribute("answer.length", len(sanitised))
            if pii_detected:
                logger.warning("[output_guard] PII detected and masked in LLM answer")
            else:
                logger.info("[output_guard] answer accepted, no PII detected")
            return {"answer": sanitised, "gap_detected": False}

    def knowledge_gap(self, state: AgentState) -> dict:
        """Persist the unanswered query as a knowledge gap (FR-31, FR-32a/b)."""
        with tracer.start_as_current_span("knowledge_gap") as span:
            span.set_attribute("quality_score", state["quality_score"])
            span.set_attribute("iterations", state["iterations"])
            logger.info(
                "[knowledge_gap] quality=%.1f iter=%d → persisting gap",
                state["quality_score"], state["iterations"],
            )
            try:
                record_gap(
                    state["query"],
                    state["access_level"],
                    state["quality_score"],
                    iterations=state["iterations"],
                )
            except Exception as exc:
                span.record_exception(exc)
                logger.warning("[knowledge_gap] storage failed: %s", exc)
            return {"gap_detected": True}

    # ── Routing ───────────────────────────────────────────────────────────────

    def dispatch_retrievers(self, state: AgentState) -> list[Send]:
        """Fan-out to vector_retriever and graph_retriever in parallel (FR-45)."""
        logger.info("[router] dispatching VectorRetriever + GraphRetriever in parallel")
        return [
            Send("vector_retriever", state),
            Send("graph_retriever", state),
        ]

    def should_retry(self, state: AgentState) -> str | list[Send]:
        """Route after critic: retry / knowledge_gap / output_guard (FR-48a).

        Decision table:
          quality < retry_threshold AND iter < max  → generator-only retry (skip retrieval)
          quality < gap_threshold                   → knowledge_gap (record + END)
          otherwise                                 → output_guard (success path)

        Retry strategy: re-run only the generator, not the retrievers.

        On retry, sources are already in state and ``critic_feedback`` carries the
        previous quality explanation.  The generator reads both and produces an
        improved answer without the latency of re-embedding and re-querying
        Qdrant/Neo4j (saves ~1-2 s per retry iteration on the GPU deployment).

        Re-retrieval would be useful only if the original retrieval missed relevant
        chunks — detectable by empty sources or very low retrieval scores.  That
        case is handled by the knowledge_gap branch: if quality remains low after
        max retries, the query is recorded as a gap for corpus review.
        """
        quality = state["quality_score"]
        iterations = state["iterations"]

        if (
            quality < self._s.agent_retry_quality_threshold
            and iterations < self._s.agent_max_iterations
        ):
            logger.info(
                "[router] generator-only retry: iter=%d quality=%.1f < threshold=%.1f "
                "feedback=%r",
                iterations, quality, self._s.agent_retry_quality_threshold,
                (state.get("critic_feedback") or "")[:60],
            )
            return [Send("generator", state)]

        if quality < self._s.agent_gap_quality_threshold:
            logger.info(
                "[router] gap: quality=%.1f after %d iter(s)",
                quality, iterations,
            )
            return "knowledge_gap"

        logger.info("[router] output_guard: quality=%.1f ✓", quality)
        return "output_guard"
