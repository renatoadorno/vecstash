# Copilot Instructions for `vecstash`

## Build, test, and lint commands

This repository uses `uv` + `unittest` and currently has no dedicated lint target configured.

```bash
# Install dependencies
uv sync

# Optional MLX backend dependencies
uv sync --extra mlx

# Editable install for CLI/daemon entry points during development
make dev
```

```bash
# Run full test suite
make test
# or
uv run python -m unittest discover -s tests -p 'test_*.py'
```

```bash
# Run a single test file
uv run python -m unittest tests/test_extraction.py

# Run a single test case
uv run python -m unittest tests.test_cli_models.CliModelsTests.test_models_validate_json
```

## High-level architecture

`vecstash` has two entry points from `pyproject.toml`:

- `vecstash` → `vecstash.cli:main` (Typer CLI for one-shot commands)
- `vecstash-daemon` → `vecstash.daemon:main` (long-running JSON-RPC server on a Unix socket)

Core flow for ingest/search spans multiple modules:

1. `config.py` loads/validates `config.toml` into frozen dataclasses (`AppConfig`) and enforces path constraints.
2. `extraction.py` parses `.txt/.md/.html/.pdf`, normalizes text, and emits `ExtractedDocument`.
3. `chunking.py` splits text into paragraph chunks with deterministic chunk IDs.
4. `embedder.py` selects backend via `create_embedder(config)` (`sentence_transformers` or `mlx`) and embeds text.
5. `storage.py` coordinates:
   - SQLite (`documents`, `ingestion_jobs`, `chunk_index_state`, migrations)
   - embedded Qdrant collection for vectors/search
6. `cli.py` orchestrates user-facing commands (`ingest`, `search`, `status`, `storage`, `models`, `reset`, `update`).
7. `daemon.py` exposes status/health and scaffolded methods via newline-delimited JSON-RPC 2.0; JSON-RPC parsing/formatting helpers live in `rpc.py`.

Important runtime behavior:

- Models are expected to be bootstrapped into local cache (`vecstash models bootstrap`).
- Embedder loading is lazy.
- Switching embedding backend/model dimensions requires `vecstash reset` and re-ingesting documents.

## Key conventions in this codebase

- **Offline-first model loading at runtime:** both embedder implementations use local cache only (`local_files_only=True` / offline HF settings). If cache is missing, commands fail with an explicit bootstrap message.
- **Backend is config-driven:** `model.backend` in config selects embedder; only `"sentence_transformers"` and `"mlx"` are valid.
- **Dimension mismatch is a hard guard:** storage checks existing Qdrant vector size and raises a user-facing error instructing `vecstash reset` when model dimensions change.
- **CLI output pattern:** many commands support `--json`; when enabled, emit machine-readable JSON and skip Rich tables/panels.
- **Ingest resilience:** CLI ingest saves metadata first, then attempts embedding/chunk upsert; embedding failures are logged and surfaced as warnings rather than crashing the whole ingest batch.
- **Daemon protocol is line-oriented JSON-RPC 2.0:** one JSON request per newline on Unix socket; this is required for client interoperability.
- **Logging is structured JSON:** configured once via `configure_logging()`, writing JSON lines with `event`/`command`-style fields to `~/.vecstash/vecstash.log`.
- **Testing style:** tests use `unittest` + `typer.testing.CliRunner`; CLI tests generally patch `vecstash.cli.create_embedder` (factory-level mocking) to avoid loading real models.
- **Version source of truth:** package version comes from `pyproject.toml`, surfaced via `importlib.metadata.version("vecstash")` in `src/vecstash/__init__.py`.
- **Scaffolded surfaces:** `reindex` and `doctor` exist in both CLI and daemon dispatch but currently return placeholders.
