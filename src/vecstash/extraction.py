from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import mimetypes
from pathlib import Path
import re
import unicodedata

from bs4 import BeautifulSoup, NavigableString
from markdown_it import MarkdownIt
import pymupdf

_WS_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MD_TABLE_BLOCK_RE = re.compile(r"(?:^[ \t]*\|.+\|[ \t]*$\n?)+", re.MULTILINE)
_MD_SEPARATOR_LINE_RE = re.compile(r"^[ \t]*\|[\s:|-]+\|[ \t]*$")
_SEPARATOR_LINE_RE = re.compile(r"^[-|:=][-|:=\s]+$")
_MD_INLINE_RE = re.compile(r"`([^`]+)`")
_MD_BOLD_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")

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


def _strip_md_inline(text: str) -> str:
    """Strip markdown inline formatting for clean embedding text."""
    text = _MD_INLINE_RE.sub(r"\1", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    return text


def _parse_md_row(line: str) -> list[str]:
    """Split a markdown table row into cells."""
    return [_strip_md_inline(cell.strip()) for cell in line.strip().strip("|").split("|")]


def _linearize_md_tables(raw: str) -> str:
    """Convert markdown tables to linear text before HTML rendering."""

    def _replace_table(match: re.Match) -> str:
        block = match.group(0)
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        non_sep = [ln for ln in lines if not _MD_SEPARATOR_LINE_RE.match(ln)]
        if len(non_sep) < 2:
            return block
        headers = _parse_md_row(non_sep[0])
        data_rows = [_parse_md_row(ln) for ln in non_sep[1:]]
        result_lines: list[str] = []
        for row in data_rows:
            if len(headers) == 2 and len(row) >= 2:
                result_lines.append(f"{row[0]}: {row[1]}")
            else:
                parts = []
                for i, cell in enumerate(row):
                    if i < len(headers):
                        parts.append(f"{headers[i]}: {cell}")
                    else:
                        parts.append(cell)
                result_lines.append(", ".join(parts))
        return "\n".join(result_lines)

    return _MD_TABLE_BLOCK_RE.sub(_replace_table, raw)


def _linearize_html_tables(soup: BeautifulSoup) -> None:
    """Replace <table> elements with linearized text in-place."""
    for table in soup.find_all("table"):
        headers: list[str] = []
        header_row = table.find("tr")
        if header_row:
            th_cells = header_row.find_all("th")
            if th_cells:
                headers = [th.get_text(strip=True) for th in th_cells]
            else:
                td_cells = header_row.find_all("td")
                headers = [td.get_text(strip=True) for td in td_cells]

        data_rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            if tr.find("th"):
                continue
            if not table.find("th") and tr == header_row:
                continue
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if cells:
                data_rows.append(cells)

        result_lines: list[str] = []
        for row in data_rows:
            if len(headers) == 2 and len(row) >= 2:
                result_lines.append(f"{row[0]}: {row[1]}")
            else:
                parts = []
                for i, cell in enumerate(row):
                    if i < len(headers):
                        parts.append(f"{headers[i]}: {cell}")
                    else:
                        parts.append(cell)
                result_lines.append(", ".join(parts))

        table.replace_with(NavigableString("\n".join(result_lines)))


def normalize_text(raw_text: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    previous_blank = False
    for line in normalized.split("\n"):
        compact = _WS_RE.sub(" ", line).strip()
        if compact:
            if _SEPARATOR_LINE_RE.match(compact):
                continue
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
    raw = _linearize_md_tables(raw)
    rendered_html = MarkdownIt("commonmark").render(raw)
    return _extract_html_from_text(rendered_html)

def extract_structured_html(soup):
    result = []

    for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        text = tag.get_text(strip=True)

        if not text:
            continue

        if tag.name == "h1":
            result.append(f"# {text}")
        elif tag.name == "h2":
            result.append(f"## {text}")
        elif tag.name == "h3":
            result.append(f"### {text}")
        elif tag.name == "li":
            result.append(f"- {text}")
        else:
            result.append(text)

    return "\n".join(result)

def _extract_html_from_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    _linearize_html_tables(soup)
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return extract_structured_html(soup)


def _extract_html(path: Path) -> str:
    return _extract_html_from_text(path.read_text(encoding="utf-8"))


def _extract_pdf(path: Path) -> str:
    doc = pymupdf.open(str(path))
    try:
        if doc.is_encrypted:
            raise ValueError(f"Encrypted PDF is not supported: {path}")

        page_texts: list[str] = []
        for page in doc:
            text = page.get_text("text")
            page_texts.append(text)

        return "\n\n".join(page_texts)
    finally:
        doc.close()


def _resolve_source_kind(path: Path) -> str:
    kind = SUPPORTED_SOURCE_KINDS.get(path.suffix.lower())
    if kind is None:
        supported = ", ".join(sorted(SUPPORTED_SOURCE_KINDS))
        raise ValueError(f"Unsupported file type for {path}. Supported suffixes: {supported}")
    return kind

def split_sections(text: str) -> list[str]:
    return re.split(r"\n#{1,3} ", text)

def ensure_sentence_spacing(text: str) -> str:
    return re.sub(r"(?<!\n)\n(?!\n)", ".\n\n", text)

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
    text = ensure_sentence_spacing(text)
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
