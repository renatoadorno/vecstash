# Spec: reescrita do vecstash em Rust

**Data:** 2026-09-18
**Tipo:** feature (reescrita completa, sem paridade obrigatória)
**Origem:** —
**Repo:** vecstash
**Estado:** concluída
**ROADMAP:** `docs/ROADMAP.md`

## Contexto

O `vecstash` é hoje um CLI Python (1.700 linhas em `src/`, 1.000 em `tests/`) para busca semântica offline em macOS ARM. A decisão de reescrever em Rust nasceu de uma análise de performance feita em 2026-09-18, cujos números estão em "Medições da base atual" abaixo.

**Três afirmações do enunciado ou da documentação foram refutadas pela análise:**

1. **`CLAUDE.md:78` está incorreto.** Afirma "All paths must be within `paths.data_dir` (enforced at parse time)". A validação `_ensure_within` é aplicada a apenas 3 dos 5 paths — `sqlite_path`, `qdrant_path` e `log_path` (`src/vecstash/config.py:160-162`). `socket_path` e `model.cache_dir` não são validados.

2. **O gargalo de startup não é o Python.** O custo de `vecstash version` é de 3,7–4,4s, e 4,54s desse total são o import de `langchain_text_splitters`, puxado no topo de `src/vecstash/chunking.py:6` e alcançado por `cli.py` em toda invocação. `torch` custa 0,99s; `qdrant_client`, 0,52s; `rich`, 0,02s. A reescrita em Rust elimina a classe do problema, mas o ganho não deve ser atribuído inteiramente à troca de linguagem.

3. **A superfície a portar é menor que a documentada.** O daemon implementa apenas `healthcheck` e `status`; `ingest`, `search`, `models`, `reindex` e `doctor` retornam `{"status": "scaffolded"}` (`src/vecstash/daemon.py:69-78`). O daemon está fora do escopo V1 por decisão D3.

## Objetivo

Um binário único em Rust que substitui o CLI Python com startup de ordem de milissegundos em vez de segundos, sem venv de 815MB e sem dois backends de embedding concorrentes.

Critério observável:

1. `vecstash version` responde em menos de 50ms (hoje: 3.700ms).
2. `vecstash search "<query>"` retorna os mesmos documentos que a versão Python para o mesmo corpus, com similaridade de cosseno superior a 0,999 entre os vetores gerados pelos dois runtimes.
3. Distribuição por binário único, sem Python, sem `uv`, sem `.venv`.

## Medições da base atual

Colhidas em 2026-09-18 no M1 alvo, com o `.venv` do projeto:

- `vecstash version` (3 execuções): 9,53s / 4,18s / 3,73s.
- `import vecstash.cli`: 4,38s.
- `import langchain_text_splitters`: **4,54s**.
- `import sentence_transformers`: 3,00s · `import torch`: 0,99s · `import qdrant_client`: 0,52s · `import bs4`: 0,16s · `import pymupdf`: 0,13s · `import typer`: 0,08s · `import huggingface_hub`: 0,04s · `import rich`: 0,02s.
- Tamanho do `.venv`: 815MB.
- Índice em produção: `metadata.db` 40KB, `qdrant/` 264KB, `models/` 4,5GB.

O tamanho do índice é a justificativa para descartar os dados atuais em vez de migrá-los: re-ingerir o corpus é mais barato que escrever um migrador.

## Análise da base

### Superfície tocada

**Entry points** (`pyproject.toml:42-44`): `vecstash = vecstash.cli:main` e `vecstash-daemon = vecstash.daemon:main`.

**Comandos implementados** (Typer, `src/vecstash/cli.py:32`; callback global `--config PATH` em `:47-53`):

- `status [--json]` — `cli.py:66-105`. JSON com 17 chaves: `app_name`, `model_name`, `model_backend`, `model_cache_dir`, `data_dir`, `sqlite_path`, `qdrant_path`, `socket_path`, `log_path`, `max_batch_size`, `max_concurrency`, `query_cache_size`, `preload_on_start`, `schema_version`, `qdrant_collection`, `qdrant_points_count`, `documents_count`.
- `models show` — `cli.py:111-137`. **Não tem `--json`.** Emite até 3 `Table`.
- `models validate [--offline-only]` — `cli.py:140-159`. **Sempre emite JSON**, ignorando o padrão `--json` do resto da CLI. Exit 0/2.
- `models bootstrap [--json]` — `cli.py:164-193`. Não baixa nada por si: reexecuta `validate_model_reference` com `offline_only=False` e deixa o download para `sentence_transformers`/`huggingface_hub`. Exit 0/2.
- `ingest <inputs...> [--json]` — `cli.py:200-258`. Falha de embedding por documento vira warning; os metadados são gravados mesmo assim (`cli.py:216-226`).
- `search <query> [--limit/-n N] [--json]` — `cli.py:265-308`. Índice vazio: exit 1. **Único comando cujo JSON usa `indent=2`.** Saída humana: `Panel(Markdown(...))` por resultado, score verde acima de 0,8, amarelo acima de 0,5, vermelho abaixo.
- `update [--check] [--json]` — `cli.py:315-359`.
- `version [--json]` — `cli.py:365-374`.
- `storage [--json]` — `cli.py:394-422`.
- `reset [--force] [--json]` — `cli.py:429-468`. Sem `--force`, usa `typer.confirm(abort=True)`.
- `reindex` e `doctor` — `cli.py:474-483`. Apenas imprimem um aviso de não implementado.

**Config** (`src/vecstash/config.py`), seções `[app]`, `[model]`, `[paths]`, `[runtime]`:

- `app.name` default `"vecstash"` · `model.name` default `"BAAI/bge-m3"` (`:19`) · `model.backend` default `"sentence_transformers"`, restrito a `("mlx", "sentence_transformers")` (`:21`, `:150-152`) · `model.cache_dir` default `data_dir/models` · `model.preload_on_start` default `false`.
- `paths.data_dir` default `~/.vecstash` (`:16`) · `sqlite_path`, `qdrant_path`, `socket_path`, `log_path`.
- `runtime.max_batch_size` default 64 (`:96`) · `max_concurrency` default 4 · `query_cache_size` default 2048.

**Variáveis de ambiente** (`config.py:239-260`) — as únicas do pacote: lê e restaura `HF_HOME`, `HF_HUB_CACHE`, `HF_HUB_OFFLINE`; muta também a constante de processo `huggingface_hub.constants.HF_HUB_OFFLINE` (`:245-247`).

**Schema SQLite** (`storage.py:52-104`): `schema_migrations`, `documents`, `ingestion_jobs`, `chunk_index_state`. `SCHEMA_VERSION = 1`. Sem nenhum `CREATE INDEX`, sem WAL, sem `PRAGMA`.

**Payload Qdrant** (`storage.py:284-291`): coleção única `document_chunks`, cosseno, `HnswConfigDiff(m=16, ef_construct=100)`; `point.id = uuid5(NAMESPACE_DNS, chunk_id)`; payload `{document_id, source_path, chunk_text, chunk_index}`.

### Convenções vigentes

- **Idioma:** código, comentários, docstrings e strings de UI 100% em inglês. Nenhum caractere acentuado em `src/` ou `tests/`.
- **Commits:** Conventional Commits (`feat`, `fix`, `docs`, `chore`, `test`, `build`, `ci`, `refactor`), com release fixo em `chore: release vX.Y.Z`.
- **Mensagens de erro:** inglês, tom direto; os erros recuperáveis citam o comando corretivo entre aspas simples — `"Run 'vecstash models bootstrap' to download it."` (`embedder.py:35-38`), `"Run 'vecstash reset' to clear the index before switching models."` (`storage.py:195-199`).
- **Logging** (`logging_utils.py:11-33`): uma linha JSON por registro, campos fixos `ts` (ISO 8601 UTC), `level`, `logger`, `message`, mais os opcionais `command`, `event`, `method`, `client`. Destino exclusivo é o arquivo; não há handler de console.
- **Versão:** declarada em `pyproject.toml:3`, lida via `importlib.metadata.version("vecstash")` com fallback `"0.0.0-dev"` (`__init__.py:3-8`). **Está dessincronizada: `pyproject.toml` diz `0.1.9` e a tag mais recente é `v0.1.10`.**
- **Lint/format:** não existe. Sem ruff, mypy, black, pre-commit, `.editorconfig` ou alvo de lint no Makefile.
- **Documentação que sobrevive à limpeza:** `README.md` (123 linhas), `docs/README.md` (479), `docs/DEVELOPMENT.md` (129), `CLAUDE.md` (121). `examples/bun-docs.md` (270 linhas) é documentação do runtime Bun, sem relação com o projeto.

### Testes existentes

A suíte é `unittest` puro rodado por `python -m unittest discover -s tests -p 'test_*.py'`, sem pytest, sem `conftest.py` e sem fixtures compartilhadas; cada método cria seu próprio `tempfile.TemporaryDirectory()` e escreve um `config.toml` dentro dele, e os testes de CLI usam `typer.testing.CliRunner`. São **69 testes** em 13 arquivos.

- Distribuição: `test_extraction.py` 21 · `test_updater.py` 11 · `test_chunking.py` 8 · `test_config.py` 5 · `test_storage_chunks.py` 5 · `test_cli_reset.py` 5 · `test_embedder_factory.py` 4 · `test_cli_storage.py` 3 · `test_cli_models.py` 2 · `test_cli_version.py` 2 · `test_storage.py` 1 · `test_cli_ingest.py` 1 · `test_daemon_preload.py` 1.
- **Nenhum teste carrega modelo real.** `create_embedder` é substituído por `MagicMock` com vetores fixos de 16 dimensões (`tests/test_cli_ingest.py:16-21`); `test_embedder_factory.py:42-63` só verifica `isinstance`. A lógica de `embed()` — batching, normalização L2 — não tem cobertura alguma.
- **Qdrant é real nos testes**, instanciado em tmpdir (`tests/test_storage_chunks.py:59-60`), nunca mockado.
- **Sem cobertura:** `src/vecstash/rpc.py` e `src/vecstash/logging_utils.py` não são mencionados em nenhum teste (verificado por grep). O dispatcher JSON-RPC não é exercitado — nenhum teste abre o socket Unix.
- **Comandos nunca invocados nos testes:** `status`, `search`, `update`, `models show`, `reindex`, `doctor`.
- **CI** (`.github/workflows/test.yml`): push e PR para `main`, `macos-latest`, `uv sync` + o comando de teste. `release.yml` dispara em tag `v*`, roda a mesma suíte e publica um GitHub Release apenas com changelog gerado de `git log` — **não constrói nem anexa artefato algum**.

### Riscos e limites

- **Código morto a não portar:** tabela `ingestion_jobs` criada e nunca lida nem escrita (`storage.py:80-89`); `runtime.max_concurrency` e `runtime.query_cache_size` parseados, validados e exibidos no `status`, sem nenhum consumidor real; `chunk_document(min_chars=100)` recebe o parâmetro e nunca o usa (`chunking.py:21`).
- **Licença:** `pymupdf` é AGPL-3.0 ou comercial Artifex e é dependência obrigatória (`pyproject.toml:27`), enquanto o projeto declara MIT (`pyproject.toml:7`). Nenhuma outra dependência é copyleft. A reescrita é a oportunidade de resolver a incompatibilidade.
- **Acoplamento a macOS:** `device="mps"` sem fallback em `config.py:327` e `embedder.py:85`; `install.sh:22-26` aborta fora de `arm64`; LaunchAgent em `support/com.vecstash.daemon.plist`.
- **Limites operacionais:** `max_length=512` hardcoded apenas no caminho MLX (`embedder.py:58`) — o caminho `sentence_transformers` usa o default do tokenizer, o que significa que o limite real de tokens hoje não é explícito no código. `top_k` default 5 (`cli.py:267`, `storage.py:298`). Chunking `chunk_size=300, chunk_overlap=50` hardcoded (`chunking.py:23-26`).
- **Sem verificação de integridade** em nenhum ponto: nem no download do modelo (a única validação é o `load()` subsequente não lançar), nem no tarball do updater (`updater.py:78-116`), nem no release workflow.
- **Updater frágil:** `_parse_version` é `tuple(int(x) for x in ver.split("."))` (`updater.py:18-20`); qualquer pré-release faz `int()` lançar `ValueError`, capturado em `:65-66` e convertido silenciosamente em "sem atualização disponível".
- **Working tree:** dois arquivos não rastreados e não ignorados — `.github/copilot-instructions.md` e `src/vecstash/teste.py`. O segundo nunca existiu em nenhum commit (`git log --all` vazio para ele) e é um script Typer autônomo que duplica o `ingest`; é descartável.

### Stack Rust avaliada

Fatos externos levantados em 2026-09-18, para sustentar as decisões:

- **Benchmark de embeddings em Rust** (Apple M4 Max, `all-MiniLM-L6-v2`): `llama-cpp-2` com Metal 1,26ms p50 e 9.676 emb/s em lote; `ort` fp32 1,10ms p50 e 3.052 emb/s; `fastembed` 1,71ms e 2.849 emb/s; `candle` (CPU, 8 threads) 8,15ms e 603 emb/s; `ollama` via HTTP 11,05ms e 433 emb/s. `ort` tem a melhor latência de query única, que é o perfil dominante de um CLI de busca.
- **`ort`:** ONNX Runtime 1.28; feature `coreml` habilita o Execution Provider de CoreML em macOS. É o backend de `fastembed-rs` e do Text Embeddings Inference da HuggingFace.
- **`sqlite-vector-rs` 0.3.1** (julho/2026, MIT ou Apache-2.0): tabela virtual `CREATE VIRTUAL TABLE t USING vector(dim=N, type=float4, metric=cosine)`; tipos `float2/float4/float8/int1/int2/int4`; métricas L2, cosseno e produto interno; HNSW via `usearch ^2` **ou busca exata por força bruta**; grafo persistido em shadow tables `{name}_data` e `{name}_index`, sincronizado a cada 1024 mudanças; usável como extensão carregável, como lib via `rusqlite`, ou como CLI. **Risco: 6 stars no GitHub, 31% da API documentada, mantenedor único.**
- **Modelo escolhido** — `BAAI/bge-m3` em ONNX (`Xenova/bge-m3`): fp32 2,27GB em arquivo de dados externo, fp16 1,13GB, int8 e `quantized` 568–570MB. Dimensão 1024, contexto 8192, backbone XLM-RoBERTa large de 568M parâmetros.
- **Alternativa medida e descartada:** `gte-multilingual-base` ONNX — fp32 1,26GB, fp16 628MB, int8 340MB, 305M parâmetros, 768 dimensões.
- **`hf-hub`:** equivalente Rust de `huggingface_hub`, reutiliza o mesmo layout de cache, com interface bloqueante opcional — permite manter `~/.vecstash/models/hub/`.

## Decisões

**D1 — Backend de embeddings: `ort` (ONNX Runtime), único.**
Alternativa descartada: manter dois backends, ou usar `candle`/`llama-cpp-2`.
Por quê: melhor latência de query única no benchmark; o projeto já sofre com dois backends concorrentes cuja manutenção dobra a superfície de teste sem ganho; `candle` foi o mais lento do benchmark e tem relato aberto de panic no backend Metal.

**D2 — Storage: `sqlite-vector-rs`, substituindo Qdrant embedded.**
Alternativa descartada: `usearch` direto, `LanceDB`, `sqlite-vec`.
Por quê: decisão do usuário. Unifica vetores e metadados em um arquivo só, elimina o `uuid5` que só existia por exigência do Qdrant, e suporta busca exata além de HNSW — adequado ao tamanho real do índice.

**D3 — Escopo V1: os 7 comandos implementados, mais `update`. Sem daemon.**
Alternativa descartada: paridade total incluindo daemon, LaunchAgent, `reindex` e `doctor`.
Por quê: o daemon só responde `healthcheck` e `status`; o preload que o justificava nunca foi entregue, e com startup de milissegundos e mmap do modelo ele perde boa parte da razão de existir. `reindex` e `doctor` nunca foram implementados — não há o que portar.

**D4 — Modelo: `bge-m3` quantizado int8 (570MB), 1024 dimensões.**
Alternativa descartada: `bge-m3` fp32 (2,27GB), `gte-multilingual-base` int8 (340MB).
Por quê: mantém o modelo e a dimensão atuais, então a qualidade de busca não muda de patamar e a documentação existente continua válida. 570MB é folgado nos 16GB do M1; o fp32 usa arquivo de pesos externo, que complica bootstrap e cache.

**D5 — Backup do código Python: diretório `legacy/` no repo.**
Alternativa descartada: branch `legacy-python`, cópia fora do repo.
Por quê: decisão do usuário — consulta direta pelo editor durante a reescrita, sem trocar de branch.

**D6 — Limpeza antes do setup Rust.**
Alternativa descartada: reescrever incrementalmente convivendo com o Python.
Por quê: decisão do usuário. A raiz fica só com a documentação, que serve de referência para a reescrita, e o projeto Rust nasce por cima.

**D7 — Dados existentes são descartados, não migrados.**
Alternativa descartada: escrever um migrador de Qdrant para `sqlite-vector-rs`.
Por quê: o índice tem 264KB de vetores e 40KB de metadados. Re-ingerir custa menos que escrever e testar um migrador.

**D8 — PDF fica fora do V1. Formatos suportados: `.txt`, `.md`, `.markdown`, `.html`, `.htm`.**
Alternativa descartada: `pdfium-render` com Pdfium via bootstrap, `pdf-extract`, `pdf_oxide`.
Por quê: decisão do usuário — PDF exige um fluxo de extração diferente e entra como feature futura, registrada no ROADMAP. Efeito colateral: `pymupdf` (AGPL-3.0) e `pypdf` desaparecem do projeto, e a incompatibilidade com a licença MIT declarada se resolve sozinha no V1. Quando o PDF voltar, a decisão de biblioteca precisa considerar a licença.

**D9 — Storage: tabela `chunks` com `id INTEGER PRIMARY KEY` casando com o `rowid` da tabela virtual; busca exata no V1.**
Alternativa descartada: HNSW desde o início; guardar metadados dentro da tabela virtual.
Por quê: a busca exata é mais precisa, dispensa o grafo HNSW e suas shadow tables sincronizando a cada 1024 escritas, e no volume atual (264KB) é mais rápida. HNSW entra como opção de configuração quando o corpus justificar. O `point_id` derivado de `uuid5` é eliminado — existia apenas porque o Qdrant exige UUID como identificador de ponto (`src/vecstash/storage.py:21-22`).

**D10 — `ort` com `download-binaries` no desenvolvimento; CPU como Execution Provider padrão, CoreML atrás de flag de configuração.**
Alternativa descartada: linkagem estática desde o início; CoreML como padrão.
Por quê: com pesos int8 o CoreML rejeita boa parte dos operadores e cai de volta para CPU, então fixar CoreML agora seria chute. A escolha se decide medindo no M1 alvo com o modelo int8 real. Linkagem estática é problema de distribuição, não de arquitetura, e vira tarefa do ROADMAP.

**D11 — `config.toml` redesenhado; `~/.vecstash/` tratado como instalação nova.**
Alternativa descartada: preservar o formato atual e seus campos.
Por quê: sem daemon (D3), `paths.socket_path` e `model.preload_on_start` perdem sentido; sem segundo backend (D1), `model.backend` também; `runtime.max_concurrency` e `runtime.query_cache_size` nunca tiveram consumidor. Como os dados já são descartados (D7), a compatibilidade preservaria apenas um arquivo de 4KB com cinco campos mortos. Mantidos: o mesmo `data_dir` e o cache de modelos em `models/hub/`, cujo layout o `hf-hub` reaproveita.

**D12 — Chunking por tokens: `text-splitter` com sizer do tokenizer do bge-m3, ~512 tokens e ~64 de overlap, configuráveis.**
Alternativa descartada: manter 300 caracteres com 50 de overlap.
Por quê: 300 caracteres equivalem a 75–100 tokens contra os 8192 de contexto do modelo — cada chunk carrega pouquíssimo contexto e a busca devolve fragmentos. Contar tokens reais elimina o risco de truncamento silencioso, que hoje existe: o caminho `sentence_transformers` não passa `max_length` (`src/vecstash/embedder.py:104-115`), então o limite efetivo não está explícito em lugar nenhum do código.

**D13 — Saída padronizada: todo comando aceita `--json`, sempre compacto em uma linha.**
Alternativa descartada: preservar as idiossincrasias atuais.
Por quê: hoje `models validate` sempre emite JSON ignorando a flag (`cli.py:152-159`), `models show` não aceita `--json`, e `search` é o único que usa `indent=2`. JSON compacto é o que funciona em pipe para `jq`; quem lê com os olhos usa a saída Rich. Exit codes preservados: 0 sucesso, 2 falha de validação.

**D14 — Release constrói binário arm64 no CI, anexa ao GitHub Release com SHA256, e `update` verifica o checksum.**
Alternativa descartada: manter tarball de código-fonte; Homebrew tap no V1.
Por quê: o `release.yml` atual não constrói artefato nenhum — só gera changelog de `git log` —, e o `update` baixa o tarball de fonte para rodar `uv tool install`. Não há verificação de integridade em ponto algum do caminho de distribuição hoje. O binário Rust habilita a correção sem custo adicional. Um tap do Homebrew pode ser somado depois.

**D15 — Versão começa em `0.2.0`, lida por `env!("CARGO_PKG_VERSION")`; `rust-version` declarado no `Cargo.toml`.**
Alternativa descartada: continuar de `0.1.10`; deixar a MSRV implícita.
Por quê: `0.2.0` sinaliza a quebra — stack nova, dados incompatíveis, comandos removidos — e passa por cima do drift atual entre `pyproject.toml` (`0.1.9`) e a tag mais recente (`v0.1.10`) sem precisar reconciliar histórico. A leitura em tempo de compilação elimina o custo de runtime do `importlib.metadata`. MSRV explícita evita que uma atualização de toolchain quebre o build sem aviso.

## Decisões em aberto

Nenhuma. Entrevista concluída em 2026-09-18.

## Fora de escopo

- **Extração de PDF** (decisão D8) — feature futura, registrada no ROADMAP; exige fluxo de extração próprio e uma escolha de biblioteca com licença compatível com MIT.
- Daemon JSON-RPC, socket Unix, `rpc.py` e o LaunchAgent em `support/` (decisão D3).
- `reindex` e `doctor` (decisão D3).
- Backend MLX e qualquer segundo backend de embeddings (decisão D1).
- Migração dos dados do índice atual (decisão D7).
- Tabela `ingestion_jobs` e os campos `runtime.max_concurrency` e `runtime.query_cache_size`, que não têm consumidor no código atual.
- `examples/bun-docs.md`, documentação do Bun sem relação com o projeto.

## Skills recomendadas

- **`rust-style`** — guia de estilo Rust do ambiente (for-loops sobre iteradores, `let-else` para retorno antecipado, shadowing, newtypes, match explícito, comentários mínimos). Aplicável a todo código escrito nesta reescrita.
- **`review-and-simplify-changes`** — revisão de reuso, qualidade e clareza ao fechar cada fase do ROADMAP, com correções seguras aplicadas pelo agente principal.
- **`review-swarm`** — revisão adversarial paralela, somente leitura, antes de mesclar a branch. Vale especialmente no fim: uma revisão de branch inteira encontra o que a revisão por tarefa não vê.

## Recomendações de implementação

Sugestões, não obrigações. Quem implementa pode desviar com motivo.

- **Branch sugerida:** `feature/rust-rewrite`. O `main` permanece com o Python funcionando até o V1 rodar de ponta a ponta; a limpeza da raiz e a criação de `legacy/` acontecem dentro da branch.
- **Testes:** escritos junto da implementação, fase a fase. A suíte Rust deve cobrir as lacunas que a Python tem hoje — `embed()` sem cobertura alguma, `search`/`status`/`update` nunca invocados — e o teste de paridade de vetores é pré-requisito de qualquer declaração de conclusão.
- **Ferramental de teste:** `assert_cmd` para os comandos, `insta` para snapshot das saídas (humana e `--json`), `tempfile` para isolamento por teste, espelhando o padrão de tmpdir que a suíte Python já usa.
- **Ordem sugerida** — derivada das dependências entre as decisões:
  1. Backup em `legacy/` e limpeza da raiz (D5, D6), deixando apenas a documentação.
  2. Esqueleto do crate: `Cargo.toml` com `rust-version` e versão `0.2.0` (D15), `clap` com os 7 comandos declarados e todos retornando "não implementado".
  3. `config` (D11) e `storage` (D2, D9) — com testes; nesta altura `status`, `storage` e `reset` já funcionam de verdade.
  4. `extraction` para `.txt`, `.md`, `.html` (D8) e `chunking` por tokens (D12) — com testes; os 21 casos de `tests/test_extraction.py` são a referência de comportamento a reproduzir, inclusive a linearização de tabelas.
  5. `embed` via `ort` (D1, D4, D10), incluindo `models bootstrap` com `hf-hub`. **Fecha com o teste de paridade contra vetores de referência do Python** — sem ele não há como afirmar que a busca continua correta.
  6. `ingest` e `search` ligando as peças; saída padronizada (D13).
  7. `update` e o workflow de release com binário e SHA256 (D14).
- **Riscos a vigiar durante a implementação:**
  - `sqlite-vector-rs` está em 0.3.1, com 31% da API documentada, 6 stars e mantenedor único. Se a integração travar, a saída é `usearch` direto com os vetores em blob na SQLite — a modelagem de D9 já deixa esse caminho aberto, porque os metadados não dependem da tabela virtual.
  - O bge-m3 usa **CLS pooling** seguido de normalização L2, não mean pooling. Errar isso produz vetores plausíveis e silenciosamente errados — é exatamente o que o teste de paridade existe para pegar.
  - A perda de qualidade da quantização int8 não foi medida neste projeto. Se o teste de paridade contra o fp32 do Python reprovar, fp16 (1,13GB) é o degrau intermediário antes de voltar ao fp32.
