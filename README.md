# vecstash

Busca semântica local e offline para macOS Apple Silicon. Binário único em Rust, sem Python e sem serviço externo: os vetores e os metadados vivem em um arquivo SQLite, e o modelo de embeddings roda em processo via ONNX Runtime.

## Requisitos

- macOS Apple Silicon (M1 ou superior)
- Rust 1.90+ para compilar a partir do fonte

## Instalação

```bash
git clone https://github.com/renatoadorno/vecstash.git
cd vecstash
cargo install --path .
vecstash models bootstrap
```

O `bootstrap` baixa o modelo (cerca de 1,2GB) para `~/.vecstash/models/hub` e só precisa rodar uma vez.

## Uso

```bash
vecstash ingest notas.md relatorio.html leia-me.txt
vecstash search "como configurar o ambiente" --limit 5
vecstash status
```

Todo comando aceita `--json`, que emite uma linha compacta pronta para `jq`:

```bash
vecstash search "prazo de entrega" --json | jq '.[0].source_path'
```

Comandos disponíveis: `ingest`, `search`, `status`, `storage`, `reset`, `models show`, `models validate`, `models bootstrap`, `update`, `version`, `completions`, `manpage`.

A saída humana vai para o stderr e o stdout carrega só o JSON, então `--json | jq` funciona sem filtro extra.

Formatos suportados na ingestão: `.txt`, `.md`, `.markdown`, `.html`, `.htm`. PDF não entra nesta versão.

## Configuração

O arquivo `~/.vecstash/config.toml` é criado na primeira execução:

```toml
[app]
name = "vecstash"

[model]
name = "Xenova/bge-m3"
onnx_file = "onnx/model_fp16.onnx"
execution_provider = "cpu"

[paths]
data_dir = "~/.vecstash"

[runtime]
max_batch_size = 64
chunk_tokens = 512
chunk_overlap = 64
```

Todos os caminhos precisam ficar dentro de `paths.data_dir`, e isso é validado ao carregar.

`execution_provider` aceita `cpu` ou `coreml`. O padrão é `cpu`; `coreml` despacha para o Neural Engine quando os operadores são suportados, e cai de volta para CPU quando não são.

`onnx_file` escolhe a variante do modelo. O padrão `onnx/model_fp16.onnx` (1,13GB) reproduz os vetores do modelo de referência com similaridade de cosseno de 0,999999. `onnx/model_quantized.onnx` (570MB) é cerca de duas vezes mais rápido, mas a similaridade cai para 0,982 — bom o suficiente para muitos usos, e insuficiente quando a precisão do ranking importa.

**Trocar de modelo exige reindexar:** rode `vecstash reset` e ingira de novo. A dimensão do índice é gravada na primeira ingestão e divergências são recusadas com mensagem explícita.

## Armazenamento

```
~/.vecstash/
  config.toml
  metadata.db      SQLite com documentos, chunks e vetores
  models/hub/      cache de modelos, no layout do HuggingFace
  vecstash.log     log JSON, uma linha por evento
```

## Vindo da versão 0.1.x (Python)

Os dados não são migrados. O binário recusa, com mensagem explícita, tanto um `config.toml` escrito pela versão Python quanto um `metadata.db` criado por ela. Para migrar:

```bash
mv ~/.vecstash/config.toml ~/.vecstash/config.toml.bak
vecstash reset --force
vecstash models bootstrap
vecstash ingest <seus arquivos>
```

O diretório `~/.vecstash/qdrant/` da versão antiga pode ser apagado à mão; o `vecstash` novo não o usa nem o contabiliza.

## Desenvolvimento

Veja [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). O histórico da implementação anterior em Python está em `legacy/python/`, preservado apenas para consulta.

## Licença

MIT. Veja [LICENSE](LICENSE).
