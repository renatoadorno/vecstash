from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import mimetypes
from pathlib import Path
import re
import unicodedata

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from pypdf import PdfReader

_WS_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

SUPPORTED_SOURCE_KINDS = {
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
}


@dataclass(frozen=True)
class ExtractedDocument:
    document_id: str
    source_path: Path
    source_kind: str
    text: str
    metadata: dict[str, str | int]


def normalize_text(raw_text: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    previous_blank = False
    for line in normalized.split("\n"):
        compact = _WS_RE.sub(" ", line).strip()
        if compact:
            lines.append(compact)
            previous_blank = False
            continue
        if not previous_blank:
            lines.append("")
            previous_blank = True

    collapsed = "\n".join(lines).strip()
    return _MULTI_NEWLINE_RE.sub("\n\n", collapsed)


def _extract_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_md(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    rendered_html = MarkdownIt("commonmark").render(raw)
    return _extract_html_from_text(rendered_html)


def _extract_html_from_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _extract_html(path: Path) -> str:
    return _extract_html_from_text(path.read_text(encoding="utf-8"))


def _extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError(f"Encrypted PDF is not supported: {path}")

    page_texts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append(text)
    return "\n\n".join(page_texts)


def _resolve_source_kind(path: Path) -> str:
    kind = SUPPORTED_SOURCE_KINDS.get(path.suffix.lower())
    if kind is None:
        supported = ", ".join(sorted(SUPPORTED_SOURCE_KINDS))
        raise ValueError(f"Unsupported file type for {path}. Supported suffixes: {supported}")
    return kind


def extract_file(path: Path) -> ExtractedDocument:
    source_path = path.expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {source_path}")
    if not source_path.is_file():
        raise ValueError(f"Path is not a file: {source_path}")

    source_kind = _resolve_source_kind(source_path)
    if source_kind == "txt":
        raw_text = _extract_txt(source_path)
    elif source_kind == "md":
        raw_text = _extract_md(source_path)
    elif source_kind == "html":
        raw_text = _extract_html(source_path)
    else:
        raw_text = _extract_pdf(source_path)

    text = normalize_text(raw_text)
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    doc_id_material = f"{source_path}:{content_hash}"
    document_id = sha256(doc_id_material.encode("utf-8")).hexdigest()
    mime_type = mimetypes.guess_type(str(source_path))[0] or "application/octet-stream"

    metadata: dict[str, str | int] = {
        "file_name": source_path.name,
        "file_suffix": source_path.suffix.lower(),
        "mime_type": mime_type,
        "byte_size": source_path.stat().st_size,
        "char_count": len(text),
        "line_count": text.count("\n") + (1 if text else 0),
        "content_hash": content_hash,
    }

    return ExtractedDocument(
        document_id=document_id,
        source_path=source_path,
        source_kind=source_kind,
        text=text,
        metadata=metadata,
    )


def extract_files(paths: list[Path]) -> list[ExtractedDocument]:
    return [extract_file(path) for path in paths]
