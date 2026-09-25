# Drone Media Manager — análise do codebase, funções por arquivo e potenciais issues

**Data:** 24/09/2026
**Branch/commit analisado:** `main` em `fb3258b` (feat: suggest and confirm location group names)
**Escopo:** leitura integral de `src/`, `scripts/`, migrations, `pyproject.toml`, `.env.example` e da pasta `Docs/`. Nenhum arquivo de código foi alterado.
**Suíte de testes nesta análise:** `pytest tests/unit tests/integration tests/security` → **296 passed, 3 skipped, 153 warnings** (os skips dependem de symlink no Windows; os warnings são depreciações de FastAPI/Starlette).
**Cenário-alvo:** operação somente na **rede local** (LAN).

---

## 1. Resumo executivo

O Drone Media Manager (DMM) organiza material de drone DJI em três máquinas:

| Máquina | Papel |
|---|---|
| **Windows** | Lê a origem (cartão SD, pasta, UNC) sempre em modo somente leitura e copia para o OMV. Existem dois fluxos: o *worker* distribuído (`dmm-worker`) e o organizador editorial da Fase 1 (`dmm-organize`), que **não está na `main`**; veja o issue C1. |
| **OMV (NAS)** | Guarda os originais em `<slug>/<poi>/<categoria>/...` (fluxo editorial) ou em `trips/<slug>/00_INBOX_ORIGINALS/...` (fluxo de ingestão segura). |
| **Mac mini** | Plano de controle com FastAPI e SQLite local. Importa `MANIFESTO.json`, gera thumbnails e proxies, serve a galeria HTTPS com login, seleção persistente e download de originais, e hospeda a triagem editorial (agrupamento por local com sugestões por SRT/GPS e Google Places). |

A implementação está alinhada com os docs até as fases **2D** (seleção e download) e **3A/3B** (agrupamento e nomes). O aceite **2E** (ponta a ponta no MacBook da usuária, com o Windows desligado) segue **pendente**, conforme `Docs/FASE_2D_CHECKPOINT_2026-09-23.md`.

Pontos mais críticos encontrados:

1. **O produtor do `MANIFESTO.json` (`dmm-organize`) não está na `main`.** Ele existe só na branch `codex/phase-1-windows-omv`. A `main` importa manifestos, mas não consegue gerá-los.
2. **O ingest distribuído (worker) não funciona para arquivos grandes.** O lease de 60 s nunca é renovado, e o primeiro `progress` depois de 60 s recebe 409, o que derruba o worker.
3. **Na LAN, a confirmação de ingest fica inutilizável.** A rota `/api/ingests` só aceita pedidos quando o *bind* do servidor é loopback, mas o worker precisa do servidor exposto na LAN.
4. A galeria e o editorial **exigem HTTPS** com certificado confiável. Isso é bom para a segurança, mas numa LAN sem Tailscale exige uma CA própria instalada nos clientes, **inclusive no Python do worker**.

---

## 2. Arquitetura e fluxos

```text
FLUXO EDITORIAL (usado de fato nos aceites 1 → 2D → 3B)
Windows: dmm-organize plan/apply  (branch codex/phase-1-windows-omv, fora da main)
   → cópia verificada para <OMV>/<slug>/<poi>/<CATEGORIA>/...
   → <OMV>/<slug>/MANIFESTO.json (schema 1)
Mac: dmm-catalog preview|import MANIFESTO.json   → SQLite (trips, catalog_assets, asset_files)
Mac: dmm-derivatives generate [--trip]            → cache local (thumbnails JPEG 480px, proxies H.264 720p)
Mac: dmm-server run (HTTPS)                       → /gallery (login, filtros, player, seleção, download)
                                                  → /editorial/ (agrupamento por local, nomes Google Places)

FLUXO DE INGESTÃO SEGURA DISTRIBUÍDA (Fase 0/1 "legado", não integrado ao catálogo)
Windows: dmm-worker pair → submit <pasta> (snapshot relativo, lotes de 500)
Mac:     dmm-server ingest confirm SNAPSHOT --trip TRIP_ID  → cria IngestJob + Job(kind=ingest)
Windows: dmm-worker run → claim → copia .partial → verifica SHA-256 → promove sem sobrescrever
         → <OMV>/trips/<slug>/05_MANIFESTS/ingest_manifest.<id>.json
```

Os dois fluxos usam **contratos de path diferentes**, e o fluxo de ingestão **não alimenta o catálogo** (tabelas `media_files`/`media_pairs` nunca são populadas em produção).

### Estado das fases (docs × código)

| Fase | Doc | Estado no código da `main` |
|---|---|---|
| 0 — Fundação (API, SQLite, worker, leases) | `superpowers/plans/…phase-0…` | Implementada |
| 1 — Ingestão segura distribuída | `operations/safe-ingest.md` | Implementada, com defeitos graves de lease (issue C2) |
| 1 — Organizador Windows → OMV (`dmm-organize`) | `01_FASE_1…v2.md`, `DIAGNOSTICO…` | **Ausente da `main`** (issue C1) |
| 2A — Importação do manifesto | `FASE_2A_CHECKPOINT` | Implementada |
| 2B — Thumbnails e proxies | `FASE_2B_CHECKPOINT`, `operations/derivatives.md` | Implementada |
| 2C — API do catálogo e galeria | `FASE_2C_CHECKPOINT`, `operations/gallery.md` | Implementada |
| 2D — Login, seleção e download | `FASE_2D_CHECKPOINT`, `operations/phase-2d.md` | Implementada |
| 2E — Aceite ponta a ponta | `03_PROMPT_CODEX_FASE_2E…` | **Pendente** |
| 3A — Agrupamento editorial | `operations/grouping.md` | Implementada |
| 3B — Nomes via Google Places | `operations/location-names.md` | Implementada |
| 3C–3H — Movimento, pessoas, scoring, selects, CapCut | `03_FASE_3…` | Não iniciadas |

---

## 3. Comandos (CLI)

| Comando | Arquivo | O que faz |
|---|---|---|
| `dmm-server migrate` | `cli/server.py` | `alembic upgrade head` |
| `dmm-server run` | `cli/server.py` | Verifica a revisão do banco e sobe o Uvicorn (TLS opcional) |
| `dmm-server user create --username X` | `cli/server.py` | Cria um usuário com senha Argon2id (mínimo de 12 caracteres, via prompt oculto) |
| `dmm-server backup [--output P]` | `cli/server.py` → `db/backup.py` | Backup online do SQLite com `integrity_check`, SHA-256 e sem sobrescrever |
| `dmm-server ingest confirm SNAP --trip ID [--revision N]` | `cli/server.py` | Chama `POST /api/ingests` via HTTP |
| `dmm-server ingest status INGEST_ID` | `cli/server.py` | Chama `GET /api/ingests/{id}` |
| `dmm-catalog preview\|import MANIFESTO [--verify-hash]` | `cli/catalog.py` | Valida e importa o manifesto schema 1 |
| `dmm-derivatives generate [--trip SLUG]` | `cli/derivatives.py` | Gera thumbnails e proxies |
| `dmm-worker pair` | `cli/worker.py` | Troca o bootstrap token por um token permanente (keyring) |
| `dmm-worker scan\|ingest --dry-run\|submit <pasta>` | `cli/worker.py` | Inventário, simulação e envio de snapshot |
| `dmm-worker once\|run` | `cli/worker.py` | Um ciclo ou loop contínuo de heartbeat, claim e execução |
| `dmm-worker verify INGEST_ID` | `cli/worker.py` | Consulta o status do ingest |
| `python scripts/install_macos_launchd.py` / `uninstall_…` | `scripts/` | Gera ou remove o plist do LaunchAgent, sem chamar `launchctl` |

---

## 4. Endpoints HTTP

| Método e rota | Autenticação | Função |
|---|---|---|
| `GET /health` | **nenhuma** | Banco, OMV, `ffmpeg -version`, `ffprobe -version` e contagem de workers |
| `POST /api/workers/register` | Bearer = bootstrap token | Registra o worker e devolve um token permanente |
| `POST /api/workers/{id}/heartbeat` | Bearer do worker | Marca ONLINE e grava uma linha de auditoria |
| `POST /api/worker-jobs/claim` | Bearer do worker | Obtém o lease do job PENDING mais antigo compatível |
| `POST /api/worker-jobs/{id}/progress\|complete\|fail` | Bearer do worker + lease token + revisão | Mutação protegida (fenced) do job; espelha o estado no `IngestJob` |
| `POST /api/sources/snapshots` (+ `/entries`, `/finalize`) | Bearer do worker | Snapshot da origem com paths relativos |
| `POST /api/ingests`, `GET /api/ingests/{id}` | **nenhuma**; só funciona com *bind* loopback | Confirmação e consulta de ingest |
| `GET/POST /login`, `POST /logout` | HTTPS + CSRF | Sessão por cookie `__Host-dmm_session` com validade de 12 h |
| `GET /`, `/gallery`, `/gallery/{slug}`, `/gallery/{slug}/assets/{id}` | HTTPS + sessão | Galeria renderizada no servidor |
| `POST /gallery/{slug}/assets/{id}/selection` | HTTPS + sessão + CSRF (formulário) | Marca ou desmarca seleção |
| `GET /api/catalog/trips[/{slug}[/assets]]`, `/assets/{id}` | HTTPS + sessão | Catálogo em JSON |
| `GET /api/catalog/assets/{id}/thumbnail\|proxy` | HTTPS + sessão | Derivados READY (ETag, Range) |
| `GET /api/catalog/assets/{id}/download` | HTTPS + sessão | Original do OMV como anexo |
| `GET /api/catalog/trips/{slug}/selected-downloads` | HTTPS + sessão | Pré-verificação do lote selecionado |
| `PUT /api/catalog/assets/{id}/selection` | HTTPS + sessão + `X-CSRF-Token` | Seleção via API |
| `GET /editorial/` | HTTPS + sessão | Página estática `editorial.html` com o CSRF injetado |
| `GET /api/editorial/trips[/{id}]`, `/assets/{id}/thumbnail`, `/trips/{id}/name-suggestions` | HTTPS + sessão | Estado da triagem |
| `POST /api/editorial/trips/{id}/analyze`, `POST …/groups`, `PUT …/groups/{gid}`, `PATCH …/groups/{gid}/name` | HTTPS + sessão + CSRF | Sugestões e grupos |

---

## 5. Modelo de dados (SQLite, migrations 0001 → 0007)

| Migration | Tabelas |
|---|---|
| `0001_core` | `workers`, `jobs`, `audit_events` |
| `0002_ingest` | `trips`, `source_snapshots`, `source_snapshot_entries`, `ingest_jobs`, `ingest_items`, `media_files`, `media_pairs`, `file_operations` |
| `0003_catalog` | `catalog_assets`, `asset_files`, `manifest_imports` |
| `0004_derivatives` | `derivatives` (único por asset e tipo) |
| `0005_gallery_auth` | `users`, `user_sessions`, `asset_selections` |
| `0005_grouping` | `location_groups`, `telemetry_tracks`, `grouping_suggestions` (+ `catalog_assets.location_group_id`) |
| `0006_merge_2d_3a` | Revisão de união dos dois ramos 0005 |
| `0007_location_names` | `location_groups.provider_place_id` |

`media_files`, `media_pairs` e `file_operations` existem no schema, mas **nenhum código de produção grava nelas**.

---

## 6. Funções por arquivo

### 6.1 Raiz do pacote

- **`config.py`**
  - `ServerSettings`: variáveis `DMM_*` e `GOOGLE_MAPS_API_KEY`.
    - `empty_tls_path_is_none`
    - `bootstrap_token_is_long_enough` (mínimo de 32 caracteres)
    - `validate_server_safety`: banco local, fora do OMV e das raízes sincronizadas; cache de derivados fora do OMV; TLS em par; bind não loopback exige TLS ou `ALLOW_INSECURE_LAN`.
  - `WorkerSettings`: URL, nome, `omv_root`, `snapshot_registry_path`, `poll_seconds` e `heartbeat_seconds` (os dois últimos não são usados; veja M4).
  - `get_server_settings`, `get_worker_settings`, `_is_loopback_host`.
- **`logging.py`**: `JsonLogFormatter` (JSON estruturado), `_redact`/`_is_sensitive_key` (mascaram tokens, segredos e GPS), `configure_logging` (stderr e arquivo rotativo opcional via `DMM_LOG_PATH`).
- **`time.py`**: `utc_now`.

### 6.2 `api/`

- **`app.py`**
  - `BoundedBodyMiddleware`: limita o corpo das requisições a 1 MiB (413).
  - `create_app`: registra os routers, os handlers de erro (formato `{"error": {...}}`), a recuperação de leases no startup e o `browser_gate`.
- **`auth.py`**
  - `BrowserIdentity`, `browser_identity` (resolve o cookie numa sessão válida).
  - `require_browser_identity`, `require_csrf` (Origin + token), `_require_https`, `_form_fields`.
  - `LoginThrottle`: 5 falhas em 15 min por IP e por IP+usuário, em memória.
  - `auth_router`: `/login` (GET/POST) e `/logout`.
  - `browser_gate`: middleware que exige HTTPS e sessão em `/gallery*`, `/editorial*`, `/api/catalog/*` e `/api/editorial/*`.
- **`dependencies.py`**
  - `require_worker`: token comparado ao digest do worker nomeado.
  - `require_authenticated_worker`: procura o token entre todos os workers.
- **`gallery.py`**
  - HTML e CSS inline: `_page`, `_duration`, `_label`, `_field`, `_select`, `_selection_form`, `_size_label`, `_download_link`, `_batch_panel` (inclui um JS de download múltiplo), `_card`.
  - `gallery_router`: `/`, `/gallery`, `/gallery/{slug}`, `/gallery/{slug}/assets/{id}`.
- **`routes/catalog.py`**
  - `_trip`, `_trip_payload`, `_matches`, `_assets` (filtros), `_asset`, `_asset_payload`.
  - `_ready_path`: valida o derivado READY (perfil, path canônico, tamanho).
  - `_byte_range`, `catalog_router`.
- **`routes/downloads.py`**: `_content_disposition` (ASCII com fallback e `filename*`), `_file_response`, `selected_originals`, `downloads_router`.
- **`routes/editorial.py`**
  - `RangeRequest`, `GroupUpdateRequest` (modos add/replace), `GroupNameRequest`, `_group_data`.
  - `editorial_router`: página, trips, estado, thumbnail, analyze, name-suggestions, criação, edição e renomeação de grupo.
- **`routes/health.py`**: `health_router`, `_database_status`, `_omv_status`, `_worker_summary`, `_dependency_payload`, `_is_healthy`.
- **`routes/ingests.py`**
  - `_require_localhost_admin`, `_response`.
  - `ingest_router`: `confirm_ingest` cria o `IngestJob`, os itens e o `Job`, com idempotência por trip+fingerprint.
  - `_destination_path` (`trips/<slug>/00_INBOX_ORIGINALS/...`), `_partial_path`.
- **`routes/jobs.py`**
  - `_audit_hook`: auditoria e status do worker.
  - `_authenticate`, `_sanitize_error`, `_mutation_response`.
  - `job_router`: claim, progress, complete e fail.
  - `_update_ingest_state`: espelha o Job no IngestJob.
- **`routes/selection.py`**: `SelectionChange`, `selection_router` (PUT via API e POST via formulário).
- **`routes/sources.py`**: `_response`, `_fingerprint`, `_owned_snapshot`, `_draft`, `source_router` (create, entries, finalize), `_unique_entries`.
- **`routes/workers.py`**: `bearer`, `BearerCredentials`, `worker_router` (register, heartbeat).
- **`schemas/*.py`**: modelos Pydantic estritos (`extra="forbid"`).
  - Workers: `WorkerRegistration`, `WorkerHeartbeat*`.
  - Jobs: `ClaimRequest` (lease de 5 a 3600 s), `ProgressRequest`, `CompleteRequest`, `FailRequest`.
  - Snapshots: `Snapshot*Request`, com validação de path relativo.
  - Ingest: `IngestConfirmationRequest`, `IngestResponse`.
- **`static/editorial.html`**: SPA em JS puro.
  - Seleção por clique e Shift+clique; funções `range`, `selectionBounds`, `suggestNames`, `render`, `loadState`, `createGroup`, `updateGroup`, `action`.
  - Monta o DOM com `textContent`, o que protege contra XSS.

### 6.3 `auth/`

- **`passwords.py`**: `hash_password` e `verify_password` (Argon2id; t=2, m=19 MiB, p=1).

### 6.4 `catalog/`

- **`importer.py`**
  - `ManifestError`, `ParsedManifest`, `ImportReport`, `_FilePlan`.
  - `resolve_omv_path`: bloqueia path absoluto, formato Windows, `..` e escape por symlink.
  - Validadores: `_object`, `_nonempty`, `_sha`, `_relative`.
  - `load_manifest`: valida o documento inteiro antes de gravar.
  - `_file_state` (AVAILABLE, MISSING, UNVERIFIED, HASH_MISMATCH), `_plans`, `_preview` (conflitos e duplicados).
  - `preview_manifest`, `import_manifest` (transacional).
- **`downloads.py`**
  - `OriginalDownload`, `safe_filename` (Unicode seguro para macOS e Windows, nomes reservados).
  - `_editorial_name`: desambigua nomes repetidos com um sufixo do asset_id.
  - `resolve_original`: só aceita ORIGINAL AVAILABLE sob o OMV, com extensão e tamanho coerentes.
- **`selection.py`**: `is_selected`, `selected_count`, `set_selected` (upsert SQLite idempotente).

### 6.5 `cli/`

- **`server.py`**: `_parser`, `AdminIngestClient` (HTTP para `/api/ingests`), `alembic_config`, `verify_database_revision`, `migrate`, `run`, `main`.
- **`catalog.py`**: `main` (preview/import; sai com código 2 em conflito ou disponibilidade parcial).
- **`derivatives.py`**: `main`.
- **`worker.py`**: `_parser`, `_inventory`, `_print_inventory`, `_authenticated_client`, `_snapshot_entries`, `_submit`, `main`.

### 6.6 `db/`

- **`session.py`**: `create_engine_from_settings` (revalida as settings; ativa `foreign_keys`, `busy_timeout=5000` e WAL), `session_factory` (`expire_on_commit=False`).
- **`backup.py`**: `BackupError`, `BackupReport`, `_sha256`, `backup_sqlite` (API de backup do sqlite3, `integrity_check`, fsync, publicação via `os.link` sem sobrescrever).
- **`base.py`**: `Base`.
- **`models/core.py`**: `Worker`, `Job`, `AuditEvent`.
- **`models/ingest.py`**: `Trip`, `SourceSnapshot`, `SourceSnapshotEntry`, `IngestJob`, `IngestItem`, `MediaFile`, `MediaPair`, `FileOperation`.
- **`models/catalog.py`**: `CatalogAsset`, `AssetFile`, `ManifestImport`, `Derivative`.
- **`models/auth.py`**: `User`, `UserSession`, `AssetSelection`.
- **`migrations/env.py`**: `validated_server_settings`, `run_migrations_offline` e `run_migrations_online`.
- **`migrations/versions/*`**: `upgrade` e `downgrade` de cada revisão (seção 5).

### 6.7 `derivatives/`

- **`service.py`**
  - `PROFILES` (`grid-v1`, `web-720p-v1`), `Renderer` (Protocol), `_sha256`, `_probe` (ffprobe).
  - `FFmpegRenderer.render`: Pillow com EXIF para fotos; ffmpeg para o thumbnail de vídeo e para o proxy H.264/AAC 720p com faststart.
  - `FFmpegRenderer.valid`: valida JPEG até 480 px e o proxy h264/yuv420p até 720 px.
  - `GenerationReport`, `_record`.
  - `generate_derivatives`: reutiliza por hash e perfil; grava num temporário e aplica `os.replace`; faz um commit por tipo.

### 6.8 `domain/`

- **`enums.py`**: `SourceKind`, `PairStatus`, `IngestStatus`, `IngestItemStatus`, `JobStatus`, `WorkerStatus`.
- **`errors.py`**: `StaleRevision`, `InvalidTransition`, `LeaseConflictReason`, `LeaseConflict`.

### 6.9 `grouping/` (Fase 3A/3B)

- **`models.py`**: `LocationGroup`, `TelemetryTrack`, `GroupingSuggestion`.
- **`telemetry.py`**: `TelemetrySummary`, `parse_srt` (lat/lon/data no formato DJI `[latitude: …]`).
- **`service.py`**
  - `ClipSignal`, `SuggestedRange`.
  - `sequence_number` (DJI_/VID_/IMG_/DSC_), `natural_key`, `_distance` (haversine).
  - `suggest_ranges`: quebra sequências por salto de numeração, pausa acima de 30 min ou distância GPS acima de 500 m.
- **`repository.py`**
  - `ordered_assets` (ordem natural por nome do arquivo), `_original_files`, `_timestamp`.
  - `_summary`: parseia o SRT e guarda o resultado em `telemetry_tracks`.
  - `analyze_trip`: substitui as sugestões anteriores sem tocar nos grupos.
  - `assign_range` (cria ou atualiza grupo; modos add/replace; audita), `range_center`, `rename_group`.
- **`names.py`**
  - `NameCandidate`, `LocationProvider`.
  - `GooglePlacesProvider.suggest_names`: Places API (New), Nearby Search, 5 resultados, pt-BR, timeout de 3 s.
  - `NameLookup`: cache de 5 min com até 256 entradas; qualquer erro vira lista vazia.

### 6.10 `ingest/` (fluxo distribuído)

- **`copy.py`**
  - `PartialPrefixMismatch`, `CopyItem`, `CopyOutcome`.
  - `CopyEngine.copy_or_resume`: blocos de 8 MiB com fsync, retoma a partir de um prefixo verificado e detecta mudança na origem.
  - `_assert_prefix`.
- **`fingerprint.py`**: `fingerprint_inventory` (SHA-256 dos metadados).
- **`inventory.py`**: `InventorySource`, `InventoryItem`, `Inventory`, `build_inventory` (**somente `.mp4` e `.srt`**), `_inventory_item`, `_entry_sort_key`, `_group_sort_key`, `_normalized_path`.
- **`manifest.py`**: `ManifestItem`, `IngestManifest`, `ManifestWriteResult`, `build_manifest`, `write_manifest_atomic` (link sem sobrescrever).
- **`verify.py`**: `VerificationResult`, `verify_copy` (hash independente da origem e do destino; compara `stat`), `hash_file`, `_source_details`, `_path_stat`, `_hash_file`.
- **`promote.py`**: `PromotionResult`, `promote_no_replace` (`os.link` + `unlink`), `_resolve_existing`.
- **`preflight.py`**: `PreflightPolicy`, `PreflightError`, `PreflightReport`, `run_preflight`, `_probe_destination`. **Não é chamado em produção.**
- **`release_policy.py`**: `BackupPolicy`, `ReleaseDecision`, `evaluate_release`, `_backup_verified`. **Não é chamado em produção.**
- **`repository.py`**: `IngestRepository` (`create_snapshot`, `confirm_ingest`, `transition_ingest`, `checkpoint_item`, `record_verified_media`). **Não é usado em produção**; a API grava direto.
- **`service.py`**: `IngestService.execute_claimed`. **Não é usado.**

### 6.11 `jobs/`

- **`repository.py`**
  - `ClaimedJob`, `_utc`, `_snapshot`.
  - `JobRepository`: `claim`, `_owned_job`, `renew` (**sem rota HTTP**), `progress`, `interrupt_expired`, `complete`, `fail`, `_finish`, `reconcile` (**sem rota nem CLI**).
  - Todas as operações usam `BEGIN IMMEDIATE`.
- **`recovery.py`**: `RecoveryReport`, `recover_on_startup` (interrompe leases expirados **só no startup**).
- **`transitions.py`**: `assert_job_transition` (grafo PENDING → LEASED → RUNNING → COMPLETE/FAILED/INTERRUPTED, e INTERRUPTED → PENDING).

### 6.12 `sources/` e `storage/`

- **`sources/discovery.py`**: `FilesystemReadOnlySource` (`iter_files`, `open_read`, `stat`), `discover_removable_sources` (**não usada**), `source_from_explicit_path`, `_descriptor_for_root`, `_iter_removable_roots` (Win32), `_mapped_unc_identity` (WNetGetConnectionW).
- **`sources/models.py`**: `CanonicalSourceRoot`, `SourceStat`, `SourceDescriptor`, `SourceEntry`.
- **`sources/paths.py`**: `UnsafeSourcePath`, `canonicalize_source_root`, `validate_source_entry`, `_source_identity`, `_has_embedded_windows_absolute_path`, `_reject_escaping_reparse_point`.
- **`sources/read_only.py`**: `ReadOnlySource` (Protocol).
- **`storage/roots.py`**: `UnsafePath`, `LogicalMediaPath.parse`, `RootMapper.to_host_path`/`to_relative`.
- **`storage/destination.py`**: `TripDestination`, `PlannedDestination`, `DestinationPlanner.plan` (**não usada**; usa `trips/<slug>-<id>/...`, diferente da API).
- **`storage/capacity.py`**: `Capacity`, `CapacityProbe`, `FilesystemCapacity`.

### 6.13 `system/` e `worker/`

- **`system/dependencies.py`**: `DependencyStatus`, `probe_executable` (`-version` com timeout de 5 s).
- **`worker/client.py`**
  - `WorkerTransportError`, `WorkerProtocolError`, `WorkerApiError`.
  - `WorkerApiClient`: `register`, `heartbeat`, `create_snapshot`, `append_snapshot_entries`, `finalize_snapshot`, `get_ingest`, `claim` (lease padrão de 60 s), `progress`, `complete`, `fail`.
  - `_response_code`, `_run_with_deadline`.
- **`worker/credentials.py`**: `CredentialStore` (keyring do sistema operacional).
- **`worker/snapshots.py`**: `LocalSnapshotRegistry` (mapeia snapshot para a raiz local; persiste em JSON), `default_snapshot_registry`.
- **`worker/service.py`**: `WorkerApi`, `PollResult`, `WorkerService.run_once`/`run_forever`, `_ApiProgressReporter`, `_payload_bytes_total`.
- **`worker/handlers/ingest.py`**: `JobExecutionResult`, `IngestJobHandler.execute`, `_process_item`, `_write_manifest`, `_report`.

### 6.14 `scripts/`

- **`install_macos_launchd.py`**: `managed_plist_path`, `build_plist` (`KeepAlive`, `RunAtLoad=False`), `install`, `main`.
- **`uninstall_macos_launchd.py`**: `uninstall` (exige `--yes`), `main`.

---

## 7. Potenciais issues

Classificação: **C** = crítico (impede o uso ou arrisca dados), **A** = alto, **M** = médio, **B** = baixo ou cosmético.

### 7.1 Críticos

**C1. O organizador da Fase 1 (`dmm-organize`) não está na `main`.**
`cli/organize.py`, `organize.py` e seus testes existem só na branch `codex/phase-1-windows-omv` (commits `a2b97db` e `1a1de0b`), que não é ancestral da `main`. Ainda sobra `src/drone_media_manager/__pycache__/organize.cpython-313.pyc` no disco.
A `main` consome `MANIFESTO.json` (`dmm-catalog`), mas não tem como produzi-lo. Uma instalação limpa a partir da `main` não processa uma nova viagem ponta a ponta.

**C2. O lease do job de ingest nunca é renovado; ingest acima de ~60 s falha.**
- `WorkerApiClient.claim` usa `lease_seconds=60`.
- `JobRepository.progress` **não estende** `lease_expires_at`.
- `renew()` existe, mas não tem rota HTTP.
- `_owned_job` rejeita com `expired_lease` (409) depois de 60 s.

Cada bloco de 8 MiB envia `progress`, então um único MP4 de 4 GB leva bem mais de 60 s pela rede e falha. Além disso, `WorkerService` injeta `lease_valid=lambda: True`, e o worker não percebe que perdeu o lease.

**C3. Exceções no worker derrubam o processo e deixam o job preso.**
`run_once` só captura `WorkerTransportError`. Ficam sem tratamento:
- `WorkerApiError` (C2);
- `KeyError` quando o snapshot não está no registro local;
- `UnsafeSourcePath`;
- `OSError` em `os.link`/SMB.

O job fica em LEASED/RUNNING. `interrupt_expired` só roda no **startup do servidor**, e `claim` recusa novos jobs enquanto o worker tiver um ativo. Resultado: o worker fica ocioso até o Mac reiniciar.

**C4. Jobs INTERRUPTED ou FAILED não podem ser retomados.**
- INTERRUPTED → PENDING depende de `JobRepository.reconcile`, que não tem rota nem CLI.
- FAILED é terminal.
- `POST /api/ingests` devolve o `IngestJob` existente para a mesma trip+fingerprint, sem criar um novo `Job`.

Uma falha transitória (por exemplo, `source_changed` ou erro de rede) deixa a mesma origem impossível de reprocessar, a não ser mexendo manualmente no SQLite.

### 7.2 Altos

**A1. Na LAN, a confirmação de ingest fica bloqueada e desprotegida ao mesmo tempo.**
`_require_localhost_admin` testa `settings.bind_host`, não o IP de quem fez o pedido.
- Para o worker Windows alcançar o Mac, o bind precisa ser LAN; aí `POST /api/ingests` sempre responde 403, e `dmm-server ingest confirm` e `dmm-worker verify` não funcionam.
- Com bind loopback e um proxy reverso na frente (nginx, `tailscale serve`), a rota passa a aceitar **qualquer cliente sem autenticação**.

Além disso, `AdminIngestClient` monta a URL com `bind_host` (`https://0.0.0.0:…` não resolve e não bate com o nome do certificado).

**A2. HTTPS é obrigatório para galeria e editorial; numa LAN sem Tailscale isso exige uma CA própria.**
O `browser_gate` responde 426 para HTTP, e `DMM_ALLOW_INSECURE_LAN=true` **não** libera a galeria. Os docs só descrevem o certificado do Tailscale. Numa LAN pura é preciso:
- gerar um certificado para um nome DNS local (por exemplo, `mac-mini.lan`), com `mkcert` ou uma CA própria;
- instalar a CA no MacBook, no Chrome e no Safari;
- configurar o worker. O `httpx` do worker usa o bundle `certifi`, **não** o repositório de certificados do Windows, então é preciso definir `SSL_CERT_FILE` com o caminho da CA.

Se o servidor ficar atrás de um proxy que termina TLS, `request.url.scheme` vira `http` e tudo responde 426, a menos que o Uvicorn receba `--proxy-headers` e `forwarded_allow_ips`, e `run()` não expõe essas opções.

**A3. O inventário do worker ignora fotos e outros formatos.**
`build_inventory` filtra só `.mp4`/`.srt`. JPG, JPEG, DNG, `.LRF` e `.MOV` do cartão **nunca são copiados** pelo ingest seguro, e o scan não avisa. Diferente do organizador da Fase 1, não existe lista de `unsupported`.

**A4. A galeria tem custo O(n²) e faz muito I/O no SMB a cada página.**
Para cada card em `/gallery/{slug}`:
- `_asset_payload` faz 2 consultas de derivado, `stat` no cache, consulta o slug e o `is_selected`;
- `_download_link` chama `resolve_original`, que faz `stat` do original **no OMV via SMB**;
- `_editorial_name` **carrega todos os originais da viagem** e roda `safe_filename` em cada um.

`_batch_panel` repete o trabalho para os selecionados, e não há paginação. Com mais de 1.000 assets a página fica lenta, e com o OMV offline cada `stat` pode travar até o timeout do SMB. O mesmo vale para `GET /api/catalog/trips/{slug}/assets`.

**A5. Heartbeat e claim a cada 2 s, com uma linha de auditoria por heartbeat.**
`run_forever` usa `delay = 2.0` quando está ocioso; `poll_seconds` e `heartbeat_seconds` são **ignorados**. Cada heartbeat grava um `AuditEvent` e incrementa `worker.revision`.

São cerca de 43 mil linhas por dia por worker, sem nenhuma rotina de limpeza. O `audit_events` cresce sem limite, as escritas no SQLite são constantes e os backups ficam cada vez maiores. Cada `progress` (a cada 8 MiB) também gera auditoria e uma transação `BEGIN IMMEDIATE`.

**A6. O cliente do worker lê a chave errada nas respostas de erro.**
A API devolve `{"error": {"code": …}}`, mas `_response_code` procura `detail`. Todos os erros viram `request_failed`, e o operador perde o diagnóstico (`expired_lease`, `snapshot_expired` etc.).

### 7.3 Médios

- **M1. `/health` não tem autenticação e dispara subprocessos.** Cada chamada executa `ffmpeg -version` e `ffprobe -version` (timeout de 5 s cada). Qualquer host da LAN pode fazer requisições em sequência e consumir CPU e threads. A resposta também expõe a quantidade de workers.
- **M2. O bootstrap token é estático e sem limite.** Quem tiver o token registra quantos workers quiser, com quaisquer capabilities e sem rate limit. Não existe revogação ou remoção de worker (nem de token) por CLI ou API.
- **M3. O fim de um ingest não é verificado pelo servidor.** `job.complete` marca **todos** os `IngestItem` como VERIFIED e copia `bytes_copied = source_size_bytes`, com base só na palavra do worker. Hashes e manifesto não voltam ao SQLite (`source_sha256`/`destination_sha256` ficam nulos).
- **M4. Configurações sem efeito.** `DMM_POLL_SECONDS` e `DMM_HEARTBEAT_SECONDS` aparecem no `.env.example`, mas não são usadas (veja A5).
- **M5. `expires_at` do snapshot vem do cliente.** O worker pode enviar qualquer data (inclusive anos à frente), e não há teto no servidor.
- **M6. Hard link em compartilhamento SMB.** `promote_no_replace`, `write_manifest_atomic` e `backup_sqlite` usam `os.link`. No Windows gravando no OMV via Samba, hard link pode não ser suportado (depende da configuração do Samba e do sistema de arquivos) e gera `OSError`, que, pelo C3, derruba o worker. Convém validar no ambiente real.
- **M7. `dmm-derivatives generate` é pesado.** Recalcula o SHA-256 **de todo original** (lido do OMV) e de todo derivado a cada execução, mesmo quando só reutiliza. ffmpeg e ffprobe rodam sem timeout, então um arquivo corrompido pode travar o processo. O hash da origem também não é comparado com `AssetFile.sha256`, e um original corrompido geraria proxy sem aviso.
- **M8. Sessões e seleções não têm manutenção.** Linhas de `user_sessions` expiradas ou revogadas nunca são apagadas. Não existe CLI para trocar senha, remover usuário ou revogar todas as sessões. Todo usuário logado pode editar grupos editoriais (não há papéis).
- **M9. `LoginThrottle` fica só em memória e zera no restart.** Um login bem-sucedido limpa o contador do IP inteiro. Atrás de NAT ou proxy, todos os clientes aparecem com o mesmo IP.
- **M10. `analyze` e `name-suggestions` rodam de forma síncrona na requisição.** Leem todos os SRT do OMV e chamam o Google Places (3 s) dentro do handler. A API do Places recebe coordenadas GPS, o que é uma questão de privacidade (documentada). `NameLookup` guarda em cache uma lista vazia por 5 min após falha transitória.
- **M11. A gestão de grupos está incompleta.** Não é possível excluir grupo, e grupos vazios continuam listados. O modo `add` move silenciosamente assets de outros grupos.
- **M12. O parser SRT só entende um formato.** Ele aceita `latitude: x`/`longitude: y`. Modelos DJI antigos usam `GPS(lon,lat,alt)` e ficam sem telemetria, sem aviso.
- **M13. O registro de snapshots fica relativo ao diretório atual.** O padrão `.dmm-worker-snapshots.json` é relativo ao CWD; rodar `dmm-worker run` de outro diretório (por exemplo, como serviço) perde o mapeamento, e o job falha com `KeyError` (C3). O arquivo guarda paths absolutos da origem sem proteção.

### 7.4 Baixos, dívida técnica e código morto

- **B1. Código não usado em produção:** `run_preflight`, `evaluate_release`, `DestinationPlanner`, `IngestRepository`, `IngestService`, `discover_removable_sources`, e as tabelas `media_files`, `media_pairs` e `file_operations`. A política de liberação do cartão, descrita nos docs, não aparece em nenhuma interface.
- **B2. Contratos de path divergentes:** `trips/<slug>/00_INBOX_ORIGINALS` (API), `trips/<slug>-<id>/…` (`DestinationPlanner`) e `<slug>/<poi>/<cat>` (catálogo).
- **B3. Estado incorreto em falha de cópia:** `_process_item` informa `lease_expired` quando o `CopyEngine` interrompe por **mudança na origem**.
- **B4. Retorno silencioso na CLI de usuário:** `dmm-server user create` retorna 2 sem mensagem quando o `--username` falta ou é inválido.
- **B5. Revisão fixa:** `--revision` do `ingest confirm` tem padrão 2 fixo.
- **B6. API depreciada:** `@app.on_event("startup")` é depreciado no FastAPI (usar `lifespan`).
- **B7. Buffer duplicado de corpo:** `BoundedBodyMiddleware` guarda o corpo inteiro de toda requisição, inclusive GET, antes do roteamento. É inofensivo com o limite de 1 MiB, mas duplica buffer.
- **B8. `KeyError` possível em `trip_state`:** o editorial faz `originals[asset.id]` sem verificar; um asset sem ORIGINAL gera erro 500. O importador sempre cria ORIGINAL, então é improvável.
- **B9. Formatação e lint pendentes:** existem linhas acima do limite em `catalog.py` e `health.py`. O diagnóstico anterior registrou que `ruff format --check .` global falhava.
- **B10. Organização de documentação:** `Docs/` mistura roadmap, prompts do Codex, checkpoints e runbooks. Vários runbooks (`gallery.md`, `derivatives.md`) mostram comandos `http://127.0.0.1:8000`, que não funcionam depois da 2D (HTTPS obrigatório); `gallery.md` avisa isso, `derivatives.md` não.

---

## 8. Recomendações para rodar só na rede local

1. **Defina qual fluxo de ingestão será usado.** Hoje o fluxo que alimenta o catálogo é o `dmm-organize`. Faça o merge de `codex/phase-1-windows-omv` na `main` (C1), ou documente que o Windows deve usar aquela branch. O worker distribuído só deve ser usado depois de corrigir C2 a C4 e A3.
2. **Nome e TLS.** Dê ao Mac um nome fixo (reserva DHCP e DNS local, ou mDNS `mac-mini.local`). Gere um certificado com `mkcert` para esse nome, instale a CA no MacBook e no Windows, e defina `SSL_CERT_FILE` no worker. Configure `DMM_BIND_HOST` com o IP da LAN, e `DMM_TLS_CERTFILE`/`DMM_TLS_KEYFILE`. Mantenha `DMM_ALLOW_INSECURE_LAN=false`.
3. **Firewall.** Libere a porta 8000 do Mac apenas para a sub-rede local (ou apenas para os IPs do MacBook e do Windows). `/health`, `/api/workers/register` e `/api/ingests` não têm autenticação de usuário.
4. **Operações administrativas locais.** Enquanto A1 existir, faça a confirmação de ingest com uma segunda instância temporária em `127.0.0.1` ou ajuste o código para checar `request.client.host`. Não use proxy reverso na frente sem autenticação.
5. **SQLite e OMV.** Mantenha o banco e o cache de derivados no disco local do Mac (a configuração já exige). Rode `dmm-server backup` antes de cada migration. No Mac mini, lembre da permissão do macOS para o `uv` acessar o volume (`Docs/operations/phase-2d.md`).
6. **Crescimento do banco.** Com o worker ativo, monitore `audit_events` (A5). Crie uma rotina de limpeza ou reduza a auditoria dos heartbeats.
7. **Google Places.** Opcional. Sem `GOOGLE_MAPS_API_KEY`, tudo funciona offline e a nomeação é manual.

---

## 9. Evidências e referências

- Suíte: `.venv/Scripts/python.exe -m pytest tests/unit tests/integration tests/security -q -p no:cacheprovider` → 296 passed, 3 skipped (24/09/2026).
- Dependências travadas (`uv.lock`): FastAPI 0.141.1, Starlette 1.6.0 (suporta Range em `FileResponse`), SQLAlchemy 2.0.54, Pydantic 2.13.5, Uvicorn 0.53.0.
- Branch do organizador: `git merge-base --is-ancestor 1a1de0b main` → não é ancestral.
- Documentos lidos:
  - Roadmap e fases: `00_ROADMAP_PRIORIZADO_v2.md`, `01_FASE_1_HOJE_CLASSIFICACAO_E_NAMING_v2.md`, `02_FASE_2_OMV_MAC_GALERIA_SELECAO_DOWNLOAD.md`, `03_FASE_3_INTELIGENCIA_EDITORIAL_E_ORGANIZACAO_AUTOMATICA.md`.
  - Diagnóstico e checkpoints: `DIAGNOSTICO_FUNCIONAL_E_PRIORIDADES.md`, `FASE_2A…2D_CHECKPOINT_*.md`, `PHASE_2D_DOWNLOAD_DESIGN.md`, `03_PROMPT_CODEX_FASE_2E_ACEITE_END_TO_END.md`.
  - Runbooks e testes: `operations/*.md`, `testing.md`.
  - Especificação e planos: `Specs/DRONE_MEDIA_MANAGER_SPEC_AND_PLAN.md`, `superpowers/plans/*`, `superpowers/prompts/*`.
