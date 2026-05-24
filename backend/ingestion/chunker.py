import re

from backend.ingestion.models import DocumentChunk, PreparedDocument

HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
TOKEN_PATTERN = re.compile(r"\S+")


def count_tokens(text: str) -> int:
    return len(TOKEN_PATTERN.findall(text))


def split_markdown_sections(text: str, default_title: str) -> list[tuple[str, str]]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        return [(default_title, text.strip())]

    sections: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append((default_title, preamble))

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group(2).strip()
        body = text[start:end].strip()
        section_text = f"{match.group(0).strip()}\n\n{body}".strip()
        if section_text:
            sections.append((title, section_text))
    return sections


def chunk_text_by_tokens(text: str, chunk_size: int, overlap: int) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text)
    if not tokens:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(" ".join(tokens[start:end]))
        if end == len(tokens):
            break
        start = end - overlap
    return chunks


def chunk_document(
    document: PreparedDocument,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    sections = split_markdown_sections(document.text, document.metadata.title)

    for section_index, (section_title, section_text) in enumerate(sections):
        section_chunks = chunk_text_by_tokens(section_text, chunk_size, overlap)
        for section_chunk_index, chunk_text in enumerate(section_chunks):
            chunk_index = len(chunks)
            chunk_id = (
                f"{document.metadata.doc_id}::s{section_index:03d}"
                f"::c{section_chunk_index:03d}"
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    doc_id=document.metadata.doc_id,
                    doc_type=document.metadata.doc_type,
                    access_level=document.metadata.access_level,
                    last_updated=document.metadata.last_updated,
                    section_title=section_title,
                    text=chunk_text,
                    chunk_index=chunk_index,
                    source=str(document.path),
                    topics=document.metadata.topics,
                )
            )
    return chunks
