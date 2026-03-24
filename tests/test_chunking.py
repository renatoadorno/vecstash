from __future__ import annotations

import unittest
from pathlib import Path

from vecstash.chunking import chunk_document
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
    def test_long_text_is_split_into_multiple_chunks(self) -> None:
        doc = _make_doc(("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 40).strip())
        chunks = chunk_document(doc)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 300 for chunk in chunks))

    def test_short_text_is_preserved(self) -> None:
        doc = _make_doc("Short")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Short")

    def test_empty_text_returns_no_chunks(self) -> None:
        doc = _make_doc("")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 0)

    def test_all_short_paragraphs_returns_single_chunk(self) -> None:
        doc = _make_doc("tiny\n\nsmall\n\nbrief")
        chunks = chunk_document(doc)
        self.assertEqual(len(chunks), 1)
        self.assertIn("tiny", chunks[0].text)
        self.assertIn("small", chunks[0].text)
        self.assertIn("brief", chunks[0].text)

    def test_chunk_index_is_sequential(self) -> None:
        doc = _make_doc(("Chunk me into multiple segments while preserving order. " * 35).strip())
        chunks = chunk_document(doc)
        self.assertGreater(len(chunks), 1)
        self.assertEqual([chunk.chunk_index for chunk in chunks], list(range(len(chunks))))

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
        self.assertGreaterEqual(len(chunks), 1)
        self.assertTrue(all(chunk.document_id == "abc123" for chunk in chunks))

    def test_custom_min_chars(self) -> None:
        doc = _make_doc("Short text\n\nAnother short one")
        chunks_default = chunk_document(doc)
        chunks_small = chunk_document(doc, min_chars=5)
        self.assertEqual(len(chunks_default), len(chunks_small))
        self.assertEqual([chunk.text for chunk in chunks_default], [chunk.text for chunk in chunks_small])
        self.assertEqual([chunk.chunk_id for chunk in chunks_default], [chunk.chunk_id for chunk in chunks_small])


if __name__ == "__main__":
    unittest.main()
