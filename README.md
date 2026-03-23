# vecstash

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![macOS ARM](https://img.shields.io/badge/macOS-Apple%20Silicon-black.svg)](https://support.apple.com/en-us/116943)

Offline semantic storage and search for macOS Apple Silicon — no cloud, no API keys.

## Features

- **Fully offline** — embeddings run locally via MLX on Apple Silicon (M1/M2/M3/M4)
- **Fast local search** — vectors stored in embedded Qdrant, metadata in SQLite
- **Multiple file formats** — ingest `.txt`, `.md`, `.html`, and `.pdf` files
- **CLI + background daemon** — one-shot commands or a persistent JSON-RPC 2.0 server over a Unix socket
- **Auto-managed** — daemon starts on login and restarts on crash via launchd

## Requirements

- macOS on Apple Silicon (M1/M2/M3/M4)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv`)

## Installation

```bash
git clone https://github.com/renatoadorno/vecstash.git && cd vecstash
./install.sh
```

This checks prerequisites, installs both binaries to `~/.local/bin`, downloads the embedding model (~500 MB, one-time), and sets up launchd for automatic daemon startup.

**Manual install:**

```bash
make install        # Install binaries to ~/.local/bin
make bootstrap      # Download the embedding model
make launchd-install  # Set up daemon auto-start
```

## Usage

### Ingest documents

Extract and store documents for semantic search:

```bash
vecstash ingest report.pdf notes.md design.html

# JSON output
vecstash ingest report.pdf --json
```

Supported formats: `.txt`, `.md`, `.html`, `.pdf`

### Search

Run a semantic search across all ingested documents:

```bash
# Search with natural language
vecstash search "how to configure authentication"

# Limit results
vecstash search "database migrations" --top-k 5

# JSON output for scripting
vecstash search "error handling" --json
```

### Via daemon (JSON-RPC 2.0)

The daemon exposes the same operations over a Unix socket:

```bash
# Healthcheck
printf '{"jsonrpc":"2.0","id":1,"method":"healthcheck","params":{}}\n' \
  | nc -U ~/.vecstash/daemon.sock

# Search via daemon
printf '{"jsonrpc":"2.0","id":1,"method":"search","params":{"query":"authentication","top_k":5}}\n' \
  | nc -U ~/.vecstash/daemon.sock
```

### Other commands

```bash
vecstash status                        # Show configuration and storage status
vecstash models show                   # Show model info and supported architectures
vecstash models bootstrap              # Download model for offline use
```

Uninstall:

```bash
make uninstall
```

## Documentation

- [docs/README.md](docs/README.md) — full reference: configuration, CLI commands, daemon protocol, launchd integration, architecture
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — contributor guide: setup, tests, Makefile targets, code structure

## Contributing

Contributions are welcome! Please read the [development guide](docs/DEVELOPMENT.md) before submitting a pull request.

## License

This project is licensed under the [MIT License](LICENSE).
