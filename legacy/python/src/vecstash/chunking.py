from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter

from vecstash.extraction import ExtractedDocument

_PARAGRAPH_SPLIT = re.compile(r"\n\n+")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_index: int


def chunk_document(doc: ExtractedDocument, min_chars: int = 100) -> list[Chunk]:
    """Split a document into paragraph-level chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50
    )
    paragraphs = splitter.split_text(doc.text)
    chunks: list[Chunk] = []
    idx = 0
    for paragraph in paragraphs:
        raw = f"{doc.document_id}:{idx}"
        chunk_id = hashlib.sha256(raw.encode()).hexdigest()
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=doc.document_id,
                text=paragraph,
                chunk_index=idx
            )
        )
        idx += 1
    return chunks
