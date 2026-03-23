from __future__ import annotations

import json
import unittest

from typer.testing import CliRunner

import vecstash
from vecstash.cli import app

runner = CliRunner()


class CliVersionTests(unittest.TestCase):
    def test_version_output(self) -> None:
        result = runner.invoke(app, ["version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(vecstash.__version__, result.output)

    def test_version_json(self) -> None:
        result = runner.invoke(app, ["version", "--json"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.output.strip())
        self.assertEqual(payload["version"], vecstash.__version__)


if __name__ == "__main__":
    unittest.main()
