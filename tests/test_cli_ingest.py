from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

from vecstash import cli


def _mock_embedder_class(config):
    """Return a mock Embedder that produces fake 16-dim vectors."""
    mock = MagicMock()
    mock.vector_size = 16
    mock.embed.side_effect = lambda texts: [[0.1] * 16 for _ in texts]
    return mock


class CliIngestTests(unittest.TestCase):
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

    @patch("vecstash.cli.Embedder", side_effect=_mock_embedder_class)
    def test_ingest_json_output(self, _mock_cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            txt = base / "sample.txt"
            txt.write_text("hello world", encoding="utf-8")
            out = StringIO()
            with patch("sys.stdout", out):
                code = cli.main(["--config", str(cfg), "ingest", str(txt), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue().strip())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["source_kind"], "txt")


if __name__ == "__main__":
    unittest.main()
