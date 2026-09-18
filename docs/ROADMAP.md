# ROADMAP — vecstash em Rust

Referência de execução da spec `docs/specs/2026-09-18-vecstash-rust-rewrite-spec.md`.
As decisões citadas como `D<n>` estão na seção "Decisões" da spec.

**Branch:** `feature/rust-rewrite` · **Versão alvo:** `0.2.0` · **Alvo:** macOS ARM (M1, 16GB)

Legenda: `[ ]` não começou · `[~]` em andamento · `[x]` concluído

---

## Fase 0 — Backup e limpeza `[x]`

- [x] Criar a branch `feature/rust-rewrite`
- [x] Mover o código Python para `legacy/python/` (D5)
- [x] Remover da raiz o que não é documentação (D6)
- [x] Conferir que a raiz contém apenas documentação e `legacy/`
- [x] Commitar o estado limpo antes de qualquer arquivo Rust

Os dois arquivos não rastreados (`src/vecstash/teste.py` e `.github/copilot-instructions.md`) foram preservados em `legacy/` em vez de apagados. O `.venv/` continua no disco, agora ignorado pelo git — remover é opcional e libera 815MB.

## Fase 1 — Esqueleto do crate `[x]`

- [x] `Cargo.toml`: versão `0.2.0`, `rust-version = "1.90"`, edition 2024 (D15)
- [x] `clap` com derive e os 8 comandos do V1
- [x] Flags globais `--config` e `--json` (D13)
- [x] `anyhow` + `thiserror`; `tracing` com layer JSON
- [x] Versão por `env!("CARGO_PKG_VERSION")` (D15)
- [x] CI com `cargo test`, `cargo clippy -- -D warnings` e `cargo fmt --check`

`vecstash version` responde em menos de 10ms, contra 3.700ms do Python — critério 1 do objetivo atendido.

## Fase 2 — Config e storage `[x]`

- [x] `config.rs` com `serde` + `toml`, seções redesenhadas (D11)
- [x] Campos sem consumidor removidos
- [x] Validação de containment em **todos** os paths, inclusive `model.cache_dir`
- [x] Autocriação do `config.toml` na primeira execução
- [x] `store.rs` com `rusqlite`
- [x] Busca exata por produto interno sobre vetores normalizados (D9)
- [x] `ingestion_jobs` não portada
- [x] Índices em `chunks(document_id)` e `documents(content_hash)`; WAL habilitado
- [x] Testes de config e de storage

Desvio de D2/D9: a tabela virtual do `sqlite-vector-rs` foi abandonada em favor de BLOB `f32` em coluna normal. Ver **D16** na spec.

## Fase 3 — Extração e chunking `[x]`

- [x] `extract.rs` para `.txt`, `.md`, `.markdown`, `.html`, `.htm` (D8)
- [x] Markdown via `pulldown-cmark`; HTML via `scraper`
- [x] Linearização de tabelas Markdown e HTML
- [x] `normalize_text`: NFKC, quebras de linha, colapso de espaços, linhas separadoras
- [x] `content_hash` e `document_id` por SHA-256
- [x] `chunk.rs` com `text-splitter` e sizer do tokenizer (D12)
- [x] Extração em paralelo com `rayon`
- [x] Testes espelhando a suíte Python de extração e chunking

`ensure_sentence_spacing` do Python **não** foi portada: ela substituía toda quebra de linha simples por `".\n\n"`, inserindo pontos finais artificiais no texto indexado. Com chunking por tokens, a função perdeu propósito.

## Fase 4 — Embeddings via ort `[x]`

- [x] `embed.rs` com `ort`, EP de CPU como padrão (D10)
- [x] CoreML atrás de flag de config, desligada por padrão
- [x] Tokenização com o crate `tokenizers`
- [x] CLS pooling seguido de normalização L2
- [x] `models bootstrap` via `hf-hub` reaproveitando `models/hub/`
- [x] `models show` e `models validate` com `--json` respeitado (D13)
- [x] Dimensão lida do modelo, nunca hardcoded; guard de mismatch
- [x] Batching respeitando `runtime.max_batch_size`
- [x] **Teste de paridade** contra vetores de referência do Python

O teste de paridade reprovou com int8 (0,981939) e passou com fp16 (0,999999). O padrão mudou para `model_fp16.onnx`. Ver **D17** na spec.

## Fase 5 — Ingest e search `[x]`

- [x] `ingest` preservando a resiliência a falha de embedding
- [x] `search` de ponta a ponta
- [x] `comfy-table`, `termimad`, `owo-colors`
- [x] Cores de score preservadas
- [x] Índice vazio sai com exit 1
- [x] Testes de CLI com `assert_cmd` (16 casos em `tests/cli.rs`)

Validado manualmente no M1 com três documentos reais: 9 chunks, `vector_dim` 1024, e a busca em português devolve os trechos corretos. Os testes de CLI cobrem os caminhos que não exigem o modelo baixado; `insta` está declarado mas ainda não é usado, porque as asserções atuais sobre JSON são mais específicas que um snapshot.

## Fase 6 — Distribuição `[x]`

- [x] `update` com verificação de SHA-256 (D14)
- [x] Parsing de versão com `semver`, tratando pré-release
- [x] `release.yml` construindo binário arm64 com checksum e validação de tag
- [x] `clap_complete` para zsh e `clap_mangen` para manpage
- [x] Reescrever `README.md`, `docs/README.md` e `docs/DEVELOPMENT.md`
- [x] Reescrever `CLAUDE.md`, corrigindo a afirmação errada sobre validação de paths
- [x] Revisão adversarial da branch inteira antes do merge

---

## Revisão adversarial — corrigido

Quatro revisores paralelos (intenção, segurança, performance, contratos) rodaram sobre a branch. Corrigido nesta branch, com teste para cada item:

- **Identidade do documento seguia o conteúdo**, então editar um arquivo criava um documento novo e deixava o antigo órfão no índice para sempre — a busca devolvia as duas versões. `document_id` agora deriva só do caminho. Era um defeito herdado do Python.
- **`ensure_within` não bloqueava `..`**, porque `Path::starts_with` é léxico. E `model.onnx_file` nunca era validado, chegando cru ao `hf-hub`, cujo `PathBuf::push` com caminho absoluto substitui o destino inteiro.
- **Sequências de escape ANSI sobreviviam** da extração até o terminal, permitindo que um `.md` de terceiros forjasse ou apagasse resultados na tela.
- **Contrato do `--json` quebrado** em quatro caminhos de erro, que emitiam texto humano e stdout vazio.
- **Falhas de extração sumiam do JSON** do `ingest`, e o comando saía com 0 mesmo com o corpus pela metade.
- **Config e banco da v0.1.x eram aceitos**, produzindo um erro de download incompreensível e um estado contraditório. Agora são recusados com o comando corretivo.
- **Índice e log eram criados 0644**, com o texto integral dos documentos.
- **O staging do `update`** usava caminho previsível em `/tmp`, sujeito a symlink attack.
- **O pooling CLS não tinha rede no CI** — o único teste que o cobria era o de paridade, que é `#[ignore]`. `pool_cls` virou função pura com testes que rodam sempre.
- Guard de versão de schema, `probe_dimension` preguiçoso, tokenizer por referência, `..` em todos os paths, `fmt --check` no release e smoke test do artefato publicado.

## Pendente antes do merge

1. Exercitar o fluxo de `update` de verdade, o que só é possível depois da primeira release com binário publicado. O download, a verificação de checksum e o `self_replace` têm testes unitários nas partes puras, mas o caminho de rede nunca rodou ponta a ponta.
2. Medir CoreML contra CPU no M1. A flag existe e está desligada por padrão; ninguém comparou.

## Achados da revisão não corrigidos

Levantados, avaliados e deixados para depois — nenhum é defeito de correção.

- **Sem trait para o embedder**, então `cmd_ingest` e `cmd_search` não têm teste de caminho feliz. Um `trait TextEmbedder` destravaria um round-trip com dublê determinístico, sem baixar 1,2GB no CI. É o item de maior retorno da lista.
- **`chunk_with_tokenizer` não é testada** — os 9 testes de chunking cobrem `chunk_with_chars`, que existe só para teste. Uma fixture de `tokenizer.json` mínima resolveria, inclusive assertando que o tokenizer do chunking não tem padding.
- **Observabilidade quase nula**: há dois eventos `tracing` no binário inteiro, e um erro fatal não deixa rastro no log. Falta `start`/`finish` por comando e um `error!` no `main`.
- **Batching preso ao documento**: muitos arquivos pequenos viram N forwards de batch 1, sem nunca exercer `max_batch_size`. Acumular os chunks de todos os documentos antes de embedar é uma ordem de grandeza no caso "muitas notas curtas".
- **`tokenizer.json` (17MB) é parseado duas vezes** por ingestão, uma para o embedder e outra para o chunking.
- **`GraphOptimizationLevel::Level3` roda do zero** a cada invocação; `with_optimized_model_path` serializa o grafo otimizado, com a chave de cache incluindo EP e versão do ORT.
- **`max_batch_size = 64` com seq 512** dá um pico de memória desproporcional para 16GB — só a matriz de atenção passa de 1GiB. Vale medir e provavelmente baixar o default, ou trocar por orçamento de tokens.
- **`Store::search` materializa o corpus inteiro** para devolver `top_k`. Aguenta o volume atual, mas o teto está em torno de 100-200k chunks. Duas passadas com `BinaryHeap` removem o limite.
- **Erro de config sai com 1, não 2**, embora a doc chame de falha de validação. Os testes de CLI assertam `.failure()` genérico, que aceita qualquer código.
- **`storage` e `reset` ignoram `~/.vecstash/qdrant/`**, que pode ter centenas de MB órfãos de uma instalação 0.1.x.
- **Actions em refs mutáveis** e binário e checksum gerados no mesmo job: a verificação SHA-256 dá integridade de transporte, não autenticidade. Pinar por SHA e assinar o artefato (minisign/cosign) fecha isso.
- **`cargo audit`/`cargo deny` não rodam** no pipeline que publica o binário distribuído por auto-update.

## Backlog pós-V1

- **Extração de PDF** (D8) — fluxo próprio, com biblioteca de licença compatível com MIT. `pymupdf` era AGPL-3.0; `pdfium-render` (BSD-3) exige distribuir a `.dylib`; `pdf_oxide` nasceu para esse problema, mas é novo.
- **Daemon** (D3) — só volta se o startup do binário provar ser insuficiente. Com `version` em menos de 10ms, a justificativa caiu.
- **`reindex`** — re-embedar sem re-extrair, útil ao trocar de modelo.
- **`doctor`** — diagnosticar cache, dimensões e integridade do índice.
- **Linkagem estática do ONNX Runtime** — hoje o `ort` usa `download-binaries`; um binário realmente autocontido precisa disso.
- **Avaliar CoreML / Neural Engine** — a flag existe e nunca foi medida contra CPU no M1.
- **Migrar para HNSW via `usearch`** — quando o corpus passar de dezenas de milhares de chunks. A busca hoje é linear sobre todos os vetores.
- **Tap do Homebrew**.
- **Busca híbrida** — BM25 via `tantivy` combinado com a busca densa.
