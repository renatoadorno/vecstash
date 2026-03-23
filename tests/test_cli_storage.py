from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from vecstash.cli import app

runner = CliRunner()


class CliStorageTests(unittest.TestCase):
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

    def test_storage_json_with_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)

            # Create fake DB files
            data_dir = base / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            sqlite_file = data_dir / "metadata.db"
            sqlite_file.write_bytes(b"x" * 1024)

            qdrant_dir = data_dir / "qdrant"
            qdrant_dir.mkdir()
            (qdrant_dir / "segment.dat").write_bytes(b"y" * 2048)

            result = runner.invoke(app, ["--config", str(cfg), "storage", "--json"])
            self.assertEqual(result.exit_code, 0)
            payload = json.loads(result.output.strip())
            self.assertEqual(payload["sqlite_bytes"], 1024)
            self.assertEqual(payload["qdrant_bytes"], 2048)
            self.assertEqual(payload["total_bytes"], 3072)

    def test_storage_json_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            (base / "data").mkdir(parents=True, exist_ok=True)

            result = runner.invoke(app, ["--config", str(cfg), "storage", "--json"])
            self.assertEqual(result.exit_code, 0)
            payload = json.loads(result.output.strip())
            self.assertEqual(payload["sqlite_bytes"], 0)
            self.assertEqual(payload["qdrant_bytes"], 0)
            self.assertEqual(payload["total_bytes"], 0)

    def test_storage_rich_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            (base / "data").mkdir(parents=True, exist_ok=True)

            result = runner.invoke(app, ["--config", str(cfg), "storage"])
            self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
