# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`vecstash` is an offline semantic storage and search tool for macOS ARM (Apple Silicon). It uses MLX-based embedding models locally and stores vectors in Qdrant (embedded/local) with document metadata in SQLite.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run vecstash status
uv run vecstash models show
uv run vecstash models validate [--offline-only]
uv run vecstash models bootstrap [--json]
uv run vecstash ingest <file1> [file2...] [--json]
uv run vecstash search "query text" [--limit N] [--json]
uv run vecstash update [--check] [--json]

# Run the background daemon (Unix socket JSON-RPC server)
uv run vecstash-daemon [--config PATH]

# Pass a custom config file to any command
uv run vecstash --config /path/to/config.toml <command>

# Run tests
uv run python -m unittest discover -s tests -p 'test_*.py'
```

## Architecture

Two entry points are defined in `pyproject.toml`:
- `vecstash` → `vecstash.cli:main` — one-shot CLI commands
- `vecstash-daemon` → `vecstash.daemon:main` — long-running JSON-RPC daemon

### Module responsibilities

| Module | Role |
|---|---|
| `cli.py` | Typer + Rich CLI: `app = typer.Typer()`, `models_app` sub-group, `Console(stderr=True)` for styled output, `Table` for status/ingest, `Panel(Markdown(...))` for search results, `--json` bypasses Rich |
| `config.py` | `AppConfig` dataclass (frozen), TOML loading from `~/.vecstash/config.toml`, HuggingFace model resolution via `mlx_embeddings` |
| `extraction.py` | Text extraction from `.txt`, `.md`, `.html`, `.pdf` files into `ExtractedDocument`; content hashing; text normalization |
| `chunking.py` | Paragraph-level document chunking (`\n\n+` split, min 50 chars); `Chunk` dataclass with deterministic `chunk_id` (sha256) |
| `embedder.py` | `Embedder` class: lazy-loading MLX model wrapper; batch embedding; `vector_size` property from `model.config.hidden_size` |
| `storage.py` | `StorageManager` owns both `SQLiteRepository` (document metadata + schema migrations) and `QdrantRepository` (vector collection via embedded Qdrant); `SearchResult` dataclass; chunk upsert and vector search |
| `updater.py` | Self-update via GitHub Releases API: `check_for_update()` compares versions, `download_and_install()` downloads tarball and runs `uv tool install` |
| `daemon.py` | `JsonRpcServer` on a Unix socket (`daemon.sock`); dispatches JSON-RPC 2.0 methods via `JsonRpcHandler` |
| `rpc.py` | Pure JSON-RPC 2.0 helpers: parse request lines, format result/error responses |
| `logging_utils.py` | JSON-structured file logging to `vecstash.log`; extra fields: `command`, `event`, `method`, `client` |

### Data flow

1. **Ingest**: `cli.py` calls `extraction.extract_files()` → `ExtractedDocument` list → `StorageManager.upsert_document_metadata()` to SQLite → `chunk_document()` splits into paragraphs → `Embedder.embed()` generates vectors → `StorageManager.upsert_chunks()` stores in Qdrant + SQLite.
2. **Search**: `cli.py` embeds query via `Embedder.embed()` → `StorageManager.search()` queries Qdrant with cosine similarity → returns `SearchResult` list displayed as Rich Panels with Markdown rendering (tables, headers, lists rendered natively).
3. **Update**: `cli.py` calls `check_for_update()` → GitHub API `/releases/latest` → compares semver → if newer, `download_and_install()` downloads tarball → extracts → `uv tool install --force`.
4. **Daemon**: `daemon.py` boots, optionally preloads the MLX model, creates the Unix socket, and loops on `socketserver.UnixStreamServer`. Clients send newline-delimited JSON-RPC 2.0 messages.
5. **Config**: `load_config()` auto-creates `~/.vecstash/config.toml` on first run if missing. All paths must be within `paths.data_dir` (enforced at parse time).

### Version management

Single source of truth: `version` field in `pyproject.toml`. Read at runtime via `importlib.metadata.version("vecstash")` in `__init__.py`.

### Storage layout (default `~/.vecstash/`)

```
~/.vecstash/
  config.toml       # TOML config
  metadata.db       # SQLite: documents, ingestion_jobs, chunk_index_state
  qdrant/           # Embedded Qdrant vector DB
  models/           # HuggingFace model cache (HF_HOME override)
  daemon.sock       # Unix domain socket (runtime only, mode 0o600)
  vecstash.log
```

### CI/CD

- `.github/workflows/test.yml` — runs tests on every push/PR to `main` (macos-latest runner)
- `.github/workflows/release.yml` — on tag `v*` push, runs tests then creates GitHub Release with auto-generated changelog

Release workflow: bump version in `pyproject.toml` → commit → `git tag v0.x.x && git push && git push --tags`

### Scaffolded commands (not yet implemented)

`reindex`, `doctor` on the CLI and the corresponding RPC methods return placeholder responses.

## Configuration

Config sections: `[app]`, `[model]`, `[paths]`, `[runtime]`.

Default model: `mlx-community/nomicai-modernbert-embed-base-bf16` (ModernBERT, bf16, 768-dim, L2-normalized).

Supported MLX embedding architectures: XLM-RoBERTa, BERT, ModernBERT, Qwen3, Qwen3-VL.

Model resolution: if `model.name` is a local path that exists, it is used directly; otherwise `snapshot_download` fetches from HuggingFace into `model.cache_dir/hub/`.

## Known workarounds

- `mlx_embeddings.TokenizerWrapper` doesn't implement `__call__` — `Embedder` accesses `processor._tokenizer` directly for batch encoding.
- `mlx_embeddings.generate()` fails with newer `transformers` (`TokenizersBackend` missing `batch_encode_plus`) — `Embedder` calls `model(**inputs)` directly instead.
- `qdrant-client` v1.17+ removed `search()` — use `query_points()` with `.points` on response.
