# ROADMAP — vecstash em Rust

Referência de execução da spec `docs/specs/2026-09-18-vecstash-rust-rewrite-spec.md`.
As decisões citadas como `D<n>` estão na seção "Decisões" da spec.

**Branch:** `feature/rust-rewrite` · **Versão alvo:** `0.2.0` · **Alvo:** macOS ARM (M1, 16GB)

Legenda: `[ ]` não começou · `[~]` em andamento · `[x]` concluído

---

## Fase 0 — Backup e limpeza

- [ ] Criar a branch `feature/rust-rewrite`
- [ ] Mover o código Python para `legacy/python/` (D5): `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `Makefile`, `install.sh`, `support/`, `.python-version`
- [ ] Remover da raiz o que não é documentação (D6): `.venv/`, `examples/bun-docs.md`, `src/vecstash/teste.py`, `.github/copilot-instructions.md`
- [ ] Conferir que a raiz contém apenas `README.md`, `LICENSE`, `CLAUDE.md`, `docs/`, `legacy/`, `.git/`, `.github/workflows/`
- [ ] Commitar o estado limpo antes de qualquer arquivo Rust

**Pronto quando:** `ls` na raiz mostra só documentação e `legacy/`, e o histórico tem um commit isolando a limpeza.

## Fase 1 — Esqueleto do crate

- [ ] `Cargo.toml`: nome `vecstash`, versão `0.2.0`, `rust-version` fixada no estável atual (D15)
- [ ] `clap` com derive: os 7 comandos do V1 declarados (`ingest`, `search`, `status`, `storage`, `reset`, `models`, `version`) mais `update`, todos retornando "não implementado"
- [ ] Flag global `--config PATH`, e `--json` em todos os comandos (D13)
- [ ] `anyhow` no binário, `thiserror` na lib; `tracing` + `tracing-subscriber` com layer JSON reproduzindo os campos `ts`, `level`, `logger`, `message`, `command`, `event`
- [ ] Versão lida por `env!("CARGO_PKG_VERSION")` (D15)
- [ ] CI: substituir `uv sync` + `unittest` por `cargo test` e `cargo clippy -- -D warnings` em `macos-latest`

**Pronto quando:** `cargo run -- version --json` responde, e `cargo run -- --help` lista a árvore de comandos completa.

## Fase 2 — Config e storage

- [ ] `config.rs` com `serde` + `toml`: seções `[app]`, `[model]`, `[paths]`, `[runtime]` redesenhadas (D11)
- [ ] Remover os campos sem consumidor: `model.backend`, `model.preload_on_start`, `paths.socket_path`, `runtime.max_concurrency`, `runtime.query_cache_size`
- [ ] Validação de containment aplicada a **todos** os paths — corrigindo o que `CLAUDE.md:78` afirmava e o Python não fazia
- [ ] Autocriação do `config.toml` na primeira execução, preservando `~/.vecstash/` como `data_dir` e `models/hub/` como cache
- [ ] `store.rs` com `rusqlite` + `sqlite-vector-rs`: tabelas `documents`, `chunks`, `schema_migrations` e a tabela virtual de vetores
- [ ] `chunks.id INTEGER PRIMARY KEY` casando com o `rowid` da tabela virtual (D9); sem `uuid5`, sem `point_id`
- [ ] Busca exata no V1, HNSW atrás de opção de config (D9)
- [ ] Não portar a tabela `ingestion_jobs` — nunca foi lida nem escrita
- [ ] Índices em `chunks(document_id)` e `documents(content_hash)`; WAL habilitado (o Python não tinha nenhum dos dois)
- [ ] Testes de config (validação, defaults, rejeição de path fora do `data_dir`) e de storage (roundtrip, upsert substituindo chunks antigos, contagem)

**Pronto quando:** `status`, `storage` e `reset` funcionam de verdade, com testes verdes.

## Fase 3 — Extração e chunking

- [ ] `extract.rs` para `.txt`, `.md`, `.markdown`, `.html`, `.htm` (D8) — PDF fica fora
- [ ] Markdown via `pulldown-cmark`; HTML via `scraper` ou `lol_html`
- [ ] Portar a linearização de tabelas (Markdown e HTML) — é o comportamento mais testado do projeto atual
- [ ] Portar `normalize_text`: NFKC, normalização de quebras de linha, colapso de espaços, remoção de linhas separadoras
- [ ] `content_hash` e `document_id` por SHA-256, mantendo o esquema `sha256(path:content_hash)`
- [ ] `chunk.rs` com `text-splitter` e sizer do tokenizer do bge-m3: ~512 tokens, ~64 de overlap, configuráveis (D12)
- [ ] Extração de múltiplos arquivos em paralelo com `rayon` — hoje é serial (`extract_files` itera em lista)
- [ ] Testes espelhando os 21 casos de `legacy/python/tests/test_extraction.py` e os 8 de `test_chunking.py`

**Pronto quando:** extração e chunking têm paridade de comportamento com o Python nos casos cobertos pela suíte antiga.

## Fase 4 — Embeddings via ort

- [ ] `embed.rs` com `ort`, feature `download-binaries`, EP de CPU como padrão (D10)
- [ ] CoreML atrás de flag de config, desligada por padrão
- [ ] Tokenização com o crate `tokenizers` lendo o `tokenizer.json` do bge-m3
- [ ] **CLS pooling seguido de normalização L2** — não mean pooling; errar aqui produz vetores silenciosamente errados
- [ ] `models bootstrap` baixando `Xenova/bge-m3` int8 (~570MB) via `hf-hub`, reaproveitando `models/hub/` (D4)
- [ ] `models show` e `models validate` com `--json` respeitado (D13)
- [ ] Dimensão lida do modelo, nunca hardcoded; guard de mismatch preservando a mensagem que manda rodar `vecstash reset`
- [ ] Batching respeitando `runtime.max_batch_size`
- [ ] **Teste de paridade:** cosseno > 0,999 contra vetores de referência gerados pelo Python para um conjunto fixo de textos

**Pronto quando:** o teste de paridade passa. Sem ele, não há como afirmar que a busca continua correta.

## Fase 5 — Ingest e search

- [ ] `ingest`: extração → chunking → embedding → persistência, preservando a resiliência atual (falha de embedding vira warning, metadados são gravados)
- [ ] `search`: embedding da query → busca por cosseno → resultados
- [ ] Saída humana: `comfy-table` para as tabelas, `termimad` para renderizar o Markdown dos resultados, `indicatif` para progresso na ingestão, `anstream`/`owo-colors` para cor com detecção de TTY
- [ ] Cores de score preservadas: verde acima de 0,8, amarelo acima de 0,5, vermelho abaixo
- [ ] Índice vazio continua saindo com exit 1
- [ ] Testes com `assert_cmd` e snapshots `insta` das duas saídas

**Pronto quando:** `ingest` seguido de `search` devolve os mesmos documentos que a versão Python para o mesmo corpus.

## Fase 6 — Distribuição

- [ ] `update` com verificação de SHA-256 (D14) — o Python não verificava integridade em ponto algum
- [ ] Parsing de versão com o crate `semver`, tratando pré-release em vez de engolir o erro silenciosamente
- [ ] `release.yml`: construir binário arm64, gerar checksum, anexar ao GitHub Release
- [ ] `clap_complete` para completions de zsh e `clap_mangen` para manpage — nenhum dos dois existe hoje
- [ ] Reescrever `README.md`, `docs/README.md` e `docs/DEVELOPMENT.md` para a stack Rust
- [ ] Reescrever `CLAUDE.md`, inclusive corrigindo a afirmação errada sobre validação de paths
- [ ] Revisão adversarial da branch inteira antes do merge

**Pronto quando:** `cargo install` a partir do release produz um binário funcional em uma máquina limpa.

---

## Backlog pós-V1

- **Extração de PDF** (D8) — fluxo próprio, e a escolha de biblioteca precisa de licença compatível com MIT. `pymupdf` era AGPL-3.0; `pdfium-render` (Pdfium, BSD-3) exige distribuir a `.dylib`; `pdf_oxide` nasceu exatamente para esse problema, mas é novo.
- **Daemon** (D3) — só volta se o startup do binário provar ser insuficiente na prática. Se voltar, implementar `ingest` e `search` de verdade, não os placeholders que existiam.
- **`reindex`** — re-embedar sem re-extrair, útil ao trocar de modelo. Nunca foi implementado.
- **`doctor`** — diagnosticar cache, dimensões e integridade do índice. Nunca foi implementado.
- **Linkagem estática do ONNX Runtime** — elimina a dependência de `.dylib` no binário distribuído.
- **Avaliar CoreML / Neural Engine** — medir contra CPU no M1. Referência externa aponta 2–3x sobre MPS e 2,6–3,8x de eficiência energética para XLM-RoBERTa no ANE, mas com int8 o CoreML tende a rejeitar operadores.
- **Migrar para HNSW** — quando o corpus passar da ordem de dezenas de milhares de chunks.
- **Tap do Homebrew** — instalação por `brew install`.
- **Busca híbrida** — BM25 via `tantivy` combinado com a busca densa.
