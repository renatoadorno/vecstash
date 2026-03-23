# vecstash — Development Guide

This guide covers setting up a local development environment, running tests, and understanding the codebase.

---

## Prerequisites

- **macOS on Apple Silicon** (M1/M2/M3/M4) — MLX requires arm64.
- **Python 3.12+** — pinned via `.python-version`.
- **uv** — install from [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) or `brew install uv`.

---

## Setup

```bash
# Clone the repo
git clone <repo-url> && cd vecstash

# Install dependencies in a local venv
uv sync

# Install in editable mode (code changes take effect without reinstalling)
make dev
```

`make dev` runs `uv tool install -e . --force`, placing `vecstash` and `vecstash-daemon` on `PATH` via `~/.local/bin` while pointing directly at your source tree.

---

## Running Tests

```bash
# Run all tests
make test

# Run a single test file
uv run python -m unittest tests/test_extraction.py

# Run a single test case
uv run python -m unittest tests.test_cli_models.TestModelsValidate.test_validate_ok
```

Tests use `unittest` with no external test runner required. The test suite covers config loading, text extraction, storage (SQLite + Qdrant), CLI commands, and daemon preload behaviour.

---

## Running the Daemon Locally

```bash
# Start in foreground (Ctrl+C to stop)
make daemon

# Test it's responding
printf '{"jsonrpc":"2.0","id":1,"method":"healthcheck","params":{}}\n' | nc -U ~/.vecstash/daemon.sock
```

The daemon writes structured JSON logs to `~/.vecstash/vecstash.log`:

```bash
tail -f ~/.vecstash/vecstash.log
```

---

## Makefile Targets

| Target | What it does |
|--------|--------------|
| `install` | `uv tool install . --force` — installs release binaries |
| `dev` | `uv tool install -e . --force` — editable install |
| `uninstall` | Unregisters launchd, then `uv tool uninstall vecstash` |
| `test` | `uv run python -m unittest discover -s tests` |
| `bootstrap` | `vecstash models bootstrap` — downloads the embedding model |
| `status` | `vecstash status` |
| `daemon` | `vecstash-daemon` — run daemon in foreground |
| `daemon-stop` | Stops the launchd-managed daemon and removes the socket |
| `launchd-install` | Registers daemon as a macOS LaunchAgent |
| `launchd-uninstall` | Removes the LaunchAgent plist |
| `clean` | Removes `dist/`, `build/`, `__pycache__` |

---

## Code Structure

Source lives in `src/vecstash/`. Two entry points are defined in `pyproject.toml`:

- `vecstash` → `vecstash.cli:main`
- `vecstash-daemon` → `vecstash.daemon:main`

| Module | Role |
|--------|------|
| `config.py` | `AppConfig` dataclass (frozen), TOML loading from `~/.vecstash/config.toml`, HuggingFace model resolution via `mlx_embeddings` |
| `extraction.py` | Text extraction from `.txt`, `.md`, `.html`, `.pdf` into `ExtractedDocument`; content hashing; text normalization |
| `storage.py` | `StorageManager` owns `SQLiteRepository` (metadata + schema migrations) and `QdrantRepository` (vector collection via embedded Qdrant) |
| `daemon.py` | `JsonRpcServer` on a Unix socket; dispatches JSON-RPC 2.0 methods via `JsonRpcHandler` |
| `rpc.py` | Pure JSON-RPC 2.0 helpers: parse requests, format results/errors |
| `logging_utils.py` | JSON-structured file logging; extra fields: `command`, `event`, `method`, `client` |
| `cli.py` | CLI entry point with subcommands: `status`, `models`, `ingest`, `search`, `reindex`, `doctor` |

### Scaffolded commands

`search`, `reindex`, and `doctor` (CLI and RPC) are defined but return placeholder responses — not yet implemented.

---

## Custom Config

Pass `--config` to any command to use a non-default config file:

```bash
uv run vecstash --config /tmp/test-config.toml status
uv run vecstash-daemon --config /tmp/test-config.toml
```

Useful for running isolated test environments without touching `~/.vecstash`.
