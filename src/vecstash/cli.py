from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vecstash.chunking import chunk_document
from vecstash.config import (
    AppConfig,
    KNOWN_GOOD_MODELS,
    SUPPORTED_MODEL_ARCHITECTURES,
    load_config,
    validate_model_reference,
)
from vecstash.embedder import Embedder
from vecstash.extraction import extract_files
from vecstash.logging_utils import configure_logging, get_logger
from vecstash.storage import StorageManager
from vecstash.updater import check_for_update, download_and_install


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vecstash",
        description="Offline semantic storage and search for macOS ARM.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to config.toml (defaults to ~/.vecstash/config.toml).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show local configuration status.")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit status in JSON format.",
    )

    models_parser = subparsers.add_parser("models", help="Inspect and validate MLX model settings.")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("show", help="Show configured model and supported architecture families.")
    validate_parser = models_sub.add_parser(
        "validate",
        help="Validate configured model (local cache only with --offline-only).",
    )
    validate_parser.add_argument(
        "--offline-only",
        action="store_true",
        help="Require model to be already available in local cache.",
    )
    bootstrap_parser = models_sub.add_parser(
        "bootstrap",
        help="Force model download/resolution now so later runtime can be offline.",
    )
    bootstrap_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit bootstrap status in JSON format.",
    )

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Extract, chunk, and index documents with vector embeddings.",
    )
    ingest_parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Files to ingest (.txt, .md, .html, .pdf).",
    )
    ingest_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit extraction results as JSON list.",
    )

    search_parser = subparsers.add_parser("search", help="Run semantic similarity search.")
    search_parser.add_argument("query", help="Natural language search query.")
    search_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        metavar="N",
        help="Number of results to return (default: 5).",
    )
    search_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON.",
    )

    update_parser = subparsers.add_parser(
        "update",
        help="Check for and install updates from GitHub.",
    )
    update_parser.add_argument(
        "--check",
        action="store_true",
        help="Only check if an update is available, don't install.",
    )
    update_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit result as JSON.",
    )

    for name, help_text in (
        ("reindex", "Rebuild local vector index (placeholder)."),
        ("doctor", "Run local diagnostics checks (placeholder)."),
    ):
        subparsers.add_parser(name, help=help_text)

    return parser


def _print_status(config: AppConfig, as_json: bool) -> int:
    storage = StorageManager(config)
    storage.initialize()
    storage_status = storage.status()
    storage.close()

    payload = {
        "app_name": config.app_name,
        "model_name": config.model.name,
        "model_cache_dir": str(config.model.cache_dir),
        "data_dir": str(config.paths.data_dir),
        "sqlite_path": str(config.paths.sqlite_path),
        "qdrant_path": str(config.paths.qdrant_path),
        "socket_path": str(config.paths.socket_path),
        "log_path": str(config.paths.log_path),
        "max_batch_size": config.runtime.max_batch_size,
        "max_concurrency": config.runtime.max_concurrency,
        "query_cache_size": config.runtime.query_cache_size,
        "preload_on_start": config.model.preload_on_start,
        "schema_version": storage_status.schema_version,
        "qdrant_collection": storage_status.collection_name,
        "qdrant_points_count": storage_status.points_count,
        "documents_count": storage_status.documents_count,
    }
    if as_json:
        print(json.dumps(payload))
        return 0

    print("vecstash status")
    for key, value in payload.items():
        print(f"- {key}: {value}")
    return 0


def _models_show(config: AppConfig) -> int:
    print("Configured model")
    print(f"- model.name: {config.model.name}")
    print(f"- model.cache_dir: {config.model.cache_dir}")
    print(f"- model.preload_on_start: {config.model.preload_on_start}")
    print("Supported architecture families (mlx_embeddings):")
    for item in SUPPORTED_MODEL_ARCHITECTURES:
        print(f"- {item}")
    print("Known good model IDs (examples):")
    for model in KNOWN_GOOD_MODELS:
        print(f"- {model}")
    return 0


def _models_validate(config: AppConfig, offline_only: bool) -> int:
    ok, detail = validate_model_reference(
        model_name=config.model.name,
        cache_dir=config.model.cache_dir,
        offline_only=offline_only,
    )
    payload = {
        "model_name": config.model.name,
        "cache_dir": str(config.model.cache_dir),
        "offline_only": offline_only,
        "ok": ok,
        "detail": detail,
    }
    print(json.dumps(payload))
    return 0 if ok else 2


def _models_bootstrap(config: AppConfig, as_json: bool) -> int:
    ok, detail = validate_model_reference(
        model_name=config.model.name,
        cache_dir=config.model.cache_dir,
        offline_only=False,
    )
    payload = {
        "model_name": config.model.name,
        "cache_dir": str(config.model.cache_dir),
        "ok": ok,
        "detail": detail,
    }
    if as_json:
        print(json.dumps(payload))
    else:
        status = "ok" if ok else "error"
        print(f"bootstrap status: {status}")
        print(f"- model: {config.model.name}")
        print(f"- cache_dir: {config.model.cache_dir}")
        print(f"- detail: {detail}")
    return 0 if ok else 2


def _ingest_extract(config: AppConfig, inputs: list[Path], as_json: bool) -> int:
    logger = get_logger(__name__)
    embedder = Embedder(config)
    storage = StorageManager(config)
    try:
        storage.initialize(vector_size=embedder.vector_size)
        docs = extract_files(inputs)
        for doc in docs:
            storage.upsert_document_metadata(doc)
            chunks = chunk_document(doc)
            if chunks:
                try:
                    embeddings = embedder.embed([c.text for c in chunks])
                    storage.upsert_chunks(doc, chunks, embeddings)
                except Exception:
                    logger.exception(
                        "embedding_failed",
                        extra={"event": "embedding_failed", "source_path": str(doc.source_path)},
                    )
                    print(f"Warning: vector indexing failed for {doc.source_path}, metadata saved.", file=sys.stderr)
    finally:
        storage.close()
    payload = [
        {
            "document_id": doc.document_id,
            "source_path": str(doc.source_path),
            "source_kind": doc.source_kind,
            "metadata": doc.metadata,
        }
        for doc in docs
    ]
    logger.info(
        "ingest_complete",
        extra={
            "event": "ingest_complete",
            "count": len(docs),
            "model_name": config.model.name,
        },
    )

    if as_json:
        print(json.dumps(payload))
        return 0

    print("Ingest summary")
    for item in payload:
        print(f"- {item['source_path']} [{item['source_kind']}] -> id={item['document_id']}")
    return 0


def _search(config: AppConfig, query: str, limit: int, as_json: bool) -> int:
    embedder = Embedder(config)
    query_vector = embedder.embed([query])[0]
    storage = StorageManager(config)
    try:
        storage.initialize(vector_size=embedder.vector_size)
        if storage.status().points_count == 0:
            print("No documents indexed yet. Run 'vecstash ingest <files>' first.")
            return 1
        results = storage.search(query_vector, top_k=limit)
    finally:
        storage.close()

    if as_json:
        print(
            json.dumps(
                [
                    {
                        "score": r.score,
                        "document_id": r.document_id,
                        "source_path": r.source_path,
                        "chunk_index": r.chunk_index,
                        "chunk_text": r.chunk_text,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
        return 0

    if not results:
        print("No results found.")
        return 0

    for r in results:
        filename = Path(r.source_path).name
        print(f"score: {r.score:.4f}  {filename}")
        print("-" * 40)
        print(r.chunk_text)
        print()
    return 0


def _update(check_only: bool, as_json: bool) -> int:
    try:
        info = check_for_update()
    except RuntimeError as e:
        if as_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps({
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "update_available": info.update_available,
            "release_url": info.release_url,
        }))
        if not info.update_available or check_only:
            return 0
    else:
        if not info.update_available:
            print(f"Already up to date (v{info.current_version}).")
            return 0

        print(f"New version available: v{info.current_version} → v{info.latest_version}")

        if check_only:
            return 0

    print(f"Downloading and installing v{info.latest_version}...")
    try:
        download_and_install(info)
    except RuntimeError as e:
        if as_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Updated to v{info.latest_version}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "update":
        return _update(check_only=args.check, as_json=args.json)

    config = load_config(args.config)
    configure_logging(config.paths.log_path)
    logger = get_logger(__name__)

    if args.command == "status":
        return _print_status(config, as_json=args.json)
    if args.command == "models":
        if args.models_command == "show":
            return _models_show(config)
        if args.models_command == "validate":
            return _models_validate(config, offline_only=args.offline_only)
        if args.models_command == "bootstrap":
            return _models_bootstrap(config, as_json=args.json)
    if args.command == "ingest":
        return _ingest_extract(config=config, inputs=args.inputs, as_json=args.json)
    if args.command == "search":
        return _search(config=config, query=args.query, limit=args.limit, as_json=args.json)

    logger.info(
        "command_not_implemented",
        extra={
            "command": args.command,
            "detail": "Command scaffold is ready; implementation will follow next phases.",
        },
    )
    print(f"Command '{args.command}' is scaffolded and will be implemented in upcoming phases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
