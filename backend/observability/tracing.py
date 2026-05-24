"""
Langfuse tracing integration.

Returns a LangChain-compatible CallbackHandler if Langfuse is installed
and LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are set.
Returns an empty list otherwise — the agent runs untraced.
"""

from __future__ import annotations

import logging

from backend.core.config import Settings

logger = logging.getLogger(__name__)


def get_langfuse_callbacks(settings: Settings) -> list:
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    try:
        from langfuse.callback import CallbackHandler  # type: ignore[import]

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse tracing enabled → %s", settings.langfuse_host)
        return [handler]
    except ImportError:
        logger.warning("langfuse package not installed — tracing disabled")
        return []
    except Exception as exc:
        logger.warning("Langfuse init failed (%s) — tracing disabled", exc)
        return []
