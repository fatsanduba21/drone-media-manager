# Checkpoint da Fase 2A — importação do manifesto

**Data:** 22/09/2026
**Escopo:** somente importação do manifesto da Fase 1 para SQLite. A Fase 2B não foi iniciada.

## Contrato implementado

- `dmm-catalog preview <manifest>` faz validação e consulta o catálogo sem gravar.
- `dmm-catalog import <manifest>` valida o documento inteiro antes de gravar; `--verify-hash` confere todos os arquivos físicos. Os dois comandos exigem migrations no head e usam `DMM_OMV_ROOT`, `DMM_DATABASE_PATH` e a configuração normal do servidor.
- `schema_version=1` é o único aceito. Versões diferentes retornam `UNSUPPORTED_SCHEMA` sem criar linhas.
- `Trip.slug` localiza a viagem. Uma nova viagem usa `nas_rel_path=<slug>`, correspondente a `DMM_OMV_ROOT/<slug>/MANIFESTO.json`; nome incompatível resulta em `CONFLICT`. Se uma Trip compatível já existir, seu `nas_rel_path` é preservado para não alterar o pipeline legado; os arquivos editoriais continuam resolvidos pelos paths do manifesto.
- O catálogo usa `catalog_assets.asset_id` único e `asset_files` com uma linha `ORIGINAL` e, quando pareado, uma linha `SRT`. O pipeline legado `MediaFile`/`IngestItem` permanece separado.
- Os paths usados para abrir mídia vêm apenas de `output.*_relative_path`. Paths absolutos, Windows, traversal e symlinks que escapem da raiz OMV são rejeitados. `source.*_path` permanece informação histórica no JSON e nunca é usado pelo importador.
- Arquivo existente com manifesto `VERIFIED` recebe `AVAILABLE`; arquivo ausente recebe `MISSING`; arquivo presente com status `PLANNED` recebe `UNVERIFIED`. Com `--verify-hash`, conteúdo divergente recebe `HASH_MISMATCH`, que só volta a `AVAILABLE` após uma nova conferência de hash bem-sucedida. Qualquer estado diferente de `AVAILABLE` é contado no resumo e a CLI retorna código 2, mesmo que o catálogo seja persistido.
- Mesmo `asset_id` com hash, path ou classificação incompatível resulta em `CONFLICT`, sem alteração do catálogo. Mesmo trip e hash principal com outro `asset_id` gera aviso `possible duplicate content`, sem merge.
- `manifest_imports` guarda uma linha por importação aceita, com trip, caminho relativo, SHA-256 do manifesto, schema, status, contagem e horário. Conflitos e documentos inválidos não geram evento nessa tabela porque são rejeitados antes da transação de catálogo.

## Schema e migration

`0003_catalog` cria `catalog_assets`, `asset_files` e `manifest_imports`, com FKs restritivas para `trips`, `asset_id` único, `(catalog_asset_id, role)` único, checks de tipo/classificação/estado e índices de consulta. O downgrade para `0002_ingest` remove apenas essas três tabelas. Nenhuma migration anterior foi alterada.

## Aceite Windows com manifesto real

O manifesto de `P:\drone-organizado\teste-fase-1\MANIFESTO.json` foi importado em um **banco SQLite temporário** em `%TEMP%`, nunca no banco operacional. Resultado observado:

| Verificação | Resultado |
| --- | ---: |
| Trip | 1 |
| CatalogAsset | 14 |
| AssetFile | 18 |
| MP4 ORIGINAL / SRT / JPG ORIGINAL | 5 / 4 / 9 |
| INSTAGRAM_9X16 / YOUTUBE_16X9 / FOTOS | 2 / 3 / 9 |
| Paths presentes / `AVAILABLE` | 18 / 18 |
| Segunda importação: assets criados / arquivos criados / conflitos / possíveis duplicados | 0 / 0 / 0 / 0 |
| Eventos `ManifestImport` após duas importações | 2 |

Um arquivo de cada tipo (MP4, SRT e JPG) teve SHA-256 recalculado no caminho OMV e comparado ao manifesto: **3/3 coincidiram**. Os demais 15 tiveram existência verificada nesta execução; o aceite anterior da Fase 1 registrou 18/18 hashes na cópia Windows → OMV. Esta execução não recalculou os 18 hashes.

Gates: `pytest` geral **200 passed, 1 skipped**; `ruff check .` passou; `mypy src` passou; teste de upgrade/downgrade da migration e testes da 2A passaram. `ruff format --check` passou para os arquivos Python novos e alterados da 2A. O check global de formatação continua fora do escopo pela dívida preexistente registrada no aceite da Fase 1. A suíte emite avisos preexistentes de depreciação de FastAPI/Starlette.

## Aceite no Mac real

No Mac mini, o checkout de `codex/phase-2a-mac-integration` foi atualizado pelo GitHub no commit `c9713b5`. Antes da migration, foi criado o backup SQLite `dmm.sqlite3.pre-2a-20260922-193409.bak`. A migration aplicada é `0003_catalog`.

`DMM_OMV_ROOT=/Volumes/VOL1_POOL_SSDs/drone-organizado` aponta para o manifesto real em `teste-fase-1/MANIFESTO.json`. O preview encontrou 14 assets, 18 arquivos disponíveis, nenhum ausente e nenhum conflito. A primeira importação criou 14 assets e 18 arquivos; a segunda criou 0 assets e 0 arquivos, com 14 já importados, 0 conflitos e 0 possíveis duplicados. O preview com `--verify-hash` conferiu os 18 arquivos a partir do Mac e não encontrou divergências.

O SQLite operacional confirmou 1 Trip para `teste-fase-1`, 14 `CatalogAsset`, 18 `AssetFile` disponíveis (5 MP4, 4 SRT, 9 JPG) e 2 eventos `ManifestImport`. O serviço `launchd` foi reiniciado; a checagem local `/health` retornou `healthy` para banco, OMV, `ffmpeg`, `ffprobe` e worker.

Após uma queda de energia, o SSD voltou a montar e `PRAGMA integrity_check` retornou `ok`. O compartilhamento SMB do OMV foi remontado diretamente no Mac; o preview com `--verify-hash` foi repetido e confirmou 18 arquivos disponíveis, sem divergências. O endpoint `/health` acessado remotamente pelo Tailscale voltou a `healthy` para banco, OMV, `ffmpeg`, `ffprobe` e worker. Essa montagem SMB direta e os paths `output.*` usados pelo importador confirmam que o Windows não participa da leitura no Mac. O desligamento físico do Windows não foi testado nesta sessão. Os passos de recuperação estão em [mac-server.md](operations/mac-server.md).
