# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

`vecstash` is an offline semantic search tool for macOS Apple Silicon, written in Rust. It ships as a single binary: embeddings run in-process through ONNX Runtime (`ort`), and both vectors and metadata live in one SQLite file.

It was rewritten from Python in September 2026. The previous implementation is archived in `legacy/python/` for reference only — it is not built, not tested, and must not be modified. The rewrite is documented in `docs/specs/2026-09-18-vecstash-rust-rewrite-spec.md`, with progress tracked in `docs/ROADMAP.md`.

## Commands

```bash
cargo build
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check

cargo run -- <command>
cargo run -- --config /path/to/config.toml <command>
```

CI runs those same four checks on `macos-latest`.

## Module responsibilities

- `src/main.rs` — entrypoint, turns errors into exit codes
- `src/cli.rs` — `clap` command tree, global `--config` and `--json`, dispatch
- `src/config.rs` — `AppConfig`, TOML parsing, path containment validation
- `src/extract.rs` — `.txt`/`.md`/`.html` extraction, table linearisation, `normalize_text`
- `src/chunk.rs` — token-based chunking via `text-splitter`
- `src/embed.rs` — `Embedder` over `ort`, HuggingFace cache, `models *` commands
- `src/store.rs` — SQLite schema, upsert, exact cosine search, `status`/`storage`/`reset`
- `src/pipeline.rs` — `ingest` and `search`
- `src/update.rs` — GitHub Releases auto-update with SHA-256 verification
- `src/output.rs` — compact JSON and human output
- `src/logging.rs` — `tracing` JSON layer to file

## Conventions

- Code, comments and user-facing strings are in English. Commits are in Brazilian Portuguese, Conventional Commits, `tipo(escopo): descrição` in the infinitive, subject at most 72 characters, at most 20 files per commit.
- Errors are direct and, when recoverable, name the fixing command: `"Run 'vecstash models bootstrap' to download it."`
- Every command accepts `--json`, and JSON output is always one compact line.
- Exit codes: 0 success, 1 runtime error, 2 validation failure.
- Follow the `rust-style` skill: `for` loops over iterator chains, `let ... else` for early returns, shadowing instead of renaming, newtypes over bare strings, exhaustive matches with no wildcards, no explanatory comments.

## Traps

- **CLS pooling, not mean pooling.** `bge-m3` pools the first token and then normalises L2. Mean pooling produces plausible, silently wrong vectors. The parity test in `src/embed.rs` is what catches this.
- **Two tokenizers on purpose.** The one in `Embedder` has padding and truncation configured for ONNX batching. Chunking loads a separate one without padding, otherwise `text-splitter` would count padding tokens and emit undersized chunks.
- **`dot` is cosine only because vectors are normalised.** `Store::search` computes an inner product. That equals cosine similarity only because embeddings are L2-normalised at generation time. Inserting unnormalised vectors silently corrupts ranking.
- **`sqlite-vector-rs` was evaluated and rejected.** Its `library` feature loads a `.dylib` from disk rather than registering in-process, which would break single-binary distribution. Vectors are BLOBs in a normal column. For ANN later, use `usearch`; the metadata schema does not need to change.
- **int8 fails the parity threshold.** `model_quantized.onnx` scores 0.981939 against the reference, below the 0.999 bar. The default is `model_fp16.onnx` at 0.999999, roughly twice as slow on CPU.

## Version management

Single source of truth: `version` in `Cargo.toml`, read at compile time via `env!("CARGO_PKG_VERSION")`. The release workflow refuses to publish when the tag does not match it.

## Storage layout

```
~/.vecstash/
  config.toml
  metadata.db      documents, chunks, embeddings, schema_migrations, index_meta
  models/hub/      HuggingFace-layout model cache
  vecstash.log     one JSON object per line
```

## Out of scope for v1

PDF ingestion, the JSON-RPC daemon, the LaunchAgent, `reindex` and `doctor`. See "Fora de escopo" in the spec and the backlog in `docs/ROADMAP.md`.
