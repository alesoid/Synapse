"""
Observability — OpenTelemetry SDK + Langfuse (ADR-010).

Two complementary layers that run simultaneously:

  1. OpenTelemetry SDK  — vendor-neutral spans for every FastAPI request and
     every LangGraph node.  Exports via OTLP/HTTP to Langfuse (self-hosted).
     Satisfies FR-28a, FR-28b, FR-49.

  2. Langfuse CallbackHandler — LLM-specific metadata (token counts, model
     name, prompt/response pairs) layered on top of the OTel trace inside
     the Langfuse UI.  Complements the structural span tree.

Call order during startup:
  1. ``tracer`` is obtained at import time from the global ProxyTracerProvider
     (no-op until a real provider is installed).
  2. ``setup_tracing(app)`` installs a real TracerProvider + OTLP exporter and
     calls ``FastAPIInstrumentor.instrument_app(app)``.  The ProxyTracer
     automatically delegates to the new provider — all spans created after this
     point (including those obtained before the call) use the real exporter.

Both functions degrade gracefully: if opentelemetry-* packages are not
installed the app starts normally, simply without OTel tracing.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import os
from typing import TYPE_CHECKING

from backend.core.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ── No-op fallback (used when opentelemetry-sdk is not installed) ─────────────

class _NoOpSpan:
    """Minimal span interface so node code compiles without opentelemetry-sdk."""
    def set_attribute(self, key: str, value: object) -> None: ...  # noqa: E704
    def record_exception(self, exc: BaseException, **_: object) -> None: ...  # noqa: E704
    def set_status(self, *_: object) -> None: ...  # noqa: E704


class _NoOpTracer:
    """Minimal tracer interface — every span is a no-op context manager."""

    @contextlib.contextmanager  # type: ignore[misc]
    def start_as_current_span(self, name: str, **kwargs: object):
        yield _NoOpSpan()


# ── Module-level tracer ───────────────────────────────────────────────────────
#
# Obtained at import time.  When opentelemetry-sdk IS installed this is a
# ProxyTracer that automatically delegates to whatever TracerProvider is
# installed at the time a span is created — so ``setup_tracing()`` can be
# called *after* this module is imported and all spans will still use the
# real exporter.
#
# When opentelemetry-sdk is NOT installed this is the _NoOpTracer above.

try:
    from opentelemetry import trace as _otel_trace  # type: ignore[import]

    tracer: _NoOpTracer = _otel_trace.get_tracer("synapse.agent")  # type: ignore[assignment]
except ImportError:
    tracer = _NoOpTracer()


# ── OTel provider setup ───────────────────────────────────────────────────────

def setup_tracing(app: "FastAPI") -> None:
    """Install the OTel SDK and auto-instrument FastAPI (FR-28a, FR-28b).

    Reads configuration from environment variables:
        LANGFUSE_OTLP_ENDPOINT  — OTLP/HTTP ingest URL (default: localhost:3000)
        LANGFUSE_PUBLIC_KEY     — used as Basic-auth username
        LANGFUSE_SECRET_KEY     — used as Basic-auth password

    Safe to call multiple times — the underlying OTel SDK is idempotent.
    Degrades gracefully if opentelemetry-* packages are not installed.
    """
    try:
        from opentelemetry import trace  # type: ignore[import]
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import]
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import (  # type: ignore[import]
            FastAPIInstrumentor,
        )
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]
    except ImportError:
        logger.warning(
            "[tracing] opentelemetry-sdk not installed — OTel tracing disabled. "
            "Run: pip install 'synapse[observability]'",
        )
        return

    otlp_endpoint = os.getenv(
        "LANGFUSE_OTLP_ENDPOINT",
        "http://localhost:3000/api/public/otel/v1/traces",
    )
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")

    if not (public_key and secret_key):
        logger.warning(
            "[tracing] LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set — "
            "OTel spans will be created but not exported",
        )

    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

    provider = TracerProvider()
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        headers={"Authorization": f"Basic {credentials}"},
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument all FastAPI routes — creates an HTTP span per request
    # that becomes the root span for all child node spans (FR-28a).
    FastAPIInstrumentor.instrument_app(app)

    logger.info(
        "[tracing] OTel SDK configured → OTLP export to %s",
        otlp_endpoint,
    )


# ── Langfuse CallbackHandler (LLM-level enrichment) ──────────────────────────

def get_langfuse_callbacks(settings: Settings) -> list:
    """Return a Langfuse CallbackHandler for LLM-specific metadata (FR-28b).

    Complements the OTel trace with LLM-layer attributes: token counts, model
    name, raw prompt/response pairs.  The CallbackHandler attaches to the
    active OTel span context so Langfuse correlates them in the same trace.

    Returns an empty list when Langfuse is not configured or not installed —
    the agent runs without LLM-level tracing rather than crashing.
    """
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    try:
        from langfuse.callback import CallbackHandler  # type: ignore[import]

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("[tracing] Langfuse CallbackHandler enabled → %s", settings.langfuse_host)
        return [handler]
    except ImportError:
        logger.warning("[tracing] langfuse package not installed — LLM-level tracing disabled")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tracing] Langfuse init failed (%s) — LLM-level tracing disabled", exc)
        return []
