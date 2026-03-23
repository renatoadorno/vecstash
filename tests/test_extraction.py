from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from vecstash.extraction import (
    _linearize_html_tables,
    _linearize_md_tables,
    extract_file,
    normalize_text,
)

from bs4 import BeautifulSoup


class ExtractionTests(unittest.TestCase):
    def test_normalize_text_collapse_whitespace(self) -> None:
        raw = "a\t\tb\r\n\r\n\r\n c "
        self.assertEqual(normalize_text(raw), "a b\n\nc")

    def test_extract_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text("hello   world\n\n\nline2", encoding="utf-8")
            doc = extract_file(path)
            self.assertEqual(doc.source_kind, "txt")
            self.assertEqual(doc.text, "hello world\n\nline2")
            self.assertEqual(doc.metadata["file_suffix"], ".txt")

    def test_extract_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.md"
            path.write_text("# Title\n\nThis is **bold**.", encoding="utf-8")
            doc = extract_file(path)
            self.assertEqual(doc.source_kind, "md")
            self.assertIn("Title", doc.text)
            self.assertIn("This is", doc.text)

    def test_extract_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.html"
            path.write_text(
                "<html><head><style>.x{}</style></head><body><h1>A</h1><script>1</script><p>B</p></body></html>",
                encoding="utf-8",
            )
            doc = extract_file(path)
            self.assertEqual(doc.source_kind, "html")
            self.assertIn("A", doc.text)
            self.assertIn("B", doc.text)
            self.assertNotIn("script", doc.text.lower())

    def test_extract_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with path.open("wb") as f:
                writer.write(f)
            doc = extract_file(path)
            self.assertEqual(doc.source_kind, "pdf")
            self.assertIsInstance(doc.text, str)

    def test_unsupported_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            path.write_text("a,b,c", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_file(path)


class LinearizeMdTablesTests(unittest.TestCase):
    def test_two_columns(self) -> None:
        md = "| Command | Description |\n|---------|-------------|\n| :q | Quit |\n| :w | Save |"
        result = _linearize_md_tables(md)
        self.assertEqual(result, ":q: Quit\n:w: Save")

    def test_multi_columns(self) -> None:
        md = "| Name | Age | City |\n|------|-----|------|\n| Alice | 30 | SP |\n| Bob | 25 | RJ |"
        result = _linearize_md_tables(md)
        self.assertEqual(result, "Name: Alice, Age: 30, City: SP\nName: Bob, Age: 25, City: RJ")

    def test_no_tables(self) -> None:
        md = "Just regular text\n\nWith paragraphs."
        result = _linearize_md_tables(md)
        self.assertEqual(result, md)

    def test_strips_backticks_from_cells(self) -> None:
        md = "| Cmd | Desc |\n|-----|------|\n| `:q` | Quit |\n| `:w` | Save |"
        result = _linearize_md_tables(md)
        self.assertEqual(result, ":q: Quit\n:w: Save")
        self.assertNotIn("`", result)

    def test_strips_bold_from_cells(self) -> None:
        md = "| Key | Val |\n|-----|-----|\n| **a** | one |"
        result = _linearize_md_tables(md)
        self.assertEqual(result, "a: one")

    def test_table_with_surrounding_text(self) -> None:
        md = "Before\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter"
        result = _linearize_md_tables(md)
        self.assertIn("1: 2", result)
        self.assertIn("Before", result)
        self.assertIn("After", result)


class LinearizeHtmlTablesTests(unittest.TestCase):
    def test_two_columns_with_th(self) -> None:
        html = "<table><tr><th>Key</th><th>Value</th></tr><tr><td>:q</td><td>Quit</td></tr><tr><td>:w</td><td>Save</td></tr></table>"
        soup = BeautifulSoup(html, "html.parser")
        _linearize_html_tables(soup)
        text = soup.get_text()
        self.assertIn(":q: Quit", text)
        self.assertIn(":w: Save", text)

    def test_multi_columns_with_th(self) -> None:
        html = "<table><tr><th>Name</th><th>Age</th><th>City</th></tr><tr><td>Alice</td><td>30</td><td>SP</td></tr></table>"
        soup = BeautifulSoup(html, "html.parser")
        _linearize_html_tables(soup)
        text = soup.get_text()
        self.assertIn("Name: Alice, Age: 30, City: SP", text)

    def test_table_without_th(self) -> None:
        html = "<table><tr><td>Key</td><td>Value</td></tr><tr><td>a</td><td>1</td></tr></table>"
        soup = BeautifulSoup(html, "html.parser")
        _linearize_html_tables(soup)
        text = soup.get_text()
        self.assertIn("a: 1", text)


class NormalizeSeparatorTests(unittest.TestCase):
    def test_removes_separator_lines(self) -> None:
        raw = "hello\n|---|---|\nworld"
        result = normalize_text(raw)
        self.assertEqual(result, "hello\nworld")

    def test_removes_dashes_only_line(self) -> None:
        raw = "hello\n-----------\nworld"
        result = normalize_text(raw)
        self.assertEqual(result, "hello\nworld")

    def test_preserves_real_content_with_pipes(self) -> None:
        raw = "a | b | c"
        result = normalize_text(raw)
        self.assertEqual(result, "a | b | c")


class ExtractMdWithTablesTests(unittest.TestCase):
    def test_md_table_becomes_linear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.md"
            path.write_text(
                "# Guide\n\n| Cmd | Desc |\n|-----|------|\n| :q | Quit |\n| :w | Save |\n\nEnd.",
                encoding="utf-8",
            )
            doc = extract_file(path)
            self.assertIn(":q: Quit", doc.text)
            self.assertIn(":w: Save", doc.text)
            self.assertNotIn("|---|", doc.text)


class ExtractHtmlWithTablesTests(unittest.TestCase):
    def test_html_table_becomes_linear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.html"
            path.write_text(
                "<html><body><p>Intro</p><table><tr><th>A</th><th>B</th></tr>"
                "<tr><td>1</td><td>2</td></tr></table><p>End</p></body></html>",
                encoding="utf-8",
            )
            doc = extract_file(path)
            self.assertIn("1: 2", doc.text)
            self.assertNotIn("<table>", doc.text)


if __name__ == "__main__":
    unittest.main()
