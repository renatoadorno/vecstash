from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from vecstash import cli


class CliModelsTests(unittest.TestCase):
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

    def test_models_validate_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp))
            out = StringIO()
            with (
                patch("vecstash.cli.validate_model_reference", return_value=(True, "ok")),
                patch("sys.stdout", out),
            ):
                code = cli.main(["--config", str(cfg), "models", "validate", "--offline-only"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue().strip())
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["offline_only"])

    def test_models_bootstrap_failure_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp))
            out = StringIO()
            with (
                patch("vecstash.cli.validate_model_reference", return_value=(False, "missing")),
                patch("sys.stdout", out),
            ):
                code = cli.main(["--config", str(cfg), "models", "bootstrap", "--json"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
