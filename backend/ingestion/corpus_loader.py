import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.ingestion.document_processor import SUPPORTED_SUFFIXES, extract_text
from backend.ingestion.models import DocumentMetadata, PreparedDocument

logger = logging.getLogger(__name__)

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
    """Load all supported documents from *corpus_dir* according to *manifest_path*.

    Supported formats: .md (Markdown), .pdf (native text layer via PyMuPDF).
    Unsupported formats are skipped with a warning.
    Files listed in the manifest but missing on disk are also skipped.

    The function name is kept for backward compatibility; it now handles
    any format listed in ``document_processor.SUPPORTED_SUFFIXES``.
    """
    documents: list[PreparedDocument] = []
    for metadata in load_manifest(manifest_path):
        path = corpus_dir / metadata.filename
        suffix = path.suffix.lower()

        if suffix not in SUPPORTED_SUFFIXES:
            logger.debug(
                "[corpus_loader] skipping '%s': format '%s' not yet supported "
                "(see ADR-013 for DOCX/XLSX/OCR roadmap)",
                metadata.filename, suffix,
            )
            continue

        try:
            text = extract_text(path)
        except FileNotFoundError:
            logger.warning("[corpus_loader] file not found, skipping: %s", path)
            continue
        except NotImplementedError as exc:
            logger.warning("[corpus_loader] %s", exc)
            continue

        logger.debug(
            "[corpus_loader] loaded '%s' (%s, %d chars)",
            metadata.filename, suffix, len(text),
        )
        documents.append(PreparedDocument(metadata=metadata, path=path, text=text))
    return documents
