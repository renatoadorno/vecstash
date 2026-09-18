# Referência da CLI

Manual completo dos comandos. Para instalação e visão geral, veja o [README](../README.md).

Flags globais:

- `--config <PATH>` — usa outro `config.toml` em vez de `~/.vecstash/config.toml`
- `--json` — emite uma linha JSON compacta em vez da saída humana, inclusive nos caminhos de erro

Exit codes: `0` sucesso, `1` erro de execução ou ingestão parcial, `2` falha de validação de modelo.

**Streams:** toda a saída humana vai para o **stderr**; o **stdout** carrega apenas o JSON do `--json` e os artefatos de `completions` e `manpage`. Isso mantém `vecstash search ... --json | jq` limpo. `completions` e `manpage` ignoram `--json`.

## ingest

```bash
vecstash ingest <arquivo> [arquivo...]
```

Extrai, divide em chunks, gera embeddings e indexa. Aceita `.txt`, `.md`, `.markdown`, `.html` e `.htm`; qualquer outra extensão é recusada com mensagem explícita.

Os arquivos são extraídos em paralelo. A identidade de um documento é o seu caminho, então reingerir um arquivo — inalterado ou editado — substitui os chunks anteriores em vez de acumular uma segunda cópia.

Se a geração de embeddings falhar para um documento, os metadados ainda são gravados, um aviso vai para o stderr e o campo `indexed` sai como `false` — os demais documentos do lote seguem normalmente.

Exit code: `0` quando tudo foi indexado; `1` quando qualquer arquivo falhou na extração ou no embedding, para que `vecstash ingest *.md && ...` não declare sucesso com o corpus pela metade.

JSON: um objeto com duas listas.

```json
{"indexed":[{"document_id":"…","source_path":"…","source_kind":"md","chunks":3,"indexed":true}],
 "failed":[{"source_path":"…","error":"Unsupported file type '.csv' for …"}]}
```

## search

```bash
vecstash search "<consulta>" [--limit N]
```

`--limit` (ou `-n`) é 5 por padrão. Sai com código 1 quando o índice está vazio.

A saída humana mostra o score e o nome do arquivo, com o trecho renderizado como Markdown. O score é verde acima de 0,8, amarelo acima de 0,5 e vermelho abaixo.

JSON: lista de objetos com `score`, `document_id`, `source_path`, `chunk_index`, `chunk_text`.

## status

```bash
vecstash status
```

Mostra a configuração efetiva e o estado do índice: modelo, arquivo ONNX, execution provider, caminhos, parâmetros de runtime, versão do schema, dimensão dos vetores e as contagens de documentos e chunks.

`vector_dim` é `null` enquanto nada foi indexado.

## storage

```bash
vecstash storage
```

Tamanho em disco do banco, incluindo os arquivos `-wal` e `-shm` do WAL.

## reset

```bash
vecstash reset [--force]
```

Apaga o banco e seus arquivos auxiliares. Sem `--force`, lista o que seria apagado e sai com código 1 sem tocar em nada — com `--json`, isso vira `{"status":"confirmation_required","targets":[…]}`. Não remove os modelos baixados.

É também o comando a rodar quando o binário recusa um índice criado pelo vecstash 0.1.x: os dados do Python não são migrados.

É o que você roda ao trocar de modelo: a dimensão dos vetores fica gravada no índice e uma divergência é recusada.

## models show

```bash
vecstash models show
```

Modelo configurado e se o tokenizer e o arquivo ONNX já estão no cache local.

## models validate

```bash
vecstash models validate [--offline-only]
```

Verifica se o modelo é utilizável. Com `--offline-only` não baixa nada: apenas confere o cache e sai com código 2 se faltar alguma coisa. Sem a flag, baixa o que estiver faltando.

## models bootstrap

```bash
vecstash models bootstrap
```

Baixa o tokenizer e o modelo para `~/.vecstash/models/hub`, no layout de cache do HuggingFace. Cerca de 1,2GB no padrão fp16. Sai com código 2 em falha.

## update

```bash
vecstash update [--check]
```

Consulta a última release no GitHub e compara com a versão atual usando semver — pré-releases são ordenadas corretamente, não silenciosamente ignoradas.

Com `--check`, apenas informa. Sem a flag, baixa o binário e o `.sha256` correspondente, **verifica o checksum** e só então substitui o executável em execução. Se a release não publicar o arquivo de checksum, a instalação é recusada.

JSON: `action` distingue os três desfechos — `up_to_date`, `checked` ou `installed` —, acompanhado de `current_version`, `latest_version`, `update_available` e `release_url`.

## version

```bash
vecstash version
```

## completions

```bash
vecstash completions zsh > "${fpath[1]}/_vecstash"
vecstash completions bash > /usr/local/etc/bash_completion.d/vecstash
```

Aceita `bash`, `zsh`, `fish`, `elvish` e `powershell`. Escreve em stdout.

## manpage

```bash
vecstash manpage > /usr/local/share/man/man1/vecstash.1
```

Gera a página de manual em roff, em stdout.

## Configuração

Seções e campos de `~/.vecstash/config.toml`:

**`[app]`**
- `name` — string não vazia, padrão `"vecstash"`

**`[model]`**
- `name` — repositório HuggingFace, padrão `"Xenova/bge-m3"`
- `onnx_file` — caminho dentro do repositório, padrão `"onnx/model_fp16.onnx"`
- `cache_dir` — padrão `<data_dir>/models`
- `execution_provider` — `"cpu"` ou `"coreml"`, padrão `"cpu"`

**`[paths]`**
- `data_dir` — padrão `~/.vecstash`
- `sqlite_path` — padrão `<data_dir>/metadata.db`
- `log_path` — padrão `<data_dir>/vecstash.log`

**`[runtime]`**
- `max_batch_size` — inteiro positivo, padrão 64
- `chunk_tokens` — inteiro positivo, padrão 512
- `chunk_overlap` — menor que `chunk_tokens`, padrão 64

Todos os caminhos precisam estar dentro de `paths.data_dir`, incluindo `model.cache_dir`, e isso é validado ao carregar. O arquivo é criado com os padrões na primeira execução.

## Logs

`~/.vecstash/vecstash.log` recebe um objeto JSON por linha, com `timestamp`, `level`, `target`, `message` e os campos extras de cada evento.

O nível vem de `VECSTASH_LOG`, no formato do `EnvFilter` do `tracing`. O padrão é `info,ort=warn`: o ONNX Runtime emite algumas centenas de linhas de `INFO` por execução sobre dispositivos e otimização de grafo, que só interessam ao depurar o runtime. Para vê-las:

```bash
VECSTASH_LOG=info vecstash search "termo"
```
