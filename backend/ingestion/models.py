from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentMetadata:
    doc_id: str
    filename: str
    title: str
    doc_type: str
    access_level: int
    role_min: str
    owner_department: str
    last_updated: str
    topics: list[str]


@dataclass(frozen=True)
class PreparedDocument:
    metadata: DocumentMetadata
    path: Path
    text: str


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    access_level: int
    last_updated: str
    section_title: str
    text: str
    chunk_index: int
    source: str
    topics: list[str]


@dataclass(frozen=True)
class IngestionResult:
    documents_processed: int
    chunks_created: int
    graph_nodes_projected: int
    graph_edges_projected: int
    storage_backend: str
