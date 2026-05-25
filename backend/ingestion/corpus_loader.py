import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.ingestion.models import DocumentMetadata, PreparedDocument

# ── Title lookup (manifest-based, cached once per process) ───────────────────

_MANIFEST_PATH = Path(__file__).parent.parent.parent / "docs" / "corpus" / "corpus_manifest.json"


@lru_cache(maxsize=1)
def _load_title_map() -> dict[str, str]:
    """Return {doc_id: title} from corpus_manifest.json (loaded once, then cached)."""
    if not _MANIFEST_PATH.exists():
        return {}
    data: list[dict[str, Any]] = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {item["doc_id"]: item["title"] for item in data}


def get_doc_title(doc_id: str) -> str:
    """Human-readable title for *doc_id*; falls back to *doc_id* if unknown."""
    return _load_title_map().get(doc_id, doc_id)


def load_manifest(manifest_path: Path) -> list[DocumentMetadata]:
    raw_items: list[dict[str, Any]] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        DocumentMetadata(
            doc_id=item["doc_id"],
            filename=item["filename"],
            title=item["title"],
            doc_type=item["doc_type"],
            access_level=int(item["access_level"]),
            role_min=item["role_min"],
            owner_department=item["owner_department"],
            last_updated=item["last_updated"],
            topics=list(item.get("topics", [])),
        )
        for item in raw_items
    ]


def load_markdown_corpus(
    manifest_path: Path,
    corpus_dir: Path,
) -> list[PreparedDocument]:
    documents: list[PreparedDocument] = []
    for metadata in load_manifest(manifest_path):
        path = corpus_dir / metadata.filename
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        documents.append(PreparedDocument(metadata=metadata, path=path, text=text))
    return documents
