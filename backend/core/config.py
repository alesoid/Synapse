from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "synapse"
    app_version: str = "0.1.0"
    app_mode: Literal["local-lite", "gpu-demo", "test"] = "local-lite"
    llm_backend: Literal["mock", "vllm"] = "mock"
    embeddings_backend: Literal["mock", "local"] = "mock"
    ollama_host: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    storage_backend: Literal["mock", "qdrant-neo4j"] = "mock"
    mock_embedding_dimension: int = 16
    embedding_dimension: int = 768  # nomic-embed-text; set to 16 for mock backend

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    vllm_host: str = "http://vllm:8001"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "chunks"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "synapse_secret"
    chunk_size: int = 500
    chunk_overlap: int = 50
    hybrid_alpha: float = 0.7  # weight for vector score; (1 - alpha) = graph weight
    corpus_manifest_path: str = "docs/corpus/corpus_manifest.json"
    corpus_adapted_dir: str = "docs/corpus/adapted"

    # vLLM
    vllm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"

    gap_store_path: str = "gaps.db"    # override in tests / Docker
    audit_store_path: str = "audit.db"  # override in tests / Docker

    # Agent behaviour (FR-48a)
    agent_max_iterations: int = 3           # max critic-retry loops
    agent_retry_quality_threshold: float = 3.0   # retry if quality < this
    agent_gap_quality_threshold: float = 2.0     # record gap if quality < this after max retries

    # Langfuse (optional — empty string disables tracing)
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
