"""
Query rewriting for improved vector retrieval.

User queries are often phrased as questions ("Как проходит онбординг?")
while document chunks are written as statements ("Процедура адаптации
включает..."). This semantic mismatch reduces recall in vector search.

QueryRewriter reformulates the user query into document-style language
before embedding — a technique that consistently improves RAG recall
without changing the retrieval infrastructure.

Two implementations:
  VLLMQueryRewriter  — LLM-based rewrite (gpu-demo / production)
  MockQueryRewriter  — pass-through (local-lite / tests)

The rewritten query is stored in AgentState.query_rewritten and used
only by the vector retriever. Graph retrieval continues to use the
original entities extracted in prepare_query (entity names are already
canonical after ontology resolution, so rewriting adds no value there).
"""

from __future__ import annotations

import logging
from typing import Protocol

from backend.core.config import Settings

logger = logging.getLogger(__name__)


class QueryRewriter(Protocol):
    def rewrite(self, query: str) -> str: ...


class MockQueryRewriter:
    """Pass-through rewriter for local-lite / test mode."""

    def rewrite(self, query: str) -> str:
        return query


class VLLMQueryRewriter:
    """LLM-based query rewriter that converts user questions to
    document-search style phrases for better vector retrieval recall.

    Uses a sync httpx call (same pool as VLLMCriticAgent) because this
    node runs in a sync LangGraph step. Output is kept short (≤ 80 tokens)
    to minimise latency — the rewriter adds ~0.3–0.8 s per request.

    Falls back to the original query on any error so the pipeline never
    stalls due to a rewriter failure.
    """

    _SYSTEM_PROMPT = (
        "Ты помогаешь улучшить поиск в корпоративной базе знаний. "
        "Перепиши вопрос пользователя в виде поискового запроса к документам: "
        "используй ключевые термины, синонимы, деловой язык корпоративных регламентов. "
        "Верни ТОЛЬКО переписанный запрос — без объяснений, кавычек и лишних слов.\n\n"
        "Примеры:\n"
        "Вход: «Как проходит онбординг новых сотрудников?»\n"
        "Выход: процедура адаптации новых сотрудников этапы документы ответственные\n\n"
        "Вход: «Можно ли работать удалённо?»\n"
        "Выход: удалённая работа дистанционный формат политика регламент условия\n\n"
        "Вход: «Кто утверждает бюджет на IT-проекты?»\n"
        "Выход: согласование бюджета IT-проектов ответственный утверждение регламент бюджетирования"
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def rewrite(self, query: str) -> str:
        from backend.core.connections import get_pool

        try:
            resp = get_pool().http.post(
                f"{self._settings.vllm_host}/v1/chat/completions",
                json={
                    "model": self._settings.vllm_model,
                    "messages": [
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 80,
                },
            )
            resp.raise_for_status()
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            # Guard: if the model returned something too short or too long, fall back
            if len(rewritten) < 5 or len(rewritten) > len(query) * 4:
                logger.warning(
                    "[rewriter] suspicious output %r — using original query", rewritten
                )
                return query
            logger.info("[rewriter] %r → %r", query[:60], rewritten[:60])
            return rewritten
        except Exception as exc:
            logger.warning("[rewriter] failed (%s) — using original query", exc)
            return query


def get_query_rewriter(settings: Settings) -> QueryRewriter:
    """Return the appropriate rewriter for the active LLM backend."""
    if settings.llm_backend == "vllm":
        return VLLMQueryRewriter(settings)
    return MockQueryRewriter()
