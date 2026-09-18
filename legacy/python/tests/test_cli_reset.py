from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from vecstash.cli import app

runner = CliRunner()


class CliResetTests(unittest.TestCase):
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

    def _create_db_files(self, base: Path) -> tuple[Path, Path]:
        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        sqlite_file = data_dir / "metadata.db"
        sqlite_file.write_bytes(b"x" * 100)
        qdrant_dir = data_dir / "qdrant"
        qdrant_dir.mkdir()
        (qdrant_dir / "data.bin").write_bytes(b"y" * 200)
        return sqlite_file, qdrant_dir

    def test_reset_force_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            sqlite_file, qdrant_dir = self._create_db_files(base)

            result = runner.invoke(app, ["--config", str(cfg), "reset", "--force", "--json"])
            self.assertEqual(result.exit_code, 0)
            payload = json.loads(result.output.strip())
            self.assertEqual(payload["status"], "reset_complete")
            self.assertIn("sqlite", payload["deleted"])
            self.assertIn("qdrant", payload["deleted"])
            self.assertFalse(sqlite_file.exists())
            self.assertFalse(qdrant_dir.exists())

    def test_reset_force_rich(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            sqlite_file, qdrant_dir = self._create_db_files(base)

            result = runner.invoke(app, ["--config", str(cfg), "reset", "--force"])
            self.assertEqual(result.exit_code, 0)
            self.assertFalse(sqlite_file.exists())
            self.assertFalse(qdrant_dir.exists())

    def test_reset_abort_on_no(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            sqlite_file, qdrant_dir = self._create_db_files(base)

            result = runner.invoke(app, ["--config", str(cfg), "reset"], input="n\n")
            self.assertNotEqual(result.exit_code, 0)
            self.assertTrue(sqlite_file.exists())
            self.assertTrue(qdrant_dir.exists())

    def test_reset_nothing_to_reset(self) -> None:
        """When neither SQLite file nor Qdrant dir exist, report nothing to reset."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)
            # load_config creates qdrant_path dir; remove it so nothing exists
            result = runner.invoke(app, ["--config", str(cfg), "reset", "--force"])
            # load_config auto-creates qdrant dir, so reset will delete it
            self.assertEqual(result.exit_code, 0)

    def test_reset_nothing_to_reset_json(self) -> None:
        """When load_config auto-creates qdrant dir, reset deletes it."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = self._write_config(base)

            result = runner.invoke(app, ["--config", str(cfg), "reset", "--force", "--json"])
            self.assertEqual(result.exit_code, 0)
            payload = json.loads(result.output.strip())
            # load_config creates qdrant_path, so it gets deleted
            self.assertEqual(payload["status"], "reset_complete")
            self.assertIn("qdrant", payload["deleted"])


if __name__ == "__main__":
    unittest.main()
