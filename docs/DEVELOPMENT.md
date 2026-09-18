# Desenvolvimento

## Setup

```bash
cargo build
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

A CI roda exatamente esses quatro comandos em `macos-latest`.

## Mapa dos módulos

- `src/main.rs` — entrypoint; converte erro em exit code
- `src/cli.rs` — árvore de comandos `clap`, flags globais `--config` e `--json`, despacho
- `src/config.rs` — `AppConfig`, parsing TOML, validação de containment dos paths
- `src/extract.rs` — extração de `.txt`/`.md`/`.html`, linearização de tabelas, `normalize_text`
- `src/chunk.rs` — chunking por tokens via `text-splitter` com o tokenizer do modelo
- `src/embed.rs` — `Embedder` sobre `ort`, cache HuggingFace, comandos `models *`
- `src/store.rs` — SQLite: schema, upsert, busca exata por cosseno, comandos `status`/`storage`/`reset`
- `src/pipeline.rs` — `ingest` e `search` ligando extração, chunking, embeddings e storage
- `src/update.rs` — auto-update por GitHub Releases com verificação de SHA-256
- `src/output.rs` — JSON compacto e saída humana
- `src/logging.rs` — `tracing` com layer JSON para arquivo

## Fluxo de dados

**Ingestão:** `extract_file` (em paralelo por `rayon`) produz `ExtractedDocument` → `upsert_document` grava metadados → `chunk_with_tokenizer` divide por tokens → `Embedder::embed` gera vetores → `replace_chunks` substitui os chunks antigos do documento numa transação.

**Busca:** a query é embedada → `Store::search` lê todos os vetores, calcula o produto interno contra a query e ordena → os `top_k` são renderizados.

Como os vetores são normalizados em L2 na geração, o produto interno **é** a similaridade de cosseno. Se algum dia entrarem vetores não normalizados no índice, `dot` deixa de ser cosseno e a ordenação fica errada.

## Decisões que não são óbvias no código

**Vetores em BLOB, não em tabela virtual.** A crate `sqlite-vector-rs` foi avaliada e descartada: a feature `library` não registra o módulo em processo, ela carrega um `.dylib` do disco. Isso quebraria a distribuição por binário único. Com busca exata sobre alguns milhares de chunks, o produto interno em Rust resolve sem dependência nenhuma. Para ANN, o próximo passo é `usearch`, e os metadados não precisam mudar.

**CLS pooling, não mean pooling.** O `bge-m3` usa o token `[CLS]` — o primeiro da sequência — seguido de normalização L2. Usar mean pooling produz vetores plausíveis e silenciosamente errados; o teste de paridade é o que pega isso.

**Dois tokenizers.** O `Embedder` configura padding e truncation no seu tokenizer, o que é necessário para o batch do ONNX. O chunking usa um tokenizer separado, sem padding, porque senão o sizer do `text-splitter` contaria os tokens de padding e os chunks sairiam menores que o pedido.

## Teste de paridade

Confere que os vetores do Rust batem com os do modelo de referência em PyTorch. Precisa do modelo baixado, então é `#[ignore]` por padrão.

```bash
# 1. gerar a referência com o ambiente Python legado
./.venv/bin/python scripts/reference_vectors.py /tmp/reference.json

# 2. rodar a comparação
VECSTASH_PARITY_CONFIG=~/.vecstash/config.toml \
VECSTASH_PARITY_REFERENCE=/tmp/reference.json \
cargo test embeddings_match -- --ignored --nocapture
```

O limiar é cosseno > 0,999. Resultados medidos no M1: `model_fp16.onnx` dá 0,999999; `model_quantized.onnx` (int8) dá 0,981939 e **reprova**.

## Release

```bash
# 1. bump em Cargo.toml
# 2. commit
git tag v0.2.1 && git push && git push --tags
```

O workflow valida que a tag bate com a versão do `Cargo.toml`, compila para `aarch64-apple-darwin`, gera o `.sha256` e anexa os dois ao GitHub Release. O comando `update` recusa instalar sem o checksum.

## Legado

`legacy/python/` guarda a implementação em Python (1.700 linhas de fonte, 69 testes) para consulta. Não é compilada nem testada, e não deve receber alterações.
