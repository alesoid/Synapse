"""
Embeddings clients for Synapse.

Backends:
  mock  — deterministic SHA-256 vectors; works on any machine, no GPU required.
  local — nomic-embed-text via Ollama HTTP API; used in gpu-demo profile.
          Ollama must be running with the model pulled:
            docker exec synapse-ollama ollama pull nomic-embed-text
          Vector dimension: 768 (nomic-embed-text default).

Performance note
----------------
LocalEmbeddingsClient reuses the pooled httpx.Client (get_pool().ollama_http)
so the TCP connection to Ollama is kept alive across requests — no new handshake
per embed_query() call.

embed_batch() sends all texts in a single POST to Ollama's /api/embed endpoint
(available since Ollama 0.1.31).  _write_qdrant() uses this to reduce N HTTP
round-trips per ingestion to exactly 1.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

from backend.core.config import Settings


class EmbeddingsClient(Protocol):
    def embed_query(self, text: str) -> list[float]:
        """Return a unit-normalised embedding vector for a single text."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return unit-normalised embedding vectors for a list of texts.

        Implementations should send a single HTTP request when possible
        (batch API) rather than one request per text.
        """


class MockEmbeddingsClient:
    """Deterministic hash-based embedding replacement for local-lite tests.

    Stable: same text → same vector across restarts.
    Dimension configurable via MOCK_EMBEDDING_DIMENSION (default 16).
    """

    def __init__(self, dimension: int = 16) -> None:
        self._dimension = dimension

    def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.strip().lower().encode("utf-8")).digest()
        values = [
            ((digest[i % len(digest)] / 255.0) * 2.0) - 1.0
            for i in range(self._dimension)
        ]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [round(v / norm, 6) for v in values]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Vectorise each text independently (mock — no batch API needed)."""
        return [self.embed_query(t) for t in texts]


class LocalEmbeddingsClient:
    """nomic-embed-text via Ollama HTTP API (gpu-demo profile).

    Uses the pooled httpx.Client (get_pool().ollama_http) for connection reuse.

    embed_batch() sends all texts in ONE request to POST /api/embed which
    accepts ``{"model": "...", "input": ["text1", "text2", ...]}``.
    This cuts ingestion HTTP round-trips from N to 1.

    Requires Ollama to be running and the model to be pulled:
        docker exec synapse-ollama ollama pull nomic-embed-text
    """

    def __init__(self, settings: Settings) -> None:
        self._model = settings.ollama_embedding_model
        # Base URL is baked into the pooled client; we only need the model name.

    # ── Public API ────────────────────────────────────────────────────────────

    def embed_query(self, text: str) -> list[float]:
        """Embed a single text.  Delegates to embed_batch() for connection reuse."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed all *texts* in a single HTTP request via Ollama /api/embed.

        Ollama /api/embed (≥ 0.1.31) accepts::
            {"model": "...", "input": ["text1", "text2", ...]}
        and returns::
            {"embeddings": [[...], [...]]}

        Falls back to sequential /api/embeddings calls if the batch endpoint
        returns 404 (older Ollama versions).
        """
        from backend.core.connections import get_pool

        client = get_pool().ollama_http
        stripped = [t.strip() for t in texts]

        try:
            resp = client.post(
                "/api/embed",
                json={"model": self._model, "input": stripped},
            )
            if resp.status_code == 404:
                # Older Ollama: fall back to per-text sequential calls
                return self._embed_sequential(client, stripped)
            resp.raise_for_status()
            return resp.json()["embeddings"]
        except Exception as exc:
            self._raise_connection_error(exc)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _embed_sequential(
        self, client: object, texts: list[str]
    ) -> list[list[float]]:
        """Fallback: call POST /api/embeddings once per text (Ollama < 0.1.31)."""
        import httpx as _httpx

        results: list[list[float]] = []
        for text in texts:
            try:
                resp = client.post(  # type: ignore[union-attr]
                    "/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
                resp.raise_for_status()
                results.append(resp.json()["embedding"])
            except Exception as exc:
                self._raise_connection_error(exc)
        return results

    def _raise_connection_error(self, exc: Exception) -> None:
        from backend.core.config import get_settings
        host = get_settings().ollama_host
        raise RuntimeError(
            f"Cannot reach Ollama at {host}. "
            "Ensure 'ollama' container is running (gpu profile) "
            "and model is pulled: ollama pull nomic-embed-text"
        ) from exc


def get_embeddings_client(settings: Settings) -> EmbeddingsClient:
    if settings.embeddings_backend == "mock":
        return MockEmbeddingsClient(dimension=settings.mock_embedding_dimension)
    if settings.embeddings_backend == "local":
        return LocalEmbeddingsClient(settings)
    raise ValueError(f"Unsupported EMBEDDINGS_BACKEND: {settings.embeddings_backend}")
