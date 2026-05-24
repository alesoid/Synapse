from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Protocol

from backend.core.config import Settings


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    trace_id: str
    # Note: quality_score comes from CriticAgent.evaluate(), not from the LLM call itself.


class LLMClient(Protocol):
    async def generate_answer(
        self,
        query: str,
        access_level: int,
        context: list[str] | None = None,
    ) -> GenerationResult: ...


class MockLLMClient:
    """Deterministic local-lite LLM replacement.

    Stable for the same query and role — smoke tests reproducible without GPU.
    Records mock tokens_per_second so the Prometheus metric is always populated
    even in local-lite mode (FR-29c).
    """

    # Approximate mock throughput: pretend 50 tokens at 500 tok/s
    _MOCK_TOKENS = 50

    async def generate_answer(
        self,
        query: str,
        access_level: int,
        context: list[str] | None = None,
    ) -> GenerationResult:
        t0 = time.perf_counter()

        normalized_query = " ".join(query.strip().split())
        query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()[:12]
        ctx_note = f" Context chunks: {len(context)}." if context else ""
        answer = (
            "[mock-llm] Synapse local-lite backend accepted the query: "
            f"'{normalized_query}'. Access level: {access_level}.{ctx_note}"
        )

        elapsed = time.perf_counter() - t0
        _emit_metrics("mock", self._MOCK_TOKENS, max(elapsed, 0.001))

        return GenerationResult(
            answer=answer,
            trace_id=f"mock-{access_level}-{query_hash}",
        )


class VLLMClient:
    _SYSTEM_PROMPT = (
        "Ты корпоративный AI-ассистент. Отвечай строго на основе предоставленного контекста. "
        "Если ответ не найден в контексте — честно сообщи об этом. "
        "Отвечай на том же языке, на котором задан вопрос."
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def generate_answer(
        self,
        query: str,
        access_level: int,
        context: list[str] | None = None,
    ) -> GenerationResult:
        ctx_block = ""
        if context:
            ctx_block = "\n\nКонтекст из базы знаний:\n" + "\n---\n".join(context)

        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT + ctx_block},
            {"role": "user", "content": query},
        ]

        from backend.core.connections import get_pool

        t0 = time.perf_counter()
        # Reuse pooled httpx.AsyncClient — non-blocking I/O, no new TCP handshake per request
        resp = await get_pool().async_http.post(
            f"{self._settings.vllm_host}/v1/chat/completions",
            json={
                "model": self._settings.vllm_model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 512,
            },
        )
        resp.raise_for_status()
        elapsed = time.perf_counter() - t0

        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()

        # FR-29c: extract completion_tokens from vLLM usage field
        usage = data.get("usage", {})
        completion_tokens = usage.get("completion_tokens", 0)
        _emit_metrics("vllm", completion_tokens, elapsed)

        query_hash = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:12]
        return GenerationResult(
            answer=answer,
            trace_id=f"vllm-{access_level}-{query_hash}",
        )


def _emit_metrics(backend: str, completion_tokens: int, elapsed_seconds: float) -> None:
    """Record FR-29c tokens_per_second and related LLM metrics (best-effort)."""
    try:
        from backend.observability.metrics import record_generation
        record_generation(backend, completion_tokens, elapsed_seconds)
    except Exception:
        pass  # never crash the pipeline due to metrics


def get_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_backend == "mock":
        return MockLLMClient()
    if settings.llm_backend == "vllm":
        return VLLMClient(settings)
    raise ValueError(f"Unsupported LLM_BACKEND: {settings.llm_backend}")
