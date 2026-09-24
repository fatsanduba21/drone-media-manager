# Componentes e schema antes da 3C

Classificação baseada nos chamadores em `src/` e no fluxo oficial descrito em
[CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md). **ACTIVE** é usado pela
produção atual; **LEGACY** pertence à ingestão distribuída ainda presente;
**DEAD** não tem consumidor; **PLANNED** exige referência concreta no roadmap.

| Componente | Estado | Evidência e decisão |
| --- | --- | --- |
| `dmm-organize`, `organize.py`, `sources/FilesystemReadOnlySource`, `ingest/inventory.py`, `ingest/copy.py`, `storage/roots.py` | ACTIVE | `cli/organize.py` chama `build_plan`/`apply_plan`; a origem é somente leitura e o destino é verificado. |
| Catálogo, derivatives, galeria, seleção/download, grouping | ACTIVE | O importador lê `MANIFESTO.json`; API e editorial consomem `catalog_assets`/`asset_files`. |
| `dmm-worker`, worker/jobs/snapshots, API de sources/ingests/jobs/workers | LEGACY | Usam `00_INBOX_ORIGINALS` e não publicam o manifesto editorial do organizador. Mantidos para compatibilidade histórica; fora dos runbooks principais. |
| `run_preflight`, `evaluate_release`, `DestinationPlanner`, `IngestRepository`, `discover_removable_sources` | LEGACY | Não têm chamadores no fluxo de produção; `DestinationPlanner` ainda representa `trips/<slug>-<id>`. Mantidos com os testes legados até a retirada coordenada do subsistema. |
| `IngestService` | DEAD, removido | Nenhum import ou teste o usava; era só um wrapper de `IngestJobHandler`. |
| `ingest/manifest.py` | LEGACY | Seu `IngestManifest` usa `items`, não o contrato editorial `assets`; não alimentar `dmm-catalog` com ele. |

## Tabelas

Migrations históricas `0001_core` a `0007_location_names` são preservadas.
`trips` é compartilhada: o importador é o writer atual, enquanto a API de
ingestão antiga ainda pode gravar nela. Código novo não deve depender das
tabelas legadas listadas abaixo.

| Tabela(s) | Writer atual / histórico | Reader | Estado |
| --- | --- | --- | --- |
| `trips` | `catalog/importer.py` / API de ingestão | catálogo, galeria, editorial / ingestão | ACTIVE compartilhada |
| `catalog_assets`, `asset_files`, `manifest_imports` | `catalog/importer.py` | catálogo, derivatives, galeria, editorial, downloads | ACTIVE |
| `derivatives` | `derivatives/service.py` | galeria | ACTIVE |
| `users`, `user_sessions`, `asset_selections` | CLI de usuário, `api/auth.py`, `catalog/selection.py` | autenticação, seleção, downloads | ACTIVE |
| `location_groups`, `telemetry_tracks`, `grouping_suggestions` | `grouping/repository.py` | editorial e sugestões de nomes | ACTIVE |
| `audit_events` | API e grouping | auditoria | ACTIVE compartilhada |
| `workers`, `jobs` | API de worker/jobs/ingestão | worker, recuperação | LEGACY |
| `source_snapshots`, `source_snapshot_entries`, `ingest_jobs`, `ingest_items` | API de sources/ingests | worker e API de ingestão | LEGACY |
| `media_files` | `IngestRepository.record_verified_media`, sem chamador de produção | nenhum reader de produção | LEGACY, sem gravação no fluxo oficial |
| `media_pairs`, `file_operations` | nenhum writer de produção | nenhum reader de produção | LEGACY, tabelas históricas vazias no fluxo oficial |

Os testes de migration cobrem banco vazio até `head` e atualização de bancos
existentes nas duas branches `0005_gallery_auth`/`0005_grouping`, preservando
dados. Qualquer remoção futura de tabela exige migration nova; não editar as
migrations aplicadas.
