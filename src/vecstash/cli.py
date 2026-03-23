from __future__ import annotations

import json as json_module
import shutil
import sys
from pathlib import Path
from typing import Annotated, Optional

import vecstash

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from vecstash.chunking import chunk_document
from vecstash.config import (
    KNOWN_GOOD_MODELS,
    ST_KNOWN_GOOD_MODELS,
    SUPPORTED_MODEL_ARCHITECTURES,
    AppConfig,
    load_config,
    validate_model_reference,
)
from vecstash.embedder import create_embedder
from vecstash.extraction import extract_files
from vecstash.logging_utils import configure_logging, get_logger
from vecstash.storage import StorageManager
from vecstash.updater import check_for_update, download_and_install

app = typer.Typer(no_args_is_help=True, pretty_exceptions_short=True)
models_app = typer.Typer(no_args_is_help=True, help="Inspect and manage embedding models.")
app.add_typer(models_app, name="models")

console = Console(stderr=True)


class _State:
    config: AppConfig | None = None
    config_path: Path | None = None


_state = _State()


@app.callback()
def _main_callback(
    config: Annotated[Optional[Path], typer.Option("--config", help="Path to config.toml.")] = None,
):
    """Offline semantic storage and search for macOS ARM."""
    _state.config_path = config
    _state.config = None


def _get_config() -> AppConfig:
    if _state.config is None:
        _state.config = load_config(_state.config_path)
        configure_logging(_state.config.paths.log_path)
    return _state.config


# ── status ────────────────────────────────────────────────────────────


@app.command()
def status(
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Show local configuration and storage status."""
    config = _get_config()
    storage = StorageManager(config)
    storage.initialize()
    ss = storage.status()
    storage.close()

    payload = {
        "app_name": config.app_name,
        "model_name": config.model.name,
        "model_backend": config.model.backend,
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
        "schema_version": ss.schema_version,
        "qdrant_collection": ss.collection_name,
        "qdrant_points_count": ss.points_count,
        "documents_count": ss.documents_count,
    }
    if json:
        print(json_module.dumps(payload))
        raise typer.Exit()

    table = Table(title="vecstash status", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key, value in payload.items():
        table.add_row(key, str(value))
    console.print(table)


# ── models ────────────────────────────────────────────────────────────


@models_app.command("show")
def models_show():
    """Show configured model and supported architecture families."""
    config = _get_config()

    table = Table(title="Configured model", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("model.name", config.model.name)
    table.add_row("model.backend", config.model.backend)
    table.add_row("model.cache_dir", str(config.model.cache_dir))
    table.add_row("model.preload_on_start", str(config.model.preload_on_start))
    console.print(table)

    if config.model.backend == "mlx":
        arch_table = Table(title="Supported MLX architectures")
        arch_table.add_column("Family", style="green")
        for item in SUPPORTED_MODEL_ARCHITECTURES:
            arch_table.add_row(item)
        console.print(arch_table)

    good_models = ST_KNOWN_GOOD_MODELS if config.model.backend == "sentence_transformers" else KNOWN_GOOD_MODELS
    models_table = Table(title="Known good models")
    models_table.add_column("Model ID", style="dim")
    for m in good_models:
        models_table.add_row(m)
    console.print(models_table)


@models_app.command("validate")
def models_validate(
    offline_only: Annotated[bool, typer.Option("--offline-only", help="Require local cache.")] = False,
):
    """Validate configured model reference."""
    config = _get_config()
    ok, detail = validate_model_reference(
        model_name=config.model.name,
        cache_dir=config.model.cache_dir,
        offline_only=offline_only,
        backend=config.model.backend,
    )
    print(json_module.dumps({
        "model_name": config.model.name,
        "cache_dir": str(config.model.cache_dir),
        "offline_only": offline_only,
        "ok": ok,
        "detail": detail,
    }))
    raise typer.Exit(code=0 if ok else 2)


@models_app.command("bootstrap")
def models_bootstrap(
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Download model to local cache for offline use."""
    config = _get_config()
    ok, detail = validate_model_reference(
        model_name=config.model.name,
        cache_dir=config.model.cache_dir,
        offline_only=False,
        backend=config.model.backend,
    )
    payload = {
        "model_name": config.model.name,
        "cache_dir": str(config.model.cache_dir),
        "ok": ok,
        "detail": detail,
    }
    if json:
        print(json_module.dumps(payload))
        raise typer.Exit(code=0 if ok else 2)

    table = Table(title="Bootstrap status", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    status_style = "green" if ok else "red"
    table.add_row("status", f"[{status_style}]{'ok' if ok else 'error'}[/{status_style}]")
    table.add_row("model", config.model.name)
    table.add_row("cache_dir", str(config.model.cache_dir))
    table.add_row("detail", detail)
    console.print(table)
    raise typer.Exit(code=0 if ok else 2)


# ── ingest ────────────────────────────────────────────────────────────


@app.command()
def ingest(
    inputs: Annotated[list[Path], typer.Argument(help="Files to ingest (.txt, .md, .html, .pdf).")],
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Extract, chunk, and index documents with vector embeddings."""
    config = _get_config()
    logger = get_logger(__name__)
    embedder = create_embedder(config)
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
                    console.print(
                        f"[yellow]Warning:[/yellow] vector indexing failed for {doc.source_path}, metadata saved."
                    )
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
        extra={"event": "ingest_complete", "count": len(docs), "model_name": config.model.name},
    )

    if json:
        print(json_module.dumps(payload))
        raise typer.Exit()

    table = Table(title="Ingest summary")
    table.add_column("File", style="cyan")
    table.add_column("Kind")
    table.add_column("Document ID", style="dim")
    for item in payload:
        table.add_row(
            Path(item["source_path"]).name,
            item["source_kind"],
            item["document_id"][:16] + "...",
        )
    console.print(table)


# ── search ────────────────────────────────────────────────────────────


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Natural language search query.")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of results.")] = 5,
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Run semantic similarity search."""
    config = _get_config()
    embedder = create_embedder(config)
    query_vector = embedder.embed([query])[0]
    storage = StorageManager(config)
    try:
        storage.initialize(vector_size=embedder.vector_size)
        if storage.status().points_count == 0:
            console.print("[yellow]No documents indexed yet. Run 'vecstash ingest <files>' first.[/yellow]")
            raise typer.Exit(code=1)
        results = storage.search(query_vector, top_k=limit)
    finally:
        storage.close()

    if json:
        print(json_module.dumps(
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
        ))
        raise typer.Exit()

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        raise typer.Exit()

    for r in results:
        filename = Path(r.source_path).name
        score_color = "green" if r.score > 0.8 else "yellow" if r.score > 0.5 else "red"
        title = f"[{score_color}]{r.score:.4f}[/{score_color}]  {filename}"
        console.print(Panel(Markdown(r.chunk_text), title=title, border_style="dim"))


# ── update ────────────────────────────────────────────────────────────


@app.command()
def update(
    check: Annotated[bool, typer.Option("--check", help="Only check, don't install.")] = False,
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Check for and install updates from GitHub."""
    try:
        info = check_for_update()
    except RuntimeError as e:
        if json:
            print(json_module.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if json:
        print(json_module.dumps({
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "update_available": info.update_available,
            "release_url": info.release_url,
        }))
        if not info.update_available or check:
            raise typer.Exit()
    else:
        if not info.update_available:
            console.print(f"[green]Already up to date[/green] (v{info.current_version}).")
            raise typer.Exit()

        console.print(
            f"New version available: v{info.current_version} → [green]v{info.latest_version}[/green]"
        )
        if check:
            raise typer.Exit()

    console.print(f"Downloading and installing v{info.latest_version}...")
    try:
        download_and_install(info)
    except RuntimeError as e:
        if json:
            print(json_module.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]Updated to v{info.latest_version}.[/green]")


# ── version ───────────────────────────────────────────────────────────


@app.command()
def version(
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Show vecstash version."""
    ver = vecstash.__version__
    if json:
        print(json_module.dumps({"version": ver}))
        raise typer.Exit()
    console.print(f"vecstash [green]v{ver}[/green]")


# ── storage ──────────────────────────────────────────────────────────


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


@app.command()
def storage(
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Show disk usage of local databases."""
    config = _get_config()
    sqlite_bytes = config.paths.sqlite_path.stat().st_size if config.paths.sqlite_path.exists() else 0
    qdrant_bytes = _dir_size(config.paths.qdrant_path)
    total_bytes = sqlite_bytes + qdrant_bytes

    payload = {
        "sqlite_path": str(config.paths.sqlite_path),
        "sqlite_bytes": sqlite_bytes,
        "qdrant_path": str(config.paths.qdrant_path),
        "qdrant_bytes": qdrant_bytes,
        "total_bytes": total_bytes,
    }
    if json:
        print(json_module.dumps(payload))
        raise typer.Exit()

    table = Table(title="vecstash storage", show_header=False)
    table.add_column("Store", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Path", style="dim")
    table.add_row("SQLite", _human_size(sqlite_bytes), str(config.paths.sqlite_path))
    table.add_row("Qdrant", _human_size(qdrant_bytes), str(config.paths.qdrant_path))
    table.add_row("[bold]Total[/bold]", f"[bold]{_human_size(total_bytes)}[/bold]", "")
    console.print(table)


# ── reset ────────────────────────────────────────────────────────────


@app.command()
def reset(
    force: Annotated[bool, typer.Option("--force", help="Skip confirmation prompt.")] = False,
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    """Delete all indexed data (SQLite database and Qdrant vectors)."""
    config = _get_config()
    sqlite_path = config.paths.sqlite_path
    qdrant_path = config.paths.qdrant_path

    sqlite_exists = sqlite_path.exists()
    qdrant_exists = qdrant_path.exists()

    if not sqlite_exists and not qdrant_exists:
        if json:
            print(json_module.dumps({"status": "nothing_to_reset"}))
        else:
            console.print("[yellow]Nothing to reset — no databases found.[/yellow]")
        raise typer.Exit()

    if not force:
        console.print("[bold red]This will permanently delete:[/bold red]")
        if sqlite_exists:
            console.print(f"  • SQLite database: {sqlite_path}")
        if qdrant_exists:
            console.print(f"  • Qdrant vectors:  {qdrant_path}")
        typer.confirm("Are you sure?", abort=True)

    deleted = []
    if sqlite_exists:
        sqlite_path.unlink()
        deleted.append("sqlite")
    if qdrant_exists:
        shutil.rmtree(qdrant_path)
        deleted.append("qdrant")

    if json:
        print(json_module.dumps({"status": "reset_complete", "deleted": deleted}))
        raise typer.Exit()

    console.print("[green]Reset complete.[/green] Deleted: " + ", ".join(deleted))


# ── scaffolded ────────────────────────────────────────────────────────


@app.command()
def reindex():
    """Rebuild local vector index (placeholder)."""
    console.print("[yellow]Command 'reindex' will be implemented in upcoming phases.[/yellow]")


@app.command()
def doctor():
    """Run local diagnostics checks (placeholder)."""
    console.print("[yellow]Command 'doctor' will be implemented in upcoming phases.[/yellow]")


# ── entry point ───────────────────────────────────────────────────────


def main():
    app()
