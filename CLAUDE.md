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

# Run the background daemon (Unix socket JSON-RPC server)
uv run vecstash-daemon [--config PATH]

# Pass a custom config file to any command
uv run vecstash --config /path/to/config.toml <command>
```

## Architecture

Two entry points are defined in `pyproject.toml`:
- `vecstash` → `vecstash.cli:main` — one-shot CLI commands
- `vecstash-daemon` → `vecstash.daemon:main` — long-running JSON-RPC daemon

### Module responsibilities

| Module | Role |
|---|---|
| `config.py` | `AppConfig` dataclass (frozen), TOML loading from `~/.vecstash/config.toml`, HuggingFace model resolution via `mlx_embeddings` |
| `extraction.py` | Text extraction from `.txt`, `.md`, `.html`, `.pdf` files into `ExtractedDocument`; content hashing; text normalization |
| `storage.py` | `StorageManager` owns both `SQLiteRepository` (document metadata + schema migrations) and `QdrantRepository` (vector collection via embedded Qdrant) |
| `daemon.py` | `JsonRpcServer` on a Unix socket (`daemon.sock`); dispatches JSON-RPC 2.0 methods via `JsonRpcHandler` |
| `rpc.py` | Pure JSON-RPC 2.0 helpers: parse request lines, format result/error responses |
| `logging_utils.py` | JSON-structured file logging to `vecstash.log`; extra fields: `command`, `event`, `method`, `client` |

### Data flow

1. **Ingest**: `cli.py` calls `extraction.extract_files()` → produces `ExtractedDocument` list → `StorageManager.upsert_document_metadata()` writes to SQLite. Vector indexing is scaffolded but not yet implemented.
2. **Daemon**: `daemon.py` boots, optionally preloads the MLX model, creates the Unix socket, and loops on `socketserver.UnixStreamServer`. Clients send newline-delimited JSON-RPC 2.0 messages.
3. **Config**: `load_config()` auto-creates `~/.vecstash/config.toml` on first run if missing. All paths must be within `paths.data_dir` (enforced at parse time).

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

### Scaffolded commands (not yet implemented)

`search`, `reindex`, `doctor` on the CLI and the corresponding RPC methods return placeholder responses.

## Configuration

Config sections: `[app]`, `[model]`, `[paths]`, `[runtime]`.

Default model: `mlx-community/nomicai-modernbert-embed-base-bf16` (ModernBERT, bf16).

Supported MLX embedding architectures: XLM-RoBERTa, BERT, ModernBERT, Qwen3, Qwen3-VL.

Model resolution: if `model.name` is a local path that exists, it is used directly; otherwise `snapshot_download` fetches from HuggingFace into `model.cache_dir/hub/`.
