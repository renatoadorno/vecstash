from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from huggingface_hub import snapshot_download
from huggingface_hub.errors import (
    GatedRepoError,
    LocalEntryNotFoundError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
)
from mlx_embeddings import load as mlx_load

DEFAULT_CONFIG_DIR = Path.home() / ".vecstash"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_APP_NAME = "vecstash"
DEFAULT_MODEL_NAME = "mlx-community/nomicai-modernbert-embed-base-bf16"
SUPPORTED_MODEL_ARCHITECTURES = (
    "XLM-RoBERTa",
    "BERT",
    "ModernBERT",
    "Qwen3",
    "Qwen3-VL",
)
KNOWN_GOOD_MODELS = (
    "mlx-community/nomicai-modernbert-embed-base-bf16",
    "mlx-community/all-MiniLM-L6-v2-4bit",
    "mlx-community/answerdotai-ModernBERT-base-4bit",
    "Qwen/Qwen3-Embedding-0.6B",
    "Qwen/Qwen3-Embedding-4B",
)


@dataclass(frozen=True)
class ModelConfig:
    name: str
    cache_dir: Path
    preload_on_start: bool


@dataclass(frozen=True)
class PathsConfig:
    data_dir: Path
    sqlite_path: Path
    qdrant_path: Path
    socket_path: Path
    log_path: Path


@dataclass(frozen=True)
class RuntimeConfig:
    max_batch_size: int
    max_concurrency: int
    query_cache_size: int


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    model: ModelConfig
    paths: PathsConfig
    runtime: RuntimeConfig


def _expand(path: str | Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


def _default_config() -> AppConfig:
    data_dir = _expand(DEFAULT_CONFIG_DIR)
    model_cache = data_dir / "models"
    return AppConfig(
        app_name=DEFAULT_APP_NAME,
        model=ModelConfig(
            name=DEFAULT_MODEL_NAME,
            cache_dir=model_cache,
            preload_on_start=False,
        ),
        paths=PathsConfig(
            data_dir=data_dir,
            sqlite_path=data_dir / "metadata.db",
            qdrant_path=data_dir / "qdrant",
            socket_path=data_dir / "daemon.sock",
            log_path=data_dir / "vecstash.log",
        ),
        runtime=RuntimeConfig(
            max_batch_size=64,
            max_concurrency=4,
            query_cache_size=2048,
        ),
    )


def _expect_table(doc: dict[str, object], key: str) -> dict[str, object]:
    value = doc.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Section [{key}] must be a TOML table.")
    return value


def _parse_non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _parse_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _parse_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean.")
    return value


def _ensure_within(base: Path, target: Path, field: str) -> None:
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{field} must be inside paths.data_dir.") from exc


def _parse_config_doc(doc: dict[str, object]) -> AppConfig:
    default = _default_config()

    app = _expect_table(doc, "app")
    model = _expect_table(doc, "model")
    paths = _expect_table(doc, "paths")
    runtime = _expect_table(doc, "runtime")

    app_name = _parse_non_empty_str(app.get("name", default.app_name), "app.name")
    model_name = _parse_non_empty_str(model.get("name", default.model.name), "model.name")
    model_cache = _expand(model.get("cache_dir", str(default.model.cache_dir)))
    preload_on_start = _parse_bool(
        model.get("preload_on_start", default.model.preload_on_start),
        "model.preload_on_start",
    )

    data_dir = _expand(paths.get("data_dir", str(default.paths.data_dir)))
    sqlite_path = _expand(paths.get("sqlite_path", str(default.paths.sqlite_path)))
    qdrant_path = _expand(paths.get("qdrant_path", str(default.paths.qdrant_path)))
    socket_path = _expand(paths.get("socket_path", str(default.paths.socket_path)))
    log_path = _expand(paths.get("log_path", str(default.paths.log_path)))

    _ensure_within(data_dir, sqlite_path, "paths.sqlite_path")
    _ensure_within(data_dir, qdrant_path, "paths.qdrant_path")
    _ensure_within(data_dir, log_path, "paths.log_path")

    max_batch_size = _parse_positive_int(
        runtime.get("max_batch_size", default.runtime.max_batch_size),
        "runtime.max_batch_size",
    )
    max_concurrency = _parse_positive_int(
        runtime.get("max_concurrency", default.runtime.max_concurrency),
        "runtime.max_concurrency",
    )
    query_cache_size = _parse_positive_int(
        runtime.get("query_cache_size", default.runtime.query_cache_size),
        "runtime.query_cache_size",
    )

    return AppConfig(
        app_name=app_name,
        model=ModelConfig(
            name=model_name,
            cache_dir=model_cache,
            preload_on_start=preload_on_start,
        ),
        paths=PathsConfig(
            data_dir=data_dir,
            sqlite_path=sqlite_path,
            qdrant_path=qdrant_path,
            socket_path=socket_path,
            log_path=log_path,
        ),
        runtime=RuntimeConfig(
            max_batch_size=max_batch_size,
            max_concurrency=max_concurrency,
            query_cache_size=query_cache_size,
        ),
    )


def render_default_config_toml() -> str:
    d = _default_config()
    supported = ", ".join(SUPPORTED_MODEL_ARCHITECTURES)
    known = "\n".join(f"# - {name}" for name in KNOWN_GOOD_MODELS)
    return (
        "# vecstash configuration\n"
        "# Supported mlx_embeddings architectures:\n"
        f"# {supported}\n"
        "# Known good model IDs (examples):\n"
        f"{known}\n\n"
        "[app]\n"
        f'name = "{d.app_name}"\n\n'
        "[model]\n"
        f'name = "{d.model.name}"\n'
        f'cache_dir = "{d.model.cache_dir}"\n'
        f"preload_on_start = {str(d.model.preload_on_start).lower()}\n\n"
        "[paths]\n"
        f'data_dir = "{d.paths.data_dir}"\n'
        f'sqlite_path = "{d.paths.sqlite_path}"\n'
        f'qdrant_path = "{d.paths.qdrant_path}"\n'
        f'socket_path = "{d.paths.socket_path}"\n'
        f'log_path = "{d.paths.log_path}"\n\n'
        "[runtime]\n"
        f"max_batch_size = {d.runtime.max_batch_size}\n"
        f"max_concurrency = {d.runtime.max_concurrency}\n"
        f"query_cache_size = {d.runtime.query_cache_size}\n"
    )


def ensure_default_config_exists(path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(render_default_config_toml(), encoding="utf-8")


def _with_hf_cache(cache_dir: Path) -> dict[str, str | None]:
    keys = ("HF_HOME", "HF_HUB_CACHE")
    old_values = {key: os.environ.get(key) for key in keys}
    os.environ["HF_HOME"] = str(cache_dir)
    os.environ["HF_HUB_CACHE"] = str(cache_dir / "hub")
    return old_values


def _restore_hf_cache(old_values: dict[str, str | None]) -> None:
    for key, old in old_values.items():
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _resolve_model_path(model_name: str, cache_dir: Path, offline_only: bool) -> Path:
    candidate = Path(model_name).expanduser()
    if candidate.exists():
        return candidate.resolve()
    return Path(
        snapshot_download(
            repo_id=model_name,
            allow_patterns=[
                "*.json",
                "*.safetensors",
                "*.py",
                "*.tiktoken",
                "*.txt",
                "*.model",
            ],
            local_files_only=offline_only,
            cache_dir=str(cache_dir / "hub"),
        )
    )


def validate_model_reference(model_name: str, cache_dir: Path, offline_only: bool) -> tuple[bool, str]:
    old = _with_hf_cache(cache_dir)
    try:
        model_path = _resolve_model_path(model_name=model_name, cache_dir=cache_dir, offline_only=offline_only)
        kwargs: dict[str, object] = {"path_or_hf_repo": str(model_path), "lazy": True}
        if offline_only:
            kwargs["tokenizer_config"] = {"local_files_only": True}
        mlx_load(**kwargs)
        if offline_only:
            return True, "model resolved from local cache"
        return True, "model resolved (local cache and/or remote)"
    except LocalEntryNotFoundError:
        return False, "model not found in local cache"
    except RepositoryNotFoundError:
        return False, "repository does not exist"
    except RevisionNotFoundError:
        return False, "model revision not found"
    except GatedRepoError:
        return False, "model is gated and requires authentication"
    except Exception as exc:
        return False, str(exc)
    finally:
        _restore_hf_cache(old)


def load_config(path: Path | None = None) -> AppConfig:
    target = _expand(path or DEFAULT_CONFIG_PATH)
    ensure_default_config_exists(target)
    doc = tomllib.loads(target.read_text(encoding="utf-8"))
    config = _parse_config_doc(doc)
    config.paths.data_dir.mkdir(parents=True, exist_ok=True)
    config.model.cache_dir.mkdir(parents=True, exist_ok=True)
    config.paths.qdrant_path.mkdir(parents=True, exist_ok=True)
    return config
