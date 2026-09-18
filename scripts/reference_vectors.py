"""Generate reference embeddings with the legacy PyTorch model.

The output feeds the Rust parity test in src/embed.rs. Run it with the legacy
Python environment, which still has sentence-transformers installed:

    ./.venv/bin/python scripts/reference_vectors.py /tmp/reference.json
"""

import json
import sys

from sentence_transformers import SentenceTransformer

MODEL = "BAAI/bge-m3"
CACHE_FOLDER = "~/.vecstash/models/hub"

TEXTS = [
    "O vecstash e uma ferramenta de busca semantica offline.",
    "Rust is a systems programming language focused on safety.",
    "Como rodar os testes do projeto?",
    "A quantizacao int8 reduz o tamanho do modelo em quatro vezes.",
    "Banco de dados vetorial embarcado com SQLite.",
]


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <output.json>", file=sys.stderr)
        return 2

    out = sys.argv[1]
    import os

    model = SentenceTransformer(
        MODEL,
        device="mps",
        cache_folder=os.path.expanduser(CACHE_FOLDER),
        local_files_only=True,
    )
    vectors = model.encode(
        TEXTS,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    payload = {"texts": TEXTS, "vectors": [v.tolist() for v in vectors]}
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    print(f"wrote {len(TEXTS)} vectors of dim {len(payload['vectors'][0])} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
