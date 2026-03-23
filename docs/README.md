# vecstash Documentation

Offline semantic storage and search toolkit for macOS ARM (Apple Silicon).
Provides a CLI for one-shot operations and a background daemon exposing a JSON-RPC 2.0 API over a Unix socket.

---

## Prerequisites

- **macOS on Apple Silicon** (M1/M2/M3/M4) — MLX requires arm64.
- **Python 3.12+** — pinned via `.python-version`.
- **uv** — install from [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) or `brew install uv`.

The first run downloads the embedding model (~500 MB, one-time).

---

## Installation

### Quick install (recommended)

```bash
git clone <repo-url> && cd vecstash
./install.sh
```

This checks prerequisites, installs both binaries to `~/.local/bin`, downloads the model, and sets up launchd for automatic daemon startup.

### Manual install

```bash
# 1. Install binaries
uv tool install /path/to/vecstash

# 2. Download the embedding model for offline use
vecstash models bootstrap

# 3. Verify
vecstash status
```

### Editable install (development)

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full contributor setup, including editable install, running tests, and code structure.

### Uninstall

```bash
make uninstall
```

This stops the daemon, removes the launchd plist, and uninstalls the binaries.

---

## Configuration Reference

Configuration lives at `~/.vecstash/config.toml`. It is auto-created with defaults on first run.

### `[app]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | `"vecstash"` | Application identifier |

### `[model]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | `"mlx-community/nomicai-modernbert-embed-base-bf16"` | HuggingFace model ID or local filesystem path |
| `cache_dir` | path | `~/.vecstash/models` | Directory for downloaded model files |
| `preload_on_start` | bool | `false` | Load model into memory when the daemon starts |

If `name` is a local path that exists, it is used directly. Otherwise the model is fetched from HuggingFace via `snapshot_download` into `cache_dir/hub/`.

**Supported MLX embedding architectures:**

- XLM-RoBERTa
- BERT
- ModernBERT
- Qwen3
- Qwen3-VL

**Known good model IDs:**

- `mlx-community/nomicai-modernbert-embed-base-bf16`
- `mlx-community/all-MiniLM-L6-v2-4bit`
- `mlx-community/answerdotai-ModernBERT-base-4bit`
- `Qwen/Qwen3-Embedding-0.6B`
- `Qwen/Qwen3-Embedding-4B`

### `[paths]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `data_dir` | path | `~/.vecstash` | Root data directory |
| `sqlite_path` | path | `~/.vecstash/metadata.db` | SQLite database for document metadata |
| `qdrant_path` | path | `~/.vecstash/qdrant` | Qdrant local vector storage |
| `socket_path` | path | `~/.vecstash/daemon.sock` | Unix domain socket for the daemon |
| `log_path` | path | `~/.vecstash/vecstash.log` | Structured JSON log file |

**Validation rule:** `sqlite_path`, `qdrant_path`, and `log_path` must be inside `data_dir`.

### `[runtime]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_batch_size` | int | `64` | Maximum documents per embedding batch |
| `max_concurrency` | int | `4` | Maximum parallel operations |
| `query_cache_size` | int | `2048` | LRU cache entries for query results |

### Example config

```toml
[app]
name = "vecstash"

[model]
name = "mlx-community/nomicai-modernbert-embed-base-bf16"
cache_dir = "~/.vecstash/models"
preload_on_start = false

[paths]
data_dir = "~/.vecstash"
sqlite_path = "~/.vecstash/metadata.db"
qdrant_path = "~/.vecstash/qdrant"
socket_path = "~/.vecstash/daemon.sock"
log_path = "~/.vecstash/vecstash.log"

[runtime]
max_batch_size = 64
max_concurrency = 4
query_cache_size = 2048
```

---

## CLI Usage

All commands accept `--config PATH` to use a custom config file.

### `vecstash status [--json]`

Show configuration and storage status.

```bash
$ vecstash status
vecstash status
- app_name: vecstash
- model_name: mlx-community/nomicai-modernbert-embed-base-bf16
- data_dir: /Users/you/.vecstash
- schema_version: 1
- documents_count: 0
...

$ vecstash status --json
{"app_name": "vecstash", "model_name": "...", ...}
```

### `vecstash models show`

Display the configured model and supported architecture families.

```bash
$ vecstash models show
Configured model
- model.name: mlx-community/nomicai-modernbert-embed-base-bf16
- model.cache_dir: /Users/you/.vecstash/models
- model.preload_on_start: False
Supported architecture families (mlx_embeddings):
- XLM-RoBERTa
- BERT
- ModernBERT
...
```

### `vecstash models validate [--offline-only]`

Check if the configured model is available. With `--offline-only`, only checks the local cache (no network).

```bash
$ vecstash models validate --offline-only
{"model_name": "...", "ok": true, "detail": "model resolved from local cache"}
```

Exit code: `0` if valid, `2` if not.

### `vecstash models bootstrap [--json]`

Download and cache the configured model for offline use.

```bash
$ vecstash models bootstrap
bootstrap status: ok
- model: mlx-community/nomicai-modernbert-embed-base-bf16
- detail: model resolved (local cache and/or remote)
```

### `vecstash ingest <files...> [--json]`

Extract text from supported files (`.txt`, `.md`, `.html`, `.pdf`) and persist metadata to SQLite.

```bash
$ vecstash ingest report.pdf notes.md --json
[{"document_id": "abc123...", "source_path": "/path/to/report.pdf", "source_kind": "pdf", "metadata": {...}}, ...]

$ vecstash ingest report.pdf notes.md
Ingest extraction summary
- /path/to/report.pdf [pdf] -> id=abc123...
- /path/to/notes.md [md] -> id=def456...
```

### Scaffolded commands

`search`, `reindex`, and `doctor` are defined but not yet implemented. They return a placeholder message.

---

## Daemon Usage

The daemon is a long-running process that exposes the same operations as the CLI via JSON-RPC 2.0 over a Unix domain socket.

### Starting the daemon

**Via launchd (recommended):**

```bash
make launchd-install
```

The daemon starts on login and restarts automatically on crash.

**Manually (foreground):**

```bash
vecstash-daemon
# or
make daemon
```

**With a custom config:**

```bash
vecstash-daemon --config /path/to/config.toml
```

### Stopping the daemon

```bash
make daemon-stop
```

### Protocol

- **Transport:** Unix domain socket at `~/.vecstash/daemon.sock` (mode `0600`)
- **Format:** Newline-delimited JSON-RPC 2.0 (one JSON object per line, terminated with `\n`)
- **Multiplexing:** Stateless per line — you can send multiple requests without waiting, using the `id` field to correlate responses

### Available methods

| Method | Params | Response |
|--------|--------|----------|
| `healthcheck` | `{}` | `status`, `app_name`, `model`, `socket_path` |
| `status` | `{}` | `data_dir`, `sqlite_path`, `qdrant_path`, `schema_version`, collection stats |
| `ingest` | — | Scaffolded (placeholder) |
| `search` | — | Scaffolded (placeholder) |
| `models` | — | Scaffolded (placeholder) |
| `reindex` | — | Scaffolded (placeholder) |
| `doctor` | — | Scaffolded (placeholder) |

### Examples

**Shell (`nc`):**

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"healthcheck","params":{}}\n' | nc -U ~/.vecstash/daemon.sock
```

**Shell (`socat`):**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"status","params":{}}' | socat - UNIX-CONNECT:$HOME/.vecstash/daemon.sock
```

**Node.js:**

```js
const net = require('net');
const readline = require('readline');

const client = net.createConnection(
  `${process.env.HOME}/.vecstash/daemon.sock`,
  () => {
    client.write(JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'healthcheck',
      params: {},
    }) + '\n');
  }
);

const rl = readline.createInterface({ input: client });
rl.on('line', (line) => {
  console.log(JSON.parse(line));
  client.destroy();
});
```

**Python:**

```python
import json
import socket

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(str(Path.home() / ".vecstash/daemon.sock"))

request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "healthcheck", "params": {}})
sock.sendall((request + "\n").encode())

response = b""
while b"\n" not in response:
    response += sock.recv(4096)
print(json.loads(response.decode()))
sock.close()
```

---

## launchd Integration

The daemon can be managed as a macOS LaunchAgent for automatic startup and crash recovery.

### Install

```bash
make launchd-install
# or via the install script:
./install.sh
```

This copies the plist to `~/Library/LaunchAgents/com.vecstash.daemon.plist` and registers it with launchd.

### Behavior

- **RunAtLoad:** daemon starts when you log in.
- **KeepAlive (SuccessfulExit=false):** restarts on crash (non-zero exit). Does not restart after clean shutdown (e.g., Ctrl+C or `make daemon-stop`).
- **ThrottleInterval:** 5 seconds between restart attempts to prevent tight loops.

### Check status

```bash
launchctl list | grep vecstash
```

A running daemon shows a PID in the first column.

### View logs

```bash
# Structured JSON application log
tail -f ~/.vecstash/vecstash.log

# Daemon stdout/stderr (startup errors, crashes)
tail -f ~/.vecstash/daemon.stdout.log
tail -f ~/.vecstash/daemon.stderr.log
```

### Uninstall

```bash
make launchd-uninstall
```

---

## Architecture

### Modules

| Module | Role |
|--------|------|
| `config.py` | `AppConfig` dataclass (frozen), TOML loading, HuggingFace model resolution via `mlx_embeddings` |
| `extraction.py` | Text extraction from `.txt`, `.md`, `.html`, `.pdf` into `ExtractedDocument`; content hashing; text normalization |
| `storage.py` | `StorageManager` owns `SQLiteRepository` (metadata + schema migrations) and `QdrantRepository` (vector collection) |
| `daemon.py` | `JsonRpcServer` on a Unix socket; dispatches JSON-RPC 2.0 methods via `JsonRpcHandler` |
| `rpc.py` | Pure JSON-RPC 2.0 helpers: parse requests, format results/errors |
| `logging_utils.py` | JSON-structured file logging; extra fields: `command`, `event`, `method`, `client` |
| `cli.py` | CLI entry point with subcommands: `status`, `models`, `ingest`, `search`, `reindex`, `doctor` |

### Data flow

```
                    CLI (one-shot)                    Daemon (persistent)
                         │                                  │
                    ┌────▼────┐                        ┌────▼────┐
                    │  cli.py │                        │daemon.py│
                    └────┬────┘                        └────┬────┘
                         │                                  │
              ┌──────────┼──────────┐            ┌──────────┼──────────┐
              ▼          ▼          ▼            ▼          ▼          ▼
         config.py  extraction.py  storage.py  config.py   rpc.py   storage.py
              │          │          │    │                             │    │
              ▼          │     ┌────▼────▼───┐                   ┌────▼────▼───┐
         config.toml     │     │ SQLite  Qdrant│                  │ SQLite  Qdrant│
                         │     └─────────────┘                   └─────────────┘
                         ▼
                   .txt .md .html .pdf
```

### Storage layout

```
~/.vecstash/
├── config.toml              # TOML configuration
├── metadata.db              # SQLite: documents, ingestion_jobs, chunk_index_state
├── qdrant/                  # Embedded Qdrant vector DB
├── models/                  # HuggingFace model cache (HF_HOME override)
│   └── hub/                 # snapshot_download target
├── daemon.sock              # Unix domain socket (runtime only, mode 0600)
├── vecstash.log       # Structured JSON application log
├── daemon.stdout.log        # launchd stdout capture
└── daemon.stderr.log        # launchd stderr capture
```

---

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for setup, running tests, Makefile targets, and code structure.
