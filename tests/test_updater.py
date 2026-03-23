from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from vecstash.updater import (
    UpdateInfo,
    _parse_version,
    check_for_update,
    download_and_install,
)


class ParseVersionTests(unittest.TestCase):
    def test_simple_version(self) -> None:
        self.assertEqual(_parse_version("0.1.1"), (0, 1, 1))

    def test_major_version(self) -> None:
        self.assertEqual(_parse_version("2.0.0"), (2, 0, 0))

    def test_comparison(self) -> None:
        self.assertGreater(_parse_version("0.2.0"), _parse_version("0.1.9"))
        self.assertGreater(_parse_version("1.0.0"), _parse_version("0.99.99"))
        self.assertEqual(_parse_version("1.2.3"), _parse_version("1.2.3"))


class CheckForUpdateTests(unittest.TestCase):
    def _mock_response(self, data: dict) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = json.dumps(data).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("vecstash.updater.vecstash")
    @patch("vecstash.updater.urllib.request.urlopen")
    def test_update_available(self, mock_urlopen, mock_vecstash) -> None:
        mock_vecstash.__version__ = "0.1.0"
        mock_urlopen.return_value = self._mock_response({
            "tag_name": "v0.2.0",
            "tarball_url": "https://example.com/tarball",
            "html_url": "https://github.com/release/v0.2.0",
            "body": "Release notes",
        })

        info = check_for_update()
        self.assertTrue(info.update_available)
        self.assertEqual(info.current_version, "0.1.0")
        self.assertEqual(info.latest_version, "0.2.0")
        self.assertEqual(info.tarball_url, "https://example.com/tarball")

    @patch("vecstash.updater.vecstash")
    @patch("vecstash.updater.urllib.request.urlopen")
    def test_already_up_to_date(self, mock_urlopen, mock_vecstash) -> None:
        mock_vecstash.__version__ = "0.2.0"
        mock_urlopen.return_value = self._mock_response({
            "tag_name": "v0.2.0",
            "tarball_url": "https://example.com/tarball",
            "html_url": "https://github.com/release/v0.2.0",
            "body": "",
        })

        info = check_for_update()
        self.assertFalse(info.update_available)

    @patch("vecstash.updater.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen) -> None:
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        with self.assertRaises(RuntimeError) as ctx:
            check_for_update()
        self.assertIn("Cannot reach GitHub", str(ctx.exception))

    @patch("vecstash.updater.urllib.request.urlopen")
    def test_rate_limit(self, mock_urlopen) -> None:
        import urllib.error
        resp = MagicMock()
        resp.code = 403
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=403, msg="Forbidden", hdrs=None, fp=None
        )
        with self.assertRaises(RuntimeError) as ctx:
            check_for_update()
        self.assertIn("rate limit", str(ctx.exception))

    @patch("vecstash.updater.urllib.request.urlopen")
    def test_no_releases(self, mock_urlopen) -> None:
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs=None, fp=None
        )
        with self.assertRaises(RuntimeError) as ctx:
            check_for_update()
        self.assertIn("No releases found", str(ctx.exception))


class DownloadAndInstallTests(unittest.TestCase):
    def test_no_tarball_url_raises(self) -> None:
        info = UpdateInfo(
            current_version="0.1.0",
            latest_version="0.2.0",
            update_available=True,
            tarball_url=None,
            release_url=None,
            release_notes=None,
        )
        with self.assertRaises(RuntimeError) as ctx:
            download_and_install(info)
        self.assertIn("No tarball URL", str(ctx.exception))

    @patch("vecstash.updater.subprocess.run")
    @patch("vecstash.updater.tarfile.open")
    @patch("vecstash.updater.urllib.request.urlopen")
    def test_successful_install(self, mock_urlopen, mock_taropen, mock_run) -> None:
        # Mock the download
        resp = MagicMock()
        resp.read.return_value = b"fake tarball data"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        # Mock tarfile extraction — we need to create a real temp directory
        # with a subdirectory to simulate extraction
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as real_tmp:
            extracted_dir = Path(real_tmp) / "renatoadorno-vecstash-abc123"
            extracted_dir.mkdir()

            tar_mock = MagicMock()
            tar_mock.__enter__ = lambda s: s
            tar_mock.__exit__ = MagicMock(return_value=False)

            def fake_extractall(path, filter=None):
                # Create the extracted directory inside the actual tmpdir used
                import os
                for item in Path(path).iterdir():
                    if item.is_dir() and item.name != "__MACOSX":
                        return
                # Create a fake extracted dir
                fake_dir = Path(path) / "renatoadorno-vecstash-abc123"
                fake_dir.mkdir(exist_ok=True)

            tar_mock.extractall = fake_extractall
            mock_taropen.return_value = tar_mock
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            info = UpdateInfo(
                current_version="0.1.0",
                latest_version="0.2.0",
                update_available=True,
                tarball_url="https://example.com/tarball",
                release_url=None,
                release_notes=None,
            )
            download_and_install(info)

            # Verify uv tool install was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            self.assertEqual(call_args[1]["check"], True)
            cmd = call_args[0][0]
            self.assertEqual(cmd[0], "uv")
            self.assertEqual(cmd[1], "tool")
            self.assertEqual(cmd[2], "install")
            self.assertEqual(cmd[4], "--force")

    @patch("vecstash.updater.subprocess.run")
    @patch("vecstash.updater.tarfile.open")
    @patch("vecstash.updater.urllib.request.urlopen")
    def test_install_failure_raises(self, mock_urlopen, mock_taropen, mock_run) -> None:
        resp = MagicMock()
        resp.read.return_value = b"fake tarball data"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        tar_mock = MagicMock()
        tar_mock.__enter__ = lambda s: s
        tar_mock.__exit__ = MagicMock(return_value=False)

        def fake_extractall(path, filter=None):
            fake_dir = Path(path) / "renatoadorno-vecstash-abc123"
            fake_dir.mkdir(exist_ok=True)

        tar_mock.extractall = fake_extractall
        mock_taropen.return_value = tar_mock

        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["uv"], stderr="install error"
        )

        from pathlib import Path

        info = UpdateInfo(
            current_version="0.1.0",
            latest_version="0.2.0",
            update_available=True,
            tarball_url="https://example.com/tarball",
            release_url=None,
            release_notes=None,
        )
        with self.assertRaises(RuntimeError) as ctx:
            download_and_install(info)
        self.assertIn("Update failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
