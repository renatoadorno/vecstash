from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vecstash.config import (
    load_config,
    render_default_config_toml,
)


class ConfigTests(unittest.TestCase):
    def test_default_config_render_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(render_default_config_toml(), encoding="utf-8")
            loaded = load_config(cfg)
            self.assertTrue(loaded.model.name)
            self.assertTrue(loaded.paths.data_dir.exists())
            self.assertGreater(loaded.runtime.max_batch_size, 0)
            self.assertEqual(loaded.model.backend, "sentence_transformers")

    def test_backend_defaults_to_sentence_transformers(self) -> None:
        """Config without backend field defaults to sentence_transformers."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(render_default_config_toml(), encoding="utf-8")
            loaded = load_config(cfg)
            self.assertEqual(loaded.model.backend, "sentence_transformers")

    def test_backend_sentence_transformers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = base / "config.toml"
            cfg.write_text(
                f"""
[app]
name = "vecstash"

[model]
name = "BAAI/bge-m3"
backend = "sentence_transformers"
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
            loaded = load_config(cfg)
            self.assertEqual(loaded.model.backend, "sentence_transformers")
            self.assertEqual(loaded.model.name, "BAAI/bge-m3")

    def test_invalid_backend_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = base / "config.toml"
            cfg.write_text(
                f"""
[app]
name = "vecstash"

[model]
name = "some-model"
backend = "invalid_backend"
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
            with self.assertRaises(ValueError):
                load_config(cfg)

    def test_invalid_runtime_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(
                """
[app]
name = "vecstash"

[model]
name = "mlx-community/all-MiniLM-L6-v2-4bit"
cache_dir = "/tmp/vecstash-models"
preload_on_start = false

[paths]
data_dir = "/tmp/vecstash-data"
sqlite_path = "/tmp/vecstash-data/metadata.db"
qdrant_path = "/tmp/vecstash-data/qdrant"
socket_path = "/tmp/vecstash-data/daemon.sock"
log_path = "/tmp/vecstash-data/vecstash.log"

[runtime]
max_batch_size = 0
max_concurrency = 4
query_cache_size = 128
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(cfg)


if __name__ == "__main__":
    unittest.main()
