from __future__ import annotations

import argparse
import os
import socketserver
import sys
from pathlib import Path
from typing import Any

from vecstash.config import AppConfig, load_config, validate_model_reference
from vecstash.logging_utils import configure_logging, get_logger
from vecstash.rpc import jsonrpc_error, jsonrpc_result, parse_jsonrpc_line
from vecstash.storage import StorageManager

logger = get_logger(__name__)


class JsonRpcHandler(socketserver.StreamRequestHandler):
    config: AppConfig
    storage: StorageManager

    def handle(self) -> None:
        client = f"{self.client_address}"
        logger.info(
            "rpc_client_connected",
            extra={"event": "rpc_client_connected", "client": client},
        )
        while True:
            line = self.rfile.readline()
            if not line:
                break
            raw = line.decode("utf-8").strip()
            if not raw:
                continue
            try:
                req = parse_jsonrpc_line(raw)
                response = self._dispatch(req.method, req.id, req.params)
            except Exception as exc:
                response = jsonrpc_error(None, -32600, str(exc))
            self.wfile.write((response + "\n").encode("utf-8"))
            self.wfile.flush()

    def _dispatch(self, method: str, req_id: str | int | None, params: dict[str, Any]) -> str:
        if method == "healthcheck":
            return jsonrpc_result(
                req_id,
                {
                    "status": "ok",
                    "app_name": self.config.app_name,
                    "model": self.config.model.name,
                    "socket_path": str(self.config.paths.socket_path),
                },
            )
        if method == "status":
            storage_status = self.storage.status()
            return jsonrpc_result(
                req_id,
                {
                    "data_dir": str(self.config.paths.data_dir),
                    "sqlite_path": str(self.config.paths.sqlite_path),
                    "qdrant_path": str(self.config.paths.qdrant_path),
                    "schema_version": storage_status.schema_version,
                    "qdrant_collection": storage_status.collection_name,
                    "qdrant_points_count": storage_status.points_count,
                    "documents_count": storage_status.documents_count,
                },
            )
        if method in {"ingest", "search", "models", "reindex", "doctor"}:
            return jsonrpc_result(
                req_id,
                {
                    "status": "scaffolded",
                    "method": method,
                    "message": "Method is scaffolded and will be implemented in upcoming phases.",
                    "params": params,
                },
            )
        return jsonrpc_error(req_id, -32601, f"Method not found: {method}")


class JsonRpcServer(socketserver.UnixStreamServer):
    allow_reuse_address = True

    def __init__(self, socket_path: str, handler, config: AppConfig, storage: StorageManager):
        self.config = config
        self.storage = storage
        super().__init__(socket_path, handler)
        self.RequestHandlerClass.config = config
        self.RequestHandlerClass.storage = storage


def _cleanup_stale_socket(path: Path) -> None:
    if path.exists():
        path.unlink()


def build_parser() -> argparse.ArgumentParser:
    # Daemon uses its own argparse (not Typer) — it has a single --config flag
    # and no interactive terminal output. CLI commands use Typer in cli.py.
    parser = argparse.ArgumentParser(
        prog="vecstash-daemon",
        description="JSON-RPC daemon for local semantic storage/search.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to config.toml (defaults to ~/.vecstash/config.toml).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.paths.log_path)
    if config.model.preload_on_start:
        ok, detail = validate_model_reference(
            model_name=config.model.name,
            cache_dir=config.model.cache_dir,
            offline_only=False,
        )
        if not ok:
            logger.error(
                "model_preload_failed",
                extra={
                    "event": "model_preload_failed",
                    "detail": detail,
                    "model_name": config.model.name,
                },
            )
            return 2
        logger.info(
            "model_preloaded",
            extra={
                "event": "model_preloaded",
                "model_name": config.model.name,
            },
        )

    socket_path = config.paths.socket_path
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_socket(socket_path)
    storage = StorageManager(config)
    storage.initialize()

    with JsonRpcServer(str(socket_path), JsonRpcHandler, config, storage) as server:
        os.chmod(socket_path, 0o600)
        logger.info(
            "daemon_started",
            extra={"event": "daemon_started", "socket_path": str(socket_path)},
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("daemon_stopped", extra={"event": "daemon_stopped"})
        finally:
            storage.close()
            _cleanup_stale_socket(socket_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
