from __future__ import annotations

from huggingface_hub.errors import LocalEntryNotFoundError

from vecstash.config import AppConfig, _resolve_model_path, _restore_hf_cache, _with_hf_cache


class Embedder:
    """Lazy-loading MLX embedding model wrapper."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._model = None
        self._tokenizer = None
        self._vector_size: int | None = None

    def _load(self) -> None:
        from mlx_embeddings import load as mlx_load

        old = _with_hf_cache(self._config.model.cache_dir)
        try:
            model_path = _resolve_model_path(
                model_name=self._config.model.name,
                cache_dir=self._config.model.cache_dir,
                offline_only=True,
            )
            model, processor = mlx_load(str(model_path))
            self._model = model
            # TokenizerWrapper delegates attribute access via __getattr__ but does
            # not implement __call__, so we access the underlying HF tokenizer
            # directly to use its __call__ for batch encoding.
            self._tokenizer = processor._tokenizer
            self._vector_size = model.config.hidden_size
        except LocalEntryNotFoundError:
            raise RuntimeError(
                f"Model '{self._config.model.name}' not found in local cache. "
                "Run 'vecstash models bootstrap' to download it."
            )
        finally:
            _restore_hf_cache(old)

    @property
    def vector_size(self) -> int:
        if self._model is None:
            self._load()
        return self._vector_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate L2-normalized embeddings for a list of texts."""
        if self._model is None:
            self._load()

        batch_size = self._config.runtime.max_batch_size
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = self._tokenizer(
                batch, return_tensors="mlx", padding=True, truncation=True, max_length=512
            )
            outputs = self._model(**inputs)
            all_vectors.extend(outputs.text_embeds.tolist())
        return all_vectors
