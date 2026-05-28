"""
Tests for backend/ingestion/document_processor.py.

Covers:
  - Markdown extraction (pure Python, no heavy deps)
  - PDF native text extraction (PyMuPDF required)
  - Unsupported format raises NotImplementedError
  - Missing file raises FileNotFoundError
"""

import pytest
from pathlib import Path

from backend.ingestion.document_processor import (
    SUPPORTED_SUFFIXES,
    extract_text,
)


# ── Markdown ─────────────────────────────────────────────────────────────────

def test_extract_md_returns_content(tmp_path: Path) -> None:
    f = tmp_path / "doc.md"
    f.write_text("# Title\n\nBody text.", encoding="utf-8")
    assert extract_text(f) == "# Title\n\nBody text."


def test_extract_md_preserves_unicode(tmp_path: Path) -> None:
    content = "Политика доступа — раздел 1.2\n\n中文内容"
    f = tmp_path / "doc.md"
    f.write_text(content, encoding="utf-8")
    assert extract_text(f) == content


# ── PDF ──────────────────────────────────────────────────────────────────────

def test_extract_pdf_native_text(tmp_path: Path) -> None:
    """Born-digital PDF: text layer must be extracted correctly.

    Note: PyMuPDF's built-in fonts (Helvetica) cover Latin-1 only.
    Cyrillic / CJK requires embedding an external font — out of scope for
    this unit test.  Real corpus PDFs are expected to have embedded fonts.
    """
    fitz = pytest.importorskip("fitz", reason="pymupdf not installed")

    pdf_path = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Information Security Policy", fontsize=12)
    page.insert_text((50, 100), "Section 1: Introduction", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    text = extract_text(pdf_path)
    assert "Information Security Policy" in text
    assert "Section 1" in text


def test_extract_pdf_multipage(tmp_path: Path) -> None:
    """Multi-page PDF: pages joined with double newline."""
    fitz = pytest.importorskip("fitz", reason="pymupdf not installed")

    pdf_path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((50, 72), f"Page {i + 1} content", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()

    text = extract_text(pdf_path)
    assert "Page 1 content" in text
    assert "Page 2 content" in text
    assert "Page 3 content" in text
    assert "\n\n" in text   # pages are joined with double newline


_ARIAL_UNICODE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


@pytest.mark.skipif(
    not Path(_ARIAL_UNICODE).exists(),
    reason="Arial Unicode not available on this system",
)
def test_extract_pdf_cyrillic(tmp_path: Path) -> None:
    """PDF with embedded Cyrillic font: extract_text() returns correct Unicode.

    Demonstrates that the extraction is language-agnostic — the Latin-only
    limitation seen in other tests is specific to PyMuPDF's built-in fonts
    used for *creating* test PDFs, not to the extraction itself.
    """
    fitz = pytest.importorskip("fitz", reason="pymupdf not installed")

    pdf_path = tmp_path / "cyrillic.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Embed Arial Unicode so Cyrillic glyphs are stored in the PDF text layer
    page.insert_text(
        (50, 72),
        "Политика информационной безопасности",
        fontfile=_ARIAL_UNICODE,
        fontname="ArialUnicode",
        fontsize=12,
    )
    page.insert_text(
        (50, 100),
        "Раздел 1: Общие положения",
        fontfile=_ARIAL_UNICODE,
        fontname="ArialUnicode",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()

    text = extract_text(pdf_path)
    assert "Политика" in text
    assert "Раздел 1" in text


# ── Error cases ───────────────────────────────────────────────────────────────

def test_extract_unsupported_format_raises(tmp_path: Path) -> None:
    f = tmp_path / "table.xlsx"
    f.write_bytes(b"fake xlsx content")
    with pytest.raises(NotImplementedError, match="xlsx"):
        extract_text(f)


def test_extract_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "nonexistent.md")


# ── SUPPORTED_SUFFIXES contract ───────────────────────────────────────────────

def test_supported_suffixes_contains_md_and_pdf() -> None:
    assert ".md" in SUPPORTED_SUFFIXES
    assert ".pdf" in SUPPORTED_SUFFIXES
