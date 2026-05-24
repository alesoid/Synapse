"""
Custom Prometheus metrics for Synapse (FR-29a, FR-29b, FR-29c).

Standard request metrics (request_latency_seconds, request_count_total) are
emitted automatically by prometheus-fastapi-instrumentator in main.py.

This module adds LLM-specific metrics that prometheus-fastapi-instrumentator
cannot capture automatically:

  FR-29c  tokens_per_second  — LLM generation throughput (tokens / second).
                               Set after each generate_answer() call.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# FR-29c: LLM generation throughput
# Gauge — current/recent speed, not cumulative (correct type for "last observed value")
llm_tokens_per_second = Gauge(
    "synapse_llm_tokens_per_second",
    "LLM generation speed in tokens per second (last observed call)",
    labelnames=["backend"],  # "mock" or "vllm"
)

# FR-29c: total completion tokens generated — Counter (monotonically increasing)
# Use Counter, not Gauge: counters survive scrape gaps and are rate()-able in PromQL.
llm_completion_tokens_total = Counter(
    "synapse_llm_completion_tokens_total",
    "Total completion tokens generated since last restart",
    labelnames=["backend"],
)

# Latency distribution of LLM calls (complements FR-29a for LLM specifically)
llm_generation_seconds = Histogram(
    "synapse_llm_generation_seconds",
    "Time spent on LLM generation per request",
    labelnames=["backend"],
    buckets=(0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0),
)


def record_generation(
    backend: str,
    completion_tokens: int,
    elapsed_seconds: float,
) -> None:
    """Update all LLM throughput metrics after a generate_answer() call.

    Args:
        backend: "mock" or "vllm"
        completion_tokens: number of tokens in the LLM response
        elapsed_seconds: wall-clock time for the LLM call
    """
    if elapsed_seconds > 0 and completion_tokens > 0:
        tps = completion_tokens / elapsed_seconds
        llm_tokens_per_second.labels(backend=backend).set(tps)
        llm_completion_tokens_total.labels(backend=backend).inc(completion_tokens)
    llm_generation_seconds.labels(backend=backend).observe(elapsed_seconds)
