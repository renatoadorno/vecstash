from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vecstash.chunking import Chunk
from vecstash.config import load_config
from vecstash.extraction import extract_file
from vecstash.storage import StorageManager, SearchResult, _chunk_point_id


class StorageChunkTests(unittest.TestCase):
    def _write_config(self, base: Path) -> Path:
        cfg = base / "config.toml"
        cfg.write_text(
            f"""
[app]
name = "vecstash"

[model]
name = "mlx-community/all-MiniLM-L6-v2-4bit"
cache_dir = "{(base / "models").as_posix()}"
preload_on_start = false

[paths]
data_dir = "{(base / "data").as_posix()}"
sqlite_path = "{(base / "data" / "metadata.db").as_posix()}"
qdrant_path = "{(base / "data" / "qdrant").as_posix()}"
socket_path = "{(base / "data" / "daemon.sock").as_posix()}"
log_path = "{(base / "data" / "vecstash.log").as_posix()}"

[runtime]
max_batch_size = 32
max_concurrency = 2
query_cache_size = 64
""".strip(),
            encoding="utf-8",
        )
        return cfg

    def test_upsert_and_search_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            config = load_config(cfg)

            src = base / "note.txt"
            src.write_text("hello storage test", encoding="utf-8")
            doc = extract_file(src)

            vector_size = 4
            chunks = [
                Chunk(chunk_id="chunk_a", document_id=doc.document_id, text="hello", chunk_index=0),
                Chunk(chunk_id="chunk_b", document_id=doc.document_id, text="world", chunk_index=1),
            ]
            embeddings = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]

            storage = StorageManager(config)
            storage.initialize(vector_size=vector_size)
            storage.upsert_document_metadata(doc)
            storage.upsert_chunks(doc, chunks, embeddings)

            status = storage.status()
            self.assertEqual(status.points_count, 2)

            results = storage.search([1.0, 0.0, 0.0, 0.0], top_k=1)
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], SearchResult)
            self.assertEqual(results[0].chunk_text, "hello")
            self.assertEqual(results[0].document_id, doc.document_id)

            storage.close()

    def test_upsert_chunks_replaces_old(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            config = load_config(cfg)

            src = base / "note.txt"
            src.write_text("hello storage test", encoding="utf-8")
            doc = extract_file(src)

            vector_size = 4
            storage = StorageManager(config)
            storage.initialize(vector_size=vector_size)
            storage.upsert_document_metadata(doc)

            chunks_v1 = [Chunk(chunk_id="c1", document_id=doc.document_id, text="old", chunk_index=0)]
            storage.upsert_chunks(doc, chunks_v1, [[1.0, 0.0, 0.0, 0.0]])
            self.assertEqual(storage.status().points_count, 1)

            chunks_v2 = [
                Chunk(chunk_id="c2", document_id=doc.document_id, text="new1", chunk_index=0),
                Chunk(chunk_id="c3", document_id=doc.document_id, text="new2", chunk_index=1),
            ]
            storage.upsert_chunks(doc, chunks_v2, [[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]])
            self.assertEqual(storage.status().points_count, 2)

            storage.close()

    def test_upsert_chunks_mismatched_lengths_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            config = load_config(cfg)

            src = base / "note.txt"
            src.write_text("hello", encoding="utf-8")
            doc = extract_file(src)

            storage = StorageManager(config)
            storage.initialize(vector_size=4)
            storage.upsert_document_metadata(doc)

            chunks = [Chunk(chunk_id="c1", document_id=doc.document_id, text="text", chunk_index=0)]
            with self.assertRaises(ValueError):
                storage.upsert_chunks(doc, chunks, [])

            storage.close()

    def test_delete_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            config = load_config(cfg)

            src = base / "note.txt"
            src.write_text("hello", encoding="utf-8")
            doc = extract_file(src)

            storage = StorageManager(config)
            storage.initialize(vector_size=4)
            storage.upsert_document_metadata(doc)

            chunks = [Chunk(chunk_id="c1", document_id=doc.document_id, text="text", chunk_index=0)]
            storage.upsert_chunks(doc, chunks, [[1.0, 0.0, 0.0, 0.0]])

            storage.sqlite.delete_chunks(doc.document_id)
            row = storage.sqlite._conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_index_state WHERE document_id = ?",
                (doc.document_id,),
            ).fetchone()
            self.assertEqual(row["n"], 0)

            storage.close()

    def test_chunk_point_id_is_deterministic(self) -> None:
        chunk = Chunk(chunk_id="test_id", document_id="doc1", text="hello", chunk_index=0)
        id1 = _chunk_point_id(chunk)
        id2 = _chunk_point_id(chunk)
        self.assertEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()
