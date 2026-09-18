from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vecstash.config import load_config
from vecstash.embedder import MLXEmbedder, SentenceTransformerEmbedder, create_embedder


class EmbedderFactoryTests(unittest.TestCase):
    def _write_config(self, base: Path, backend: str = "mlx", model_name: str = "test-model") -> Path:
        cfg = base / "config.toml"
        cfg.write_text(
            f"""
[app]
name = "vecstash"

[model]
name = "{model_name}"
backend = "{backend}"
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

    def test_factory_returns_mlx_embedder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp), backend="mlx")
            config = load_config(cfg)
            embedder = create_embedder(config)
            self.assertIsInstance(embedder, MLXEmbedder)

    def test_factory_returns_st_embedder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp), backend="sentence_transformers")
            config = load_config(cfg)
            embedder = create_embedder(config)
            self.assertIsInstance(embedder, SentenceTransformerEmbedder)

    def test_factory_raises_for_unknown_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp), backend="mlx")
            config = load_config(cfg)
            # Bypass config validation by directly setting backend
            object.__setattr__(config.model, "backend", "unknown")
            with self.assertRaises(ValueError):
                create_embedder(config)

    def test_st_embedder_raises_when_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp), backend="sentence_transformers", model_name="BAAI/bge-m3")
            config = load_config(cfg)
            embedder = create_embedder(config)
            with patch.dict("sys.modules", {"sentence_transformers": None}):
                with self.assertRaises(RuntimeError) as ctx:
                    embedder._load()
                self.assertIn("sentence-transformers not installed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
