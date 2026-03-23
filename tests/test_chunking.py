from __future__ import annotations

import unittest
from pathlib import Path

from vecstash.chunking import Chunk, chunk_document
from vecstash.extraction import ExtractedDocument


def _make_doc(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        document_id="abc123",
        source_path=Path("/tmp/test.txt"),
        source_kind="txt",
        text=text,
        metadata={
            "file_name": "test.txt",
            "file_suffix": ".txt",
            "mime_type": "text/plain",
            "byte_size": len(text.encode()),
            "char_count": len(text),
            "line_count": text.count("\n") + 1,
            "content_hash": "fakehash",
        },
    )


class ChunkDocumentTests(unittest.TestCase):
    def test_splits_on_double_newline(self) -> None:
        doc = _make_doc(
            "First paragraph with more than enough characters to comfortably pass the minimum character filter threshold.\n\n"
            "Second paragraph also has more than enough characters to comfortably pass the minimum character filter threshold."
        )
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 2)
        self.assertIn("First paragraph", chunks[0].text)
        self.assertIn("Second paragraph", chunks[1].text)

    def test_filters_short_paragraphs(self) -> None:
        doc = _make_doc("Short\n\nThis paragraph is long enough to pass the minimum character filter easily and comfortably exceeds the threshold.")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 1)
        self.assertIn("long enough", chunks[0].text)

    def test_empty_text_returns_no_chunks(self) -> None:
        doc = _make_doc("")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 0)

    def test_all_short_paragraphs_returns_empty(self) -> None:
        doc = _make_doc("tiny\n\nsmall\n\nbrief")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 0)

    def test_chunk_index_is_sequential(self) -> None:
        doc = _make_doc(
            "Short\n\n"
            "First real paragraph with plenty of characters for the filter and enough to exceed the minimum threshold.\n\n"
            "Also short\n\n"
            "Second real paragraph also has enough characters to pass the filter and exceed the minimum threshold."
        )
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[1].chunk_index, 1)

    def test_chunk_ids_are_unique(self) -> None:
        doc = _make_doc(
            "Paragraph one has enough text to pass the character filter.\n\n"
            "Paragraph two also has enough text to pass the character filter."
        )
        chunks = chunk_document(doc)
        ids = [c.chunk_id for c in chunks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_chunk_document_id_matches_source(self) -> None:
        doc = _make_doc("Long enough paragraph to pass the minimum character limit for chunking and comfortably exceed the threshold.")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].document_id, "abc123")

    def test_custom_min_chars(self) -> None:
        doc = _make_doc("Short text\n\nAnother short one")
        chunks_default = chunk_document(doc)
        chunks_small = chunk_document(doc, min_chars=5)
        self.assertEqual(len(chunks_default), 0)
        self.assertEqual(len(chunks_small), 2)


if __name__ == "__main__":
    unittest.main()
