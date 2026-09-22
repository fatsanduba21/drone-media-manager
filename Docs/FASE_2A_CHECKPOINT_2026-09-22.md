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

## Pendente: handoff no Mac real

Esta execução ocorreu no Windows. A montagem OMV, o SQLite e a operação com Windows desligado **não foram validados no Mac**. Execute o checklist em [mac-server.md](operations/mac-server.md) no Mac mini antes de declarar o handoff operacional aceito.
