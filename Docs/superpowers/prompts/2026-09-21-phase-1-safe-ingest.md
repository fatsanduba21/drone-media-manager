# Prompt — Fase 1: ingestão segura distribuída

Continue o Drone Media Manager pela Fase 1 — ingestão segura distribuída. Não inicie a Fase 2 ou qualquer fase posterior.

## Contexto do projeto

- Projeto: `C:\dev-apps\drone-orgnize`
- Branch de trabalho: `main`, salvo orientação explícita diferente.
- A completion gate da Fase 0 foi executada e o checkpoint Mac/Windows foi confirmado pelo usuário.
- Preserve alterações existentes, inclusive arquivos não rastreados e `uv.lock`.
- Leia integralmente antes de alterar código:
  - `Docs/Specs/DRONE_MEDIA_MANAGER_SPEC_AND_PLAN.md`
  - `Docs/superpowers/specs/2026-09-21-distributed-drone-media-manager-design.md`
  - `Docs/superpowers/plans/2026-09-21-phase-1-safe-ingest.md`
  - `Docs/superpowers/prompts/2026-09-21-phase-1-safe-ingest.md`
  - o ledger da Fase 0, se necessário, para confirmar as decisões anteriores.

## Instruções obrigatórias

1. Use Superpowers com `subagent-driven-development` ou o fallback inline `executing-plans`, mantendo ledger, TDD e revisão independente.
2. Execute uma tarefa por vez, na ordem do plano. Não pule a etapa RED: escreva o teste, execute-o e confirme a falha esperada antes do código de produção.
3. Implemente somente a Fase 1. Não crie catálogo DJI, proxies, análise, UI de revisão, selects, retenção ou exclusão física.
4. A origem é sempre read-only: listar, obter metadados e abrir para leitura. Nunca renomear, mover, apagar, formatar ou escrever na origem, inclusive em falhas e retries.
5. O banco SQLite continua local no Mac; o worker Windows nunca acessa o SQLite diretamente.
6. Use apenas caminhos OMV relativos no estado autoritativo e nos manifestos. Nunca grave caminhos absolutos de host, credenciais, tokens ou letras de unidade em manifestos.
7. Cópia, hash, promoção e manifestos devem ser idempotentes, seguros contra colisão e conservadores em caso de divergência.
8. Não declare sucesso, liberação do cartão ou backup sem evidência verificável. O aviso de formatação é apenas manual e nunca autoriza apagar a origem.
9. Antes de cada commit, rode os testes da tarefa; antes da conclusão, rode o gate completo abaixo e faça revisão de segurança contra operações destrutivas, path traversal, sobrescrita silenciosa e avanço de escopo.
10. Não faça push sem autorização explícita.

## Gate automatizado da Fase 1

Ao concluir todas as tarefas, execute e leia os resultados de:

```text
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest tests/unit tests/integration tests/security --cov=drone_media_manager --cov-report=term-missing -q
git diff --check
```

Faça também o checkpoint manual descrito na Task 10: fonte de teste com MP4/SRT, MP4 sem SRT e SRT órfão; `scan`, `ingest --dry-run`, `submit`, confirmação no Mac, cópia, interrupção/reconexão, retry e reimportação idempotente. Registre comandos, resultados, decisões e achados em um relatório da Fase 1 antes de atualizar o ledger.

## Critério de parada

Pare e peça orientação se uma decisão exigir apagar dados, formatar cartão, sobrescrever destino divergente, publicar dados externamente ou alterar um contrato da Fase 0 sem teste de compatibilidade. Caso contrário, resolva ambiguidades conservadoramente, registre a decisão no ledger e continue.

## Plano vinculante da Fase 1
# Phase 1 Distributed Safe Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import MP4 and optional SRT files from an explicitly selected Windows source into OMV with resumable copies, independent SHA-256 verification, idempotency, manifests, and no source mutation.

**Architecture:** The Windows worker inventories removable, local, or network sources through a read-only capability and submits a source snapshot to the Mac. After human confirmation, the Mac schedules per-ingest work; the worker copies to same-directory partial files on OMV, verifies source and destination independently, and reports authoritative progress through leased jobs.

**Tech Stack:** Phase 0 stack plus Python standard-library hashing and filesystem APIs; no ffmpeg execution is needed for Phase 1.

**Spec:** `Docs/superpowers/specs/2026-09-21-distributed-drone-media-manager-design.md`

**Prerequisite:** Every Phase 0 completion gate in `Docs/superpowers/plans/2026-09-21-phase-0-distributed-foundation.md` has passed and been approved.

## Global Constraints

- A source may be a removable volume, local drive, local directory, mapped drive, or UNC network path selected explicitly by the user.
- Every source kind is logically read-only; application code may only list, stat, and open source files for reading.
- MP4 and SRT extension matching is case-insensitive; SRT is optional.
- Pair states are exactly `PAIRED`, `VIDEO_WITHOUT_SRT`, and `ORPHAN_SRT`.
- Copy and verification operate on source bytes and OMV destination bytes only; no analysis, proxy, or transcoding reads directly from the source.
- A partial file is created in the final destination directory and never promoted until independent destination verification succeeds.
- Promotion never replaces an existing final file. Identical content is idempotent; divergent content is a conflict.
- The Mac is the state authority. Windows never opens SQLite and cannot finalize an ingest without a current lease.
- Host-specific absolute paths and credentials never enter manifests; media paths are logical OMV-relative paths.
- The card-formatting notice applies only to removable-card sources and never authorizes deleting source or INBOX files.
- No physical delete, move from source, rename on source, or format behavior exists in Phase 1.

## Review Focus

- Source enumeration must reject a symlink, junction, or reparse point that escapes the confirmed root.
- A source file changing size, timestamp, or file identity during copy must never reach `VERIFIED`.
- A partial file whose prefix differs from the source must be preserved and reported as a conflict, not appended or deleted.
- MP4 without SRT and orphan SRT must appear in the manifest without crashing or blocking unrelated files.
- Losing a network source, OMV, Mac, or Windows process mid-copy must preserve verified outputs and never create a false success.

## Planned File Structure

```text
src/drone_media_manager/
  domain/enums.py                       add source, pairing, ingest states
  db/models/ingest.py                   Trip, IngestJob, IngestItem, MediaFile, MediaPair, FileOperation
  db/migrations/versions/0002_ingest.py ingest schema
  sources/models.py                     source descriptors and entries
  sources/read_only.py                  read-only capability
  sources/discovery.py                  removable and explicit-path discovery
  sources/paths.py                      canonicalization and boundary checks
  ingest/inventory.py                   MP4/SRT pairing and snapshot
  ingest/fingerprint.py                 deterministic source fingerprint
  ingest/preflight.py                   connectivity and capacity checks
  ingest/copy.py                        chunked copy and resume
  ingest/verify.py                      source/destination SHA-256
  ingest/promote.py                     no-replace atomic promotion
  ingest/manifest.py                    atomic JSON manifest
  ingest/release_policy.py              removable-card release decision
  ingest/repository.py                  ingest state persistence
  ingest/service.py                     worker orchestration
  api/routes/sources.py                 source snapshot submission
  api/routes/ingests.py                 confirmation and status API
  worker/handlers/ingest.py              leased ingest job handler
  cli/worker.py                         scan, dry-run, ingest, verify commands
tests/fixtures/sources/                  simulated source trees
tests/unit/                              pure ingest tests
tests/integration/                       API/database/filesystem tests
tests/security/                          source mutation and path tests
```

---

### Task 1: Define source descriptors and a read-only filesystem capability

**Files:**
- Create: `src/drone_media_manager/sources/models.py`
- Create: `src/drone_media_manager/sources/read_only.py`
- Create: `src/drone_media_manager/sources/paths.py`
- Modify: `src/drone_media_manager/domain/enums.py`
- Create: `tests/unit/test_source_models.py`
- Create: `tests/security/test_source_read_only.py`
- Create: `tests/security/test_source_paths.py`

**Interfaces:**
- Produces: `SourceKind = REMOVABLE | LOCAL | NETWORK`, `SourceDescriptor`, `SourceEntry`, `SourceStat(size, mtime_ns, file_identity)`, and `ReadOnlySource` protocol.
- `ReadOnlySource` exposes only `iter_files()`, `open_read(entry)`, and `stat(entry)`.
- Produces: `canonicalize_source_root(path) -> CanonicalSourceRoot` and `validate_source_entry(root, candidate) -> SourceEntry`.

- [ ] **Step 1: Write failing capability and escape tests**

```python
def test_read_only_protocol_has_no_mutating_methods():
    methods = {
        name for name, value in ReadOnlySource.__dict__.items()
        if callable(value) and not name.startswith("_")
    }
    assert methods == {"iter_files", "open_read", "stat"}

@pytest.mark.parametrize("relative", ["../secret.mp4", "/etc/passwd", r"C:\other\clip.mp4"])
def test_source_entry_rejects_escape(source_root, relative):
    with pytest.raises(UnsafeSourcePath):
        validate_source_entry(source_root, source_root.path / relative)
```

- [ ] **Step 2: Run tests and verify missing modules fail**

Run: `uv run pytest tests/unit/test_source_models.py tests/security/test_source_read_only.py tests/security/test_source_paths.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement immutable descriptors and Windows boundary checks**

`SourceDescriptor` contains `kind`, canonical root, display label, volume identity when available, and a Boolean `is_removable`. Reject NUL, root escape, symlink escape, and Windows reparse points leaving the root. Network sources preserve their canonical UNC identity even when accessed through a mapped drive.

- [ ] **Step 4: Verify all source kinds use the same safety contract**

Run: `uv run pytest tests/unit/test_source_models.py tests/security/test_source_read_only.py tests/security/test_source_paths.py -v`

Expected: PASS, with zero mutating methods on `ReadOnlySource`.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/sources src/drone_media_manager/domain/enums.py tests/unit/test_source_models.py tests/security/test_source_read_only.py tests/security/test_source_paths.py
git commit -m "feat: add read-only source boundary"
```

### Task 2: Discover sources and build deterministic MP4/SRT inventories

**Files:**
- Create: `src/drone_media_manager/sources/discovery.py`
- Create: `src/drone_media_manager/ingest/inventory.py`
- Create: `src/drone_media_manager/ingest/fingerprint.py`
- Create: `tests/fixtures/sources/mixed/DCIM/DJI_0001.MP4`
- Create: `tests/fixtures/sources/mixed/DCIM/DJI_0001.SRT`
- Create: `tests/fixtures/sources/mixed/DCIM/DJI_0002.mp4`
- Create: `tests/fixtures/sources/mixed/DCIM/ORPHAN.srt`
- Create: `tests/unit/test_source_discovery.py`
- Create: `tests/unit/test_inventory.py`
- Create: `tests/unit/test_fingerprint.py`

**Interfaces:**
- Consumes: `SourceDescriptor` and `ReadOnlySource`.
- Produces: `discover_removable_sources() -> list[SourceDescriptor]`, `source_from_explicit_path(path) -> SourceDescriptor`.
- Produces: `build_inventory(source, recursive=True) -> Inventory` and `fingerprint_inventory(inventory) -> str`.

- [ ] **Step 1: Write failing pairing and fingerprint tests**

```python
def test_inventory_preserves_optional_srt_states(mixed_source):
    inventory = build_inventory(mixed_source)
    assert [(item.stem, item.pair_status.value) for item in inventory.items] == [
        ("DJI_0001", "PAIRED"),
        ("DJI_0002", "VIDEO_WITHOUT_SRT"),
        ("ORPHAN", "ORPHAN_SRT"),
    ]

def test_fingerprint_is_independent_of_enumeration_order(inventory):
    assert fingerprint_inventory(inventory) == fingerprint_inventory(inventory.reversed())
```

- [ ] **Step 2: Run tests and observe missing inventory behavior**

Run: `uv run pytest tests/unit/test_source_discovery.py tests/unit/test_inventory.py tests/unit/test_fingerprint.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement discovery, pairing, and canonical fingerprinting**

Recognize `.mp4` and `.srt` case-insensitively, pair by complete filename stem within the same relative directory, sort by Unicode-normalized relative path, and retain orphans. Fingerprint SHA-256 over canonical JSON containing source kind, stable volume identity when available, relative path, size, and nanosecond modification time. The fingerprint is an inventory identity, not a substitute for content verification.

- [ ] **Step 4: Verify removable, local, network, missing-SRT, and orphan-SRT cases**

Run: `uv run pytest tests/unit/test_source_discovery.py tests/unit/test_inventory.py tests/unit/test_fingerprint.py -v`

Expected: PASS with exactly three pair-state results for the mixed fixture.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/sources/discovery.py src/drone_media_manager/ingest tests/fixtures/sources tests/unit/test_source_discovery.py tests/unit/test_inventory.py tests/unit/test_fingerprint.py
git commit -m "feat: inventory flexible media sources"
```

### Task 3: Add ingest persistence, constraints, and repository transitions

**Files:**
- Create: `src/drone_media_manager/db/models/ingest.py`
- Create: `src/drone_media_manager/db/migrations/versions/0002_ingest.py`
- Create: `src/drone_media_manager/ingest/repository.py`
- Modify: `src/drone_media_manager/domain/enums.py`
- Create: `tests/integration/test_ingest_migration.py`
- Create: `tests/integration/test_ingest_repository.py`

**Interfaces:**
- Produces models `Trip`, `IngestJob`, `IngestItem`, `MediaFile`, `MediaPair`, and `FileOperation`.
- Produces: `IngestRepository.create_snapshot(...)`, `confirm_ingest(...)`, `transition_ingest(...)`, `checkpoint_item(...)`, and `record_verified_media(...)`.

- [ ] **Step 1: Write failing migration and idempotency-constraint tests**

```python
def test_same_trip_and_source_fingerprint_is_unique(session, trip):
    session.add(IngestJob(trip_id=trip.id, source_fingerprint="a" * 64))
    session.commit()
    session.add(IngestJob(trip_id=trip.id, source_fingerprint="a" * 64))
    with pytest.raises(IntegrityError):
        session.commit()

def test_item_checkpoint_requires_expected_revision(repository, ingest_item):
    with pytest.raises(StaleRevision):
        repository.checkpoint_item(ingest_item.id, expected_revision=99, bytes_copied=10)
```

- [ ] **Step 2: Run tests and observe missing revision `0002_ingest`**

Run: `uv run pytest tests/integration/test_ingest_migration.py tests/integration/test_ingest_repository.py -v`

Expected: FAIL because models and migration are absent.

- [ ] **Step 3: Implement schema and guarded transitions**

Use unique constraints on `(trip_id, source_fingerprint)` and `(ingest_job_id, source_rel_path)`. `IngestItem` persists source metadata, destination relative path, partial relative path, copied bytes, source hash, destination hash, status, error, and revision. `MediaFile` identity within a trip uses `(trip_id, media_type, size_bytes, sha256)`. Foreign keys restrict deletion of referenced records and never cascade audit history.

Allowed ingest progression is `DISCOVERED -> COPYING -> VERIFYING -> VERIFIED`, with `FAILED` and `INTERRUPTED` exits. A retry from `INTERRUPTED` requires explicit reconciliation.

- [ ] **Step 4: Verify migration round-trip and repository concurrency**

Run: `uv run pytest tests/integration/test_ingest_migration.py tests/integration/test_ingest_repository.py -v`

Expected: PASS for upgrade, downgrade, uniqueness, foreign keys, legal transitions, and stale revisions.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/db/models/ingest.py src/drone_media_manager/db/migrations/versions/0002_ingest.py src/drone_media_manager/ingest/repository.py src/drone_media_manager/domain/enums.py tests/integration/test_ingest_migration.py tests/integration/test_ingest_repository.py
git commit -m "feat: add safe ingest persistence"
```

### Task 4: Add source snapshot and human-confirmed ingest APIs

**Files:**
- Create: `src/drone_media_manager/api/schemas/sources.py`
- Create: `src/drone_media_manager/api/schemas/ingests.py`
- Create: `src/drone_media_manager/api/routes/sources.py`
- Create: `src/drone_media_manager/api/routes/ingests.py`
- Modify: `src/drone_media_manager/api/app.py`
- Create: `tests/integration/test_source_snapshot_api.py`
- Create: `tests/integration/test_ingest_confirmation_api.py`

**Interfaces:**
- Consumes: authenticated worker identity, `Inventory`, fingerprint, and `IngestRepository`.
- Produces: `POST /api/sources/snapshots`, batched `POST /api/sources/snapshots/{snapshot_id}/entries`, `POST /api/sources/snapshots/{snapshot_id}/finalize`, `POST /api/ingests`, and `GET /api/ingests/{ingest_id}`.
- A finalized snapshot is immutable and expires after a configured interval; confirmation references its ID and revision.

- [ ] **Step 1: Write failing worker-ownership and confirmation tests**

```python
def test_worker_cannot_submit_snapshot_for_another_worker(worker_a, worker_b):
    response = worker_a.post("/api/sources/snapshots", json=snapshot_json(worker_b.id))
    assert response.status_code == 403

def test_confirmed_snapshot_enqueues_ingest_job(user_client, snapshot, trip):
    response = user_client.post("/api/ingests", json={"snapshot_id": snapshot.id, "trip_id": trip.id})
    assert response.status_code == 201
    assert response.json()["status"] == "DISCOVERED"
```

- [ ] **Step 2: Run tests and verify routes are absent**

Run: `uv run pytest tests/integration/test_source_snapshot_api.py tests/integration/test_ingest_confirmation_api.py -v`

Expected: FAIL with 404 or missing imports.

- [ ] **Step 3: Implement immutable snapshots and explicit confirmation**

Accept only worker-authenticated snapshots. Create the draft with source metadata, accept at most 500 relative entries per request, and finalize only after the server recomputes the declared item count and fingerprint. Store logical metadata and relative entries; never store the worker's raw credentials. Confirmation validates finalized status, expiry, and revision, creates or reuses the `(trip_id, source_fingerprint)` ingest, creates per-file items, and enqueues one `ingest` orchestration job for the same worker capability.

Until user authentication arrives in the later UI phase, confirmation is exposed only through a localhost-admin dependency and the server CLI. It must not be anonymously reachable on a LAN bind.

- [ ] **Step 4: Verify authorization, expiry, replay, and idempotency**

Run: `uv run pytest tests/integration/test_source_snapshot_api.py tests/integration/test_ingest_confirmation_api.py -v`

Expected: PASS for wrong worker, expired snapshot, stale revision, duplicate confirmation, and valid confirmation.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/api src/drone_media_manager/ingest/repository.py tests/integration/test_source_snapshot_api.py tests/integration/test_ingest_confirmation_api.py
git commit -m "feat: add confirmed ingest api"
```

### Task 5: Implement OMV and source preflight without mutating the source

**Files:**
- Create: `src/drone_media_manager/ingest/preflight.py`
- Create: `src/drone_media_manager/storage/capacity.py`
- Create: `src/drone_media_manager/storage/destination.py`
- Create: `tests/unit/test_ingest_preflight.py`
- Create: `tests/security/test_destination_paths.py`

**Interfaces:**
- Consumes: `Inventory`, `ReadOnlySource`, `RootMapper`, and configured reserve bytes/percentage.
- Produces: `run_preflight(inventory, source, destination, policy) -> PreflightReport`.
- Produces: `DestinationPlanner.plan(trip, source_entry) -> PlannedDestination`.

- [ ] **Step 1: Write failing capacity and collision tests**

```python
def test_preflight_blocks_when_space_is_below_required_margin(inventory, fake_capacity):
    fake_capacity.available_bytes = inventory.total_bytes
    report = run_preflight(inventory, source(), destination(fake_capacity), policy(reserve_bytes=1))
    assert report.allowed is False
    assert report.errors[0].code == "insufficient_space"

def test_destination_never_uses_source_absolute_path(planner, source_entry):
    planned = planner.plan(trip(), source_entry)
    assert planned.relative_path.as_posix().startswith("trips/")
    assert str(source_entry.absolute_path) not in planned.relative_path.as_posix()
```

- [ ] **Step 2: Run tests and observe missing preflight modules**

Run: `uv run pytest tests/unit/test_ingest_preflight.py tests/security/test_destination_paths.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement read-only preflight and deterministic destinations**

Verify source entries still match inventoried size, nanosecond mtime, and file identity; verify OMV root identity, connectivity, and free bytes; require `total_pending_bytes + max(reserve_bytes, capacity * reserve_percent)`. Probe destination permissions by exclusively creating, fsyncing, and removing an application-owned zero-byte file below the planned INBOX directory; never probe by writing to the source. Determine destination paths from sanitized trip slug, stable trip ID, and source-relative filename. Destination collision is reported before copy.

- [ ] **Step 4: Verify NAS offline, source changed, margin, and path escape cases**

Run: `uv run pytest tests/unit/test_ingest_preflight.py tests/security/test_destination_paths.py -v`

Expected: PASS with stable error codes `source_changed`, `destination_offline`, `insufficient_space`, and `unsafe_destination`.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/ingest/preflight.py src/drone_media_manager/storage/capacity.py src/drone_media_manager/storage/destination.py tests/unit/test_ingest_preflight.py tests/security/test_destination_paths.py
git commit -m "feat: add ingest preflight checks"
```

### Task 6: Copy in chunks with durable progress and prefix-safe resume

**Files:**
- Create: `src/drone_media_manager/ingest/copy.py`
- Create: `tests/unit/test_chunked_copy.py`
- Create: `tests/integration/test_copy_resume.py`

**Interfaces:**
- Consumes: `ReadOnlySource`, `PlannedDestination`, progress callback, cancellation token, and an open-current-lease callback.
- Produces: `CopyEngine.copy_or_resume(item, progress, cancelled, lease_valid) -> CopyOutcome`.
- `CopyOutcome` contains bytes copied, source SHA-256, partial path, and final source stat.

- [ ] **Step 1: Write failing interruption and divergent-prefix tests**

```python
def test_interruption_preserves_partial_and_checkpoint(copy_engine, item, cancel_after_two_chunks):
    outcome = copy_engine.copy_or_resume(item, cancelled=cancel_after_two_chunks)
    assert outcome.status == "INTERRUPTED"
    assert item.partial_path.exists()
    assert item.partial_path.stat().st_size == 2 * item.chunk_size

def test_resume_rejects_divergent_partial(copy_engine, item):
    item.partial_path.write_bytes(b"different prefix")
    with pytest.raises(PartialPrefixMismatch):
        copy_engine.copy_or_resume(item)
    assert item.partial_path.read_bytes() == b"different prefix"
```

- [ ] **Step 2: Run tests and confirm copy engine is absent**

Run: `uv run pytest tests/unit/test_chunked_copy.py tests/integration/test_copy_resume.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement bounded copy and conservative resume**

Default chunks are 8 MiB and configurable between 1 and 64 MiB. Name the partial with `f".{final_path.name}.{ingest_item.id}.partial"` in the final directory. Before append, hash the existing partial and the same-length source prefix and require equality. On mismatch, preserve the partial, record `partial_prefix_mismatch`, and stop. Flush Python buffers and call `os.fsync` before recording a durable checkpoint. Re-check cancellation and lease validity between chunks, then compare final size, nanosecond mtime, and file identity with the inventoried `SourceStat` before returning success.

- [ ] **Step 4: Verify interruption, resume, cancellation, and source mutation**

Run: `uv run pytest tests/unit/test_chunked_copy.py tests/integration/test_copy_resume.py -v`

Expected: PASS; source bytes and metadata remain unchanged in every test.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/ingest/copy.py tests/unit/test_chunked_copy.py tests/integration/test_copy_resume.py
git commit -m "feat: add resumable chunked copy"
```

### Task 7: Independently verify and atomically promote without replacement

**Files:**
- Create: `src/drone_media_manager/ingest/verify.py`
- Create: `src/drone_media_manager/ingest/promote.py`
- Create: `tests/unit/test_hash_verifier.py`
- Create: `tests/integration/test_atomic_promote.py`

**Interfaces:**
- Consumes: copied source hash, current source stat, partial path, and final path.
- Produces: `verify_copy(source, partial, expected_source_hash) -> VerificationResult`.
- Produces: `promote_no_replace(partial, final) -> PromotionResult` with `PROMOTED`, `IDENTICAL_EXISTING`, or `DIVERGENT_CONFLICT`.

- [ ] **Step 1: Write failing hash-divergence and no-overwrite tests**

```python
def test_destination_hash_mismatch_never_verifies(verifier, source, partial):
    partial.write_bytes(b"corrupted")
    result = verifier.verify_copy(source, partial, expected_source_hash=sha256(source))
    assert result.verified is False
    assert result.error_code == "destination_hash_mismatch"

def test_divergent_final_is_never_replaced(tmp_path):
    partial = write(tmp_path / ".clip.partial", b"new")
    final = write(tmp_path / "clip.mp4", b"existing")
    assert promote_no_replace(partial, final).status == "DIVERGENT_CONFLICT"
    assert final.read_bytes() == b"existing"
    assert partial.read_bytes() == b"new"
```

- [ ] **Step 2: Run tests and observe missing verification behavior**

Run: `uv run pytest tests/unit/test_hash_verifier.py tests/integration/test_atomic_promote.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement independent destination hashing and Windows no-replace promotion**

Re-open both the source and partial after copy and compute their SHA-256 independently from the streaming copy hash. Require current source size, nanosecond mtime, and file identity to match inventory; destination size to match source; the second source hash to match the streaming source hash; and the destination hash to match both. On Windows, use a same-volume rename primitive that fails when the destination exists; never use `os.replace`. When final exists, hash it: identical content returns `IDENTICAL_EXISTING`; different content preserves both files and returns conflict.

- [ ] **Step 4: Verify hash, existing-file, race, and cross-volume rejection cases**

Run: `uv run pytest tests/unit/test_hash_verifier.py tests/integration/test_atomic_promote.py -v`

Expected: PASS with no silent replacement under any case.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/ingest/verify.py src/drone_media_manager/ingest/promote.py tests/unit/test_hash_verifier.py tests/integration/test_atomic_promote.py
git commit -m "feat: verify and promote ingest files safely"
```

### Task 8: Generate atomic manifests and evaluate card-release policy

**Files:**
- Create: `src/drone_media_manager/ingest/manifest.py`
- Create: `src/drone_media_manager/ingest/release_policy.py`
- Create: `tests/unit/test_manifest.py`
- Create: `tests/unit/test_release_policy.py`

**Interfaces:**
- Consumes: verified ingest records and logical paths.
- Produces: `build_manifest(ingest) -> IngestManifest`, `write_manifest_atomic(manifest, destination) -> ManifestWriteResult`.
- Produces: `evaluate_release(ingest, backup_policy) -> ReleaseDecision`.

- [ ] **Step 1: Write failing optional-SRT and release-policy tests**

```python
def test_manifest_contains_missing_and_orphan_srt_states(verified_ingest):
    manifest = build_manifest(verified_ingest)
    assert {item.pair_status for item in manifest.items} >= {
        "VIDEO_WITHOUT_SRT", "ORPHAN_SRT"
    }

def test_local_source_never_gets_card_format_notice(verified_local_ingest):
    decision = evaluate_release(verified_local_ingest, BackupPolicy.NAS_ONLY)
    assert decision.card_format_allowed is False
    assert decision.reason == "source_is_not_removable"
```

- [ ] **Step 2: Run tests and verify manifest/policy modules are absent**

Run: `uv run pytest tests/unit/test_manifest.py tests/unit/test_release_policy.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement versioned manifest and conservative release rules**

Write canonical UTF-8 JSON to `f"05_MANIFESTS/ingest_manifest.{ingest.id}.json"` through a same-directory temporary file, fsync, and no-replace rename. Include schema version, IDs, source kind/fingerprint, relative paths, sizes, SHA-256 values, pair states, and errors. Exclude source absolute paths, worker tokens, mount paths, and credentials.

`REQUIRE_SECOND_COPY` permits the removable-card notice only when all items and manifest are verified and a separate verified backup record exists. `NAS_ONLY` permits it after complete OMV verification but returns the exact warning that only one verified copy exists. Non-removable sources never receive the notice.

- [ ] **Step 4: Verify canonical JSON, replay, secrets, and all policy branches**

Run: `uv run pytest tests/unit/test_manifest.py tests/unit/test_release_policy.py -v`

Expected: PASS; writing the identical manifest twice is idempotent and divergent existing content is a conflict.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/ingest/manifest.py src/drone_media_manager/ingest/release_policy.py tests/unit/test_manifest.py tests/unit/test_release_policy.py
git commit -m "feat: add ingest manifests and release policy"
```

### Task 9: Orchestrate leased ingestion and expose distributed CLI workflows

**Files:**
- Create: `src/drone_media_manager/ingest/service.py`
- Create: `src/drone_media_manager/worker/handlers/ingest.py`
- Modify: `src/drone_media_manager/worker/service.py`
- Modify: `src/drone_media_manager/cli/worker.py`
- Modify: `src/drone_media_manager/cli/server.py`
- Create: `tests/integration/test_ingest_orchestration.py`
- Create: `tests/integration/test_ingest_cli.py`

**Interfaces:**
- Consumes: preflight, copy, verify, promote, manifest, release policy, current job lease, and API client.
- Produces: `IngestJobHandler.execute(claimed_job) -> JobExecutionResult`.
- Produces Windows commands `dmm-worker scan PATH`, `dmm-worker ingest --dry-run PATH`, `dmm-worker submit PATH`, and `dmm-worker verify INGEST_ID`.
- Produces Mac commands `dmm-server ingest confirm SNAPSHOT_ID --trip TRIP_ID` and `dmm-server ingest status INGEST_ID`.

- [ ] **Step 1: Write a failing complete distributed-ingest test**

```python
def test_confirmed_ingest_copies_verifies_and_reports_manifest(distributed_harness):
    snapshot = distributed_harness.worker.submit_fixture("mixed")
    ingest = distributed_harness.server.confirm(snapshot.id, trip_name="Test Trip")
    distributed_harness.worker.run_until_idle()
    result = distributed_harness.server.ingest(ingest.id)
    assert result.status == "VERIFIED"
    assert result.bytes_verified == result.bytes_total
    assert result.manifest_status == "VERIFIED"
    assert distributed_harness.source_tree_digest() == distributed_harness.original_digest
```

- [ ] **Step 2: Run the integration tests and verify orchestration is incomplete**

Run: `uv run pytest tests/integration/test_ingest_orchestration.py tests/integration/test_ingest_cli.py -v`

Expected: FAIL because the ingest handler and CLI subcommands are absent.

- [ ] **Step 3: Implement the orchestration state machine**

For each item: reconcile existing partial/final state, check the current lease, transition to copying, checkpoint chunks, transition to verifying, independently verify, promote, and record verified media. Stop the ingest on a safety failure while preserving prior verified items. After all items, write and verify the manifest, transition the aggregate ingest to `VERIFIED`, and evaluate the release policy.

`--dry-run` performs discovery, inventory, collision detection, and capacity calculation without creating source, OMV, database, or API state. `submit` uploads an immutable snapshot but does not confirm it. Actual copying begins only after the Mac confirmation command.

- [ ] **Step 4: Verify CLI exit codes and the end-to-end happy path**

Run: `uv run pytest tests/integration/test_ingest_orchestration.py tests/integration/test_ingest_cli.py -v`

Expected: PASS; exit code 0 means success, 2 means validation/configuration error, 3 means interrupted/retryable, and 4 means integrity conflict.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/ingest/service.py src/drone_media_manager/worker src/drone_media_manager/cli tests/integration/test_ingest_orchestration.py tests/integration/test_ingest_cli.py
git commit -m "feat: orchestrate distributed safe ingest"
```

### Task 10: Prove failure recovery and document the operational checkpoint

**Files:**
- Create: `tests/integration/test_ingest_failures.py`
- Create: `tests/integration/test_ingest_idempotency.py`
- Create: `tests/security/test_no_source_mutation.py`
- Create: `Docs/operations/safe-ingest.md`
- Modify: `Docs/testing.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the completed Phase 1 CLI and distributed service interfaces.
- Produces: a reproducible operator procedure and automated failure matrix.

- [ ] **Step 1: Add parameterized failing recovery tests**

```python
@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        ("source_disconnected", "INTERRUPTED"),
        ("omv_disconnected", "INTERRUPTED"),
        ("mac_unreachable", "INTERRUPTED"),
        ("worker_stopped", "INTERRUPTED"),
        ("destination_hash_mismatch", "FAILED"),
        ("insufficient_space", "FAILED"),
    ],
)
def test_failure_never_marks_ingest_verified(failure_harness, failure, expected_status):
    result = failure_harness.run_with_failure(failure)
    assert result.status == expected_status
    assert result.status != "VERIFIED"
    assert failure_harness.source_tree_digest() == failure_harness.original_digest
```

- [ ] **Step 2: Run the failure suite and record every unimplemented recovery path**

Run: `uv run pytest tests/integration/test_ingest_failures.py tests/integration/test_ingest_idempotency.py tests/security/test_no_source_mutation.py -v`

Expected: FAIL for any recovery path not yet wired through the orchestration service.

- [ ] **Step 3: Make the minimum recovery corrections and write the runbook**

Correct only failures exposed by the matrix. The runbook documents scan, dry-run, submit, Mac confirmation, progress, verification, retry after reconnect, conflict handling, optional SRT behavior, default second-copy policy, `nas_only` warning, and the difference between card release and INBOX retention.

- [ ] **Step 4: Run the complete automated Phase 1 gate**

Run: `uv run ruff check .`

Run: `uv run ruff format --check .`

Run: `uv run mypy src`

Run: `uv run pytest tests/unit tests/integration tests/security --cov=drone_media_manager --cov-report=term-missing -q`

Expected: all commands exit 0. Tests prove no duplicate media on repeat import, no source mutation, no silent overwrite, and no false `VERIFIED` state.

- [ ] **Step 5: Perform the manual Mac-Windows-OMV acceptance test**

Create `C:\DMM-TestSource` containing one MP4/SRT pair, one MP4 without SRT, and one orphan SRT. On Windows run `uv run dmm-worker scan C:\DMM-TestSource`, `uv run dmm-worker ingest --dry-run C:\DMM-TestSource`, and `uv run dmm-worker submit C:\DMM-TestSource`. Confirm the snapshot on the Mac, let the worker finish, disconnect and reconnect the test source during a second run, and confirm safe resumption. Reimport the same source and confirm zero duplicated media records or files.

- [ ] **Step 6: Commit**

```text
git add tests/integration/test_ingest_failures.py tests/integration/test_ingest_idempotency.py tests/security/test_no_source_mutation.py Docs/operations/safe-ingest.md Docs/testing.md README.md
git commit -m "test: prove safe ingest recovery"
```

## Phase 1 Completion Gate

- Removable, local-drive, local-directory, mapped-drive, and UNC sources share one read-only safety boundary.
- MP4/SRT pairs, MP4 without SRT, and orphan SRT are cataloged and represented in the manifest.
- Copy interruption preserves partial work and safe resume validates the complete existing prefix.
- Source and destination SHA-256 plus size equality are required for `VERIFIED`.
- Existing divergent destination content is never overwritten or deleted.
- Repeat import is idempotent at ingest, media-record, and filesystem levels.
- Network-source, OMV, Mac, and Windows failures never create a false success.
- Only removable-card sources can receive the manual-format notice, and only under the configured backup policy.
- POI reverse geocoding remains explicitly deferred to its later phase; Phase 1 preserves optional SRT and future telemetry inputs without inventing location data.
- No later phase starts until the automated gate and manual distributed checkpoint are reviewed and approved.
