from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vecstash import daemon


class DaemonPreloadTests(unittest.TestCase):
    def _write_config(self, base: Path, preload: bool) -> Path:
        cfg = base / "config.toml"
        cfg.write_text(
            f"""
[app]
name = "vecstash"

[model]
name = "mlx-community/all-MiniLM-L6-v2-4bit"
cache_dir = "{(base / "models").as_posix()}"
preload_on_start = {str(preload).lower()}

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

    def test_preload_failure_exits_early(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(Path(tmp), preload=True)
            with patch("vecstash.daemon.validate_model_reference", return_value=(False, "fail")):
                code = daemon.main(["--config", str(cfg)])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
