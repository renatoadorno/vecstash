from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import vecstash

GITHUB_REPO = "renatoadorno/vecstash"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _parse_version(ver: str) -> tuple[int, ...]:
    """Parse a version string like '0.1.1' into a comparable tuple."""
    return tuple(int(x) for x in ver.split("."))


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    update_available: bool
    tarball_url: str | None
    release_url: str | None
    release_notes: str | None


def check_for_update() -> UpdateInfo:
    """Check GitHub Releases for a newer version of vecstash."""
    current = vecstash.__version__

    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError("No releases found for vecstash.") from e
        if e.code == 403:
            raise RuntimeError(
                "GitHub API rate limit exceeded. Try again later."
            ) from e
        raise RuntimeError(f"GitHub API error: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            "Cannot reach GitHub. Check your internet connection."
        ) from e

    tag = data.get("tag_name", "")
    latest = tag.lstrip("v")
    tarball_url = data.get("tarball_url")
    release_url = data.get("html_url")
    release_notes = data.get("body")

    try:
        update_available = _parse_version(latest) > _parse_version(current)
    except (ValueError, TypeError):
        update_available = False

    return UpdateInfo(
        current_version=current,
        latest_version=latest,
        update_available=update_available,
        tarball_url=tarball_url,
        release_url=release_url,
        release_notes=release_notes,
    )


def download_and_install(info: UpdateInfo) -> None:
    """Download the release tarball and install via uv tool install."""
    if not info.tarball_url:
        raise RuntimeError("No tarball URL available for this release.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tarball_path = Path(tmpdir) / "vecstash.tar.gz"

        req = urllib.request.Request(
            info.tarball_url,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            tarball_path.write_bytes(resp.read())

        with tarfile.open(tarball_path, "r:gz") as tar:
            tar.extractall(path=tmpdir, filter="data")

        # GitHub tarballs extract to a single directory like owner-repo-sha/
        extracted_dirs = [
            p for p in Path(tmpdir).iterdir()
            if p.is_dir() and p.name != "__MACOSX"
        ]
        if len(extracted_dirs) != 1:
            raise RuntimeError(
                f"Expected one extracted directory, found {len(extracted_dirs)}."
            )

        try:
            subprocess.run(
                ["uv", "tool", "install", str(extracted_dirs[0]), "--force"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Update failed. Your current version is still installed.\n{e.stderr}"
            ) from e
