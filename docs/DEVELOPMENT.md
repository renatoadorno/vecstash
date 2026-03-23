# vecstash — Development Guide

This guide covers setting up a local development environment, running tests, and understanding the codebase.

---

## Prerequisites

- **macOS on Apple Silicon** (M1/M2/M3/M4) — MPS GPU acceleration requires arm64.
- **Python 3.12+** — pinned via `.python-version`.
- **uv** — install from [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) or `brew install uv`.

---

## Setup

```bash
# Clone the repo
git clone <repo-url> && cd vecstash

# Install dependencies in a local venv
uv sync

# Install with MLX backend (optional)
uv sync --extra mlx

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
uv run python -m unittest tests.test_cli_models.CliModelsTests.test_models_validate_json
```

Tests use `unittest` with no external test runner required. The test suite covers config loading (including backend parsing), text extraction, storage (SQLite + Qdrant + dimension guard), CLI commands, embedder factory, and daemon preload behaviour.

Tests mock `create_embedder` (not the model classes directly) to avoid loading real models.

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
| `config.py` | `AppConfig` dataclass (frozen), TOML loading, `ModelConfig.backend` field (`"sentence_transformers"` / `"mlx"`), backend-aware `validate_model_reference()` |
| `embedder.py` | Multi-backend: `MLXEmbedder`, `SentenceTransformerEmbedder`, `create_embedder()` factory. Lazy loading, `local_files_only=True` at runtime |
| `extraction.py` | Text extraction from `.txt`, `.md`, `.html`, `.pdf` into `ExtractedDocument`; content hashing; text normalization |
| `storage.py` | `StorageManager` owns `SQLiteRepository` (metadata + schema migrations) and `QdrantRepository` (vector collection); vector dimension mismatch guard |
| `daemon.py` | `JsonRpcServer` on a Unix socket; dispatches JSON-RPC 2.0 methods via `JsonRpcHandler` |
| `rpc.py` | Pure JSON-RPC 2.0 helpers: parse requests, format results/errors |
| `logging_utils.py` | JSON-structured file logging; extra fields: `command`, `event`, `method`, `client` |
| `cli.py` | Typer + Rich CLI: `version`, `status`, `storage`, `models`, `ingest`, `search`, `update`, `reset`, `reindex`, `doctor` |

### Embedding backends

The default backend is `sentence_transformers` using `BAAI/bge-m3` (1024-dim, MPS GPU). The `mlx` backend is available as an optional extra (`pip install vecstash[mlx]`).

The `create_embedder(config)` factory reads `config.model.backend` and returns the appropriate embedder class. Both backends implement the same interface: `vector_size` property and `embed(texts)` method.

### Scaffolded commands

`reindex` and `doctor` (CLI and RPC) are defined but return placeholder responses — not yet implemented.

---

## Custom Config

Pass `--config` to any command to use a non-default config file:

```bash
uv run vecstash --config /tmp/test-config.toml status
uv run vecstash-daemon --config /tmp/test-config.toml
```

Useful for running isolated test environments without touching `~/.vecstash`.
