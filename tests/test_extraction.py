from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from vecstash.extraction import extract_file, normalize_text


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


if __name__ == "__main__":
    unittest.main()
