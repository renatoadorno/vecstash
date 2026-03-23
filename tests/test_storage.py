from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vecstash.config import load_config
from vecstash.extraction import extract_file
from vecstash.storage import StorageManager


class StorageTests(unittest.TestCase):
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

    def test_initialize_and_document_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            config = load_config(cfg)

            src = base / "note.txt"
            src.write_text("hello storage", encoding="utf-8")
            doc = extract_file(src)

            storage = StorageManager(config)
            status = storage.initialize(vector_size=16)
            self.assertGreaterEqual(status.schema_version, 1)
            self.assertEqual(status.points_count, 0)
            self.assertEqual(status.documents_count, 0)

            storage.upsert_document_metadata(doc)
            loaded = storage.get_document_metadata(doc.document_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["source_kind"], "txt")
            self.assertEqual(loaded["content_hash"], doc.metadata["content_hash"])
            storage.close()


if __name__ == "__main__":
    unittest.main()
