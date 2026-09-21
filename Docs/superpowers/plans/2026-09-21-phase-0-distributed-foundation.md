# Phase 0 Distributed Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run an always-on Mac control plane and an intermittently connected Windows worker with persistent, authenticated, recoverable jobs and no source-media mutation.

**Architecture:** One Python package exposes `dmm-server` for the Mac and `dmm-worker` for Windows. FastAPI and a Mac-local SQLite database own authoritative state; the Windows process polls an authenticated HTTP API, renews job leases, and reports progress. Host-specific mount paths map to logical OMV-relative paths.

**Tech Stack:** Python 3.13.14 (`>=3.12,<3.14`), uv, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, Pydantic Settings, HTTPX, keyring, pytest, Ruff, mypy.

**Spec:** `Docs/superpowers/specs/2026-09-21-distributed-drone-media-manager-design.md`

## Global Constraints

- The Mac runs API, UI foundation, scheduler, worker registry, leases, audit log, and the active SQLite database.
- The active SQLite file must be a local Mac path, never SMB, OMV, iCloud, or another synchronized directory.
- The Windows worker never opens SQLite and communicates only through the authenticated API.
- The worker may read configured sources and write only below the configured OMV destination root.
- Source-facing interfaces expose no write, rename, move, delete, or format operation.
- All subprocess calls use argument lists, `shell=False`, explicit timeout, and bounded output capture.
- Default server bind is `127.0.0.1`; cleartext LAN bind requires `DMM_ALLOW_INSECURE_LAN=true` and emits a warning.
- No phase-0 API performs media deletion, SD formatting, proxy generation, or media analysis.
- Timestamps are UTC; stable identifiers are UUID strings; state transitions are validated server-side.
- Each task uses red-green-refactor and ends with an independently reviewable commit.

## Review Focus

- A database path beginning with `//`, `\\`, or located under a configured synchronized directory must fail configuration validation.
- Two concurrent job claims must never lease the same job to different workers.
- An expired lease must enter reconciliation/interruption before the job can be claimed again.
- A stale heartbeat or progress report carrying an old revision or lease token must be rejected without changing state.
- A worker losing the Mac connection must stop claiming/finalizing work and preserve its local execution state.

## Planned File Structure

```text
pyproject.toml                         dependencies, tools, CLI entrypoints
.python-version                       Python 3.13
.env.example                          non-secret configuration names
src/drone_media_manager/
  __init__.py                         package version
  config.py                           validated server/worker settings
  time.py                             UTC clock abstraction
  domain/enums.py                     worker/job states
  domain/errors.py                    typed domain errors
  db/base.py                          SQLAlchemy metadata
  db/session.py                       local SQLite engine/session factory
  db/models/core.py                   Worker, Job, AuditEvent
  db/migrations/env.py                Alembic environment
  db/migrations/versions/0001_core.py core schema
  jobs/transitions.py                 legal state transitions
  jobs/repository.py                  transactional claim/lease operations
  api/app.py                          FastAPI factory and lifecycle
  api/dependencies.py                 DB and worker-auth dependencies
  api/routes/health.py                health endpoint
  api/routes/workers.py               registration and heartbeat
  api/routes/jobs.py                  claim/progress/complete/fail
  worker/client.py                    typed HTTP client
  worker/credentials.py               keyring token storage
  worker/service.py                   heartbeat and poll loop
  storage/roots.py                    logical OMV root mapping
  system/dependencies.py              ffmpeg/ffprobe probes
  cli/server.py                       dmm-server entrypoint
  cli/worker.py                       dmm-worker entrypoint
tests/unit/                            pure behavior tests
tests/integration/                     SQLite and HTTP tests
tests/security/                        path/auth boundary tests
```

---

### Task 1: Bootstrap the package and validated host configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/drone_media_manager/__init__.py`
- Create: `src/drone_media_manager/config.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `ServerSettings`, `WorkerSettings`, `get_server_settings()`, and `get_worker_settings()`.
- `ServerSettings.database_path: Path`, `omv_root: Path`, `bind_host: str`, `port: int`, `allow_insecure_lan: bool`, `worker_bootstrap_token: SecretStr`.
- `WorkerSettings.server_url: AnyHttpUrl`, `worker_name: str`, `omv_root: Path`, `poll_seconds: float`, `heartbeat_seconds: float`.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_server_rejects_unc_sqlite_path(tmp_path):
    with pytest.raises(ValueError, match="SQLite database must be local"):
        ServerSettings(
            database_path=Path(r"\\omv\media\dmm.sqlite3"),
            omv_root=tmp_path,
            worker_bootstrap_token="0123456789abcdef0123456789abcdef",
        )

def test_server_rejects_cleartext_non_loopback_without_opt_in(tmp_path):
    with pytest.raises(ValueError, match="DMM_ALLOW_INSECURE_LAN"):
        ServerSettings(
            database_path=tmp_path / "dmm.sqlite3",
            omv_root=tmp_path,
            bind_host="0.0.0.0",
            worker_bootstrap_token="0123456789abcdef0123456789abcdef",
        )
```

- [ ] **Step 2: Verify the tests fail because configuration is absent**

Run: `uv run pytest tests/unit/test_config.py -v`

Expected: FAIL during import of `drone_media_manager.config`.

- [ ] **Step 3: Add package metadata and minimal settings implementation**

Use `requires-python = ">=3.12,<3.14"`. Runtime dependencies are `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `pydantic-settings`, `httpx`, and `keyring`. Dev dependencies are `pytest`, `pytest-cov`, `ruff`, and `mypy`.

Implement Pydantic validators that reject UNC database paths, reject database paths under `DMM_SYNCED_ROOTS`, require a bootstrap token of at least 32 characters, and permit a non-loopback bind only with TLS configuration or `allow_insecure_lan=True`.

- [ ] **Step 4: Run focused quality checks**

Run: `uv run pytest tests/unit/test_config.py -v`

Expected: PASS.

Run: `uv run ruff check src/drone_media_manager/config.py tests/unit/test_config.py`

Expected: exit code 0.

- [ ] **Step 5: Commit**

```text
git add pyproject.toml .python-version .gitignore .env.example src/drone_media_manager tests/unit/test_config.py
git commit -m "chore: bootstrap distributed media manager"
```

### Task 2: Create the local SQLite core schema and migration contract

**Files:**
- Create: `alembic.ini`
- Create: `src/drone_media_manager/time.py`
- Create: `src/drone_media_manager/db/base.py`
- Create: `src/drone_media_manager/db/session.py`
- Create: `src/drone_media_manager/db/models/core.py`
- Create: `src/drone_media_manager/db/migrations/env.py`
- Create: `src/drone_media_manager/db/migrations/script.py.mako`
- Create: `src/drone_media_manager/db/migrations/versions/0001_core.py`
- Create: `tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: `ServerSettings.database_path`.
- Produces: `create_engine_from_settings(settings) -> Engine`, `session_factory(engine) -> sessionmaker[Session]`, `utc_now() -> datetime`.
- Produces models `Worker`, `Job`, and `AuditEvent` with UUID string primary keys and UTC timestamps.

- [ ] **Step 1: Write a migration round-trip test**

```python
def test_core_migration_round_trip(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'core.sqlite3'}"
    command.up(alembic_config(db_url), "head")
    assert set(inspect(create_engine(db_url)).get_table_names()) >= {
        "workers", "jobs", "audit_events", "alembic_version"
    }
    command.downgrade(alembic_config(db_url), "base")
    assert inspect(create_engine(db_url)).get_table_names() == []
```

- [ ] **Step 2: Run the test and observe the missing Alembic configuration**

Run: `uv run pytest tests/integration/test_migrations.py::test_core_migration_round_trip -v`

Expected: FAIL because `alembic.ini` or revision `0001_core` is missing.

- [ ] **Step 3: Implement the schema**

`workers` contains `id`, `name`, `token_digest`, `capabilities_json`, `status`, `last_seen_at`, `revision`, `created_at`, and `updated_at`. `jobs` contains `id`, `kind`, `payload_json`, `status`, `revision`, `attempts`, `progress`, `available_at`, `lease_worker_id`, `lease_token_digest`, `lease_expires_at`, `error`, `created_at`, and `updated_at`. `audit_events` contains immutable actor, action, entity, result, details, correlation ID, and occurrence time fields.

Install SQLAlchemy connection listeners that execute `PRAGMA foreign_keys=ON` and `PRAGMA busy_timeout=5000`. Enable WAL only after `ServerSettings` has validated the local database path.

- [ ] **Step 4: Verify migration and SQLite pragmas**

Run: `uv run pytest tests/integration/test_migrations.py -v`

Expected: PASS for upgrade, downgrade, foreign-key enforcement, and busy timeout.

- [ ] **Step 5: Commit**

```text
git add alembic.ini src/drone_media_manager/db src/drone_media_manager/time.py tests/integration/test_migrations.py
git commit -m "feat: add local sqlite core schema"
```

### Task 3: Implement job state transitions, claims, and renewable leases

**Files:**
- Create: `src/drone_media_manager/domain/enums.py`
- Create: `src/drone_media_manager/domain/errors.py`
- Create: `src/drone_media_manager/jobs/transitions.py`
- Create: `src/drone_media_manager/jobs/repository.py`
- Create: `tests/unit/test_job_transitions.py`
- Create: `tests/integration/test_job_leases.py`

**Interfaces:**
- Consumes: `Job`, `Worker`, SQLAlchemy `Session`, and `utc_now()`.
- Produces: `JobStatus`, `WorkerStatus`, `assert_job_transition(current, target) -> None`.
- Produces: `JobRepository.claim(worker_id, capabilities, lease_seconds) -> ClaimedJob | None`, `renew(job_id, worker_id, lease_token, expected_revision, lease_seconds) -> ClaimedJob`, and `interrupt_expired(now) -> list[str]`.

- [ ] **Step 1: Write failing state and concurrency tests**

```python
def test_complete_cannot_transition_back_to_running():
    with pytest.raises(InvalidTransition):
        assert_job_transition(JobStatus.COMPLETE, JobStatus.RUNNING)

def test_two_sessions_cannot_claim_the_same_job(session_factory, worker_pair):
    first = JobRepository(session_factory()).claim(worker_pair[0].id, {"ingest"}, 30)
    second = JobRepository(session_factory()).claim(worker_pair[1].id, {"ingest"}, 30)
    assert first is not None
    assert second is None
```

- [ ] **Step 2: Run focused tests and confirm missing behavior**

Run: `uv run pytest tests/unit/test_job_transitions.py tests/integration/test_job_leases.py -v`

Expected: FAIL because transition and repository modules do not exist.

- [ ] **Step 3: Implement transactional lease behavior**

Use `BEGIN IMMEDIATE` for the short SQLite claim transaction. Select the oldest eligible `PENDING` job whose `kind` is in worker capabilities, set `LEASED`, increment `revision` and `attempts`, store a SHA-256 digest of a random 32-byte lease token, and return the plaintext token once. Renewals and progress require matching worker ID, token digest, non-expired lease, and expected revision.

`interrupt_expired()` transitions expired `LEASED` or `RUNNING` jobs to `INTERRUPTED`; a separate explicit reconciliation action returns them to `PENDING`. It must never requeue directly from an expired lease.

- [ ] **Step 4: Verify transitions, concurrency, stale revisions, and lease expiry**

Run: `uv run pytest tests/unit/test_job_transitions.py tests/integration/test_job_leases.py -v`

Expected: PASS, including the five Review Focus failure paths owned by the repository.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/domain src/drone_media_manager/jobs tests/unit/test_job_transitions.py tests/integration/test_job_leases.py
git commit -m "feat: add persistent job leases"
```

### Task 4: Expose authenticated worker registration, heartbeat, and job APIs

**Files:**
- Create: `src/drone_media_manager/api/app.py`
- Create: `src/drone_media_manager/api/dependencies.py`
- Create: `src/drone_media_manager/api/schemas/workers.py`
- Create: `src/drone_media_manager/api/schemas/jobs.py`
- Create: `src/drone_media_manager/api/routes/workers.py`
- Create: `src/drone_media_manager/api/routes/jobs.py`
- Create: `tests/integration/test_worker_api.py`
- Create: `tests/security/test_worker_auth.py`

**Interfaces:**
- Consumes: `ServerSettings`, `JobRepository`, and the core SQLAlchemy models.
- Produces: `create_app(settings, session_factory) -> FastAPI`.
- Produces API operations matching the approved design: register, heartbeat, claim, progress, complete, and fail.

- [ ] **Step 1: Write failing authentication and stale-update tests**

```python
def test_registration_rejects_wrong_bootstrap_token(client):
    response = client.post(
        "/api/workers/register",
        headers={"Authorization": "Bearer wrong"},
        json={"name": "windows-laptop", "capabilities": ["ingest"]},
    )
    assert response.status_code == 401

def test_progress_rejects_stale_revision(authenticated_client, claimed_job):
    response = authenticated_client.post(
        f"/api/worker-jobs/{claimed_job.id}/progress",
        json={"lease_token": claimed_job.lease_token, "revision": 0, "progress": 0.5},
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Run the tests and verify missing routes fail**

Run: `uv run pytest tests/integration/test_worker_api.py tests/security/test_worker_auth.py -v`

Expected: FAIL because `create_app` and routes are absent.

- [ ] **Step 3: Implement bootstrap pairing and authenticated mutations**

Registration accepts only the configured bootstrap bearer token, creates a random permanent worker token, stores only its SHA-256 digest, and returns the plaintext once. All later endpoints compare bearer-token digests with `hmac.compare_digest`. Error bodies use stable codes such as `invalid_worker_token`, `stale_revision`, `expired_lease`, and `invalid_transition` without returning secrets.

Every accepted mutation creates an `audit_events` row in the same transaction. Request bodies are capped by server middleware at 1 MiB for phase 0.

- [ ] **Step 4: Verify the complete worker API contract**

Run: `uv run pytest tests/integration/test_worker_api.py tests/security/test_worker_auth.py -v`

Expected: PASS for registration, heartbeat, claim, progress, completion, failure, stale revision, expired lease, and wrong token.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/api tests/integration/test_worker_api.py tests/security/test_worker_auth.py
git commit -m "feat: add authenticated worker api"
```

### Task 5: Build the Windows worker client, credential storage, and resilient poll loop

**Files:**
- Create: `src/drone_media_manager/worker/client.py`
- Create: `src/drone_media_manager/worker/credentials.py`
- Create: `src/drone_media_manager/worker/service.py`
- Create: `src/drone_media_manager/cli/worker.py`
- Create: `tests/unit/test_worker_client.py`
- Create: `tests/unit/test_worker_service.py`

**Interfaces:**
- Consumes: `WorkerSettings` and the phase-0 HTTP API.
- Produces: `CredentialStore.get_token(worker_name) -> str | None` and `set_token(worker_name, token) -> None`.
- Produces: `WorkerApiClient.register()`, `heartbeat()`, `claim()`, `progress()`, `complete()`, and `fail()` with typed request/response models.
- Produces: `WorkerService.run_once() -> PollResult` and `run_forever(stop_event) -> None`.

- [ ] **Step 1: Write failing connection-loss and token-redaction tests**

```python
def test_connection_loss_returns_offline_without_claiming(fake_http, service):
    fake_http.raise_on_heartbeat(httpx.ConnectError("mac offline"))
    assert service.run_once() == PollResult.OFFLINE
    assert fake_http.claim_calls == 0

def test_client_repr_does_not_expose_token(client):
    assert client.token not in repr(client)
```

- [ ] **Step 2: Run tests and observe missing worker modules**

Run: `uv run pytest tests/unit/test_worker_client.py tests/unit/test_worker_service.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement the typed client and polling behavior**

Use an injected `httpx.Client` with connect timeout 5 seconds and total request timeout 30 seconds. Store the permanent worker token through `keyring` under service name `DroneMediaManager`. On connection failure, return `OFFLINE`, apply capped exponential backoff from 2 to 60 seconds, and do not claim or finalize jobs. Do not log authorization headers or response secrets.

The worker CLI supports `dmm-worker pair`, `dmm-worker once`, and `dmm-worker run`. `pair` requires the bootstrap token through an interactive hidden prompt or environment variable; it never accepts secrets as command-line arguments.

- [ ] **Step 4: Verify offline recovery and CLI parsing**

Run: `uv run pytest tests/unit/test_worker_client.py tests/unit/test_worker_service.py -v`

Expected: PASS with no real network or OS credential manager dependency.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/worker src/drone_media_manager/cli/worker.py tests/unit/test_worker_client.py tests/unit/test_worker_service.py
git commit -m "feat: add resilient windows worker client"
```

### Task 6: Add OMV root mapping, dependency probes, and health reporting

**Files:**
- Create: `src/drone_media_manager/storage/roots.py`
- Create: `src/drone_media_manager/system/dependencies.py`
- Create: `src/drone_media_manager/api/routes/health.py`
- Create: `tests/unit/test_storage_roots.py`
- Create: `tests/unit/test_dependencies.py`
- Create: `tests/integration/test_health.py`

**Interfaces:**
- Consumes: host-specific `omv_root` configuration.
- Produces: `LogicalMediaPath.parse(value)`, `RootMapper.to_host_path(relative) -> Path`, and `RootMapper.to_relative(host_path) -> LogicalMediaPath`.
- Produces: `probe_executable(name, timeout_seconds=5) -> DependencyStatus` and `GET /health`.

- [ ] **Step 1: Write failing root-escape and missing-tool tests**

```python
@pytest.mark.parametrize("value", ["../outside.mp4", "/absolute.mp4", r"C:\outside.mp4"])
def test_logical_path_rejects_root_escape(value):
    with pytest.raises(UnsafePath):
        LogicalMediaPath.parse(value)

def test_missing_ffmpeg_is_degraded(fake_runner):
    fake_runner.not_found("ffmpeg")
    assert probe_executable("ffmpeg", runner=fake_runner).state == "degraded"
```

- [ ] **Step 2: Run tests and confirm failures**

Run: `uv run pytest tests/unit/test_storage_roots.py tests/unit/test_dependencies.py tests/integration/test_health.py -v`

Expected: FAIL because root mapping, probes, and health route are missing.

- [ ] **Step 3: Implement safe mapping and non-crashing probes**

Logical paths use `/` separators, are never absolute, contain no `..`, NUL, drive prefix, or empty component, and remain beneath the resolved host root. Probe `ffmpeg -version` and `ffprobe -version` with list arguments, `shell=False`, five-second timeout, and 64 KiB output cap. Missing or timed-out tools produce `degraded`, not application startup failure.

`GET /health` returns separate `database`, `omv`, `ffmpeg`, `ffprobe`, and `worker_summary` components. The OMV check performs metadata/readability checks only and creates no file.

- [ ] **Step 4: Verify root safety and health output**

Run: `uv run pytest tests/unit/test_storage_roots.py tests/unit/test_dependencies.py tests/integration/test_health.py -v`

Expected: PASS, including `../`, Windows drive-prefix, missing executable, and timeout cases.

- [ ] **Step 5: Commit**

```text
git add src/drone_media_manager/storage src/drone_media_manager/system src/drone_media_manager/api/routes/health.py tests/unit/test_storage_roots.py tests/unit/test_dependencies.py tests/integration/test_health.py
git commit -m "feat: add storage mapping and health checks"
```

### Task 7: Wire server lifecycle, structured audit logging, and recovery

**Files:**
- Create: `src/drone_media_manager/logging.py`
- Create: `src/drone_media_manager/jobs/recovery.py`
- Create: `src/drone_media_manager/cli/server.py`
- Modify: `src/drone_media_manager/api/app.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/test_logging.py`
- Create: `tests/integration/test_recovery.py`

**Interfaces:**
- Consumes: `create_app`, `JobRepository.interrupt_expired`, and settings.
- Produces: JSON log formatter with timestamp, level, event, correlation ID, actor, entity, and result.
- Produces: `recover_on_startup(session_factory, now) -> RecoveryReport`.

- [ ] **Step 1: Write failing redaction and restart-recovery tests**

```python
def test_json_log_redacts_tokens(json_formatter):
    record = make_record(extra={"authorization": "Bearer secret", "gps_track": [1, 2]})
    payload = json.loads(json_formatter.format(record))
    assert "secret" not in json.dumps(payload)
    assert payload["authorization"] == "[REDACTED]"

def test_restart_interrupts_expired_running_job(db, expired_running_job):
    report = recover_on_startup(db.session_factory, now=expired_running_job.lease_expires_at)
    assert report.interrupted_job_ids == [expired_running_job.id]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/unit/test_logging.py tests/integration/test_recovery.py -v`

Expected: FAIL because formatter and recovery service do not exist.

- [ ] **Step 3: Implement startup and shutdown behavior**

On server startup, migrate only when explicitly invoked by `dmm-server migrate`; normal startup verifies the database revision and refuses an outdated schema. Recovery interrupts expired work and records an audit event. Configure rotating JSON logs without authorization values, credential fields, full GPS tracks, or secret settings. Register `dmm-server` and `dmm-worker` in `[project.scripts]`.

- [ ] **Step 4: Run lifecycle tests and the complete phase suite**

Run: `uv run pytest tests/unit tests/integration tests/security -q`

Expected: PASS.

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```text
git add pyproject.toml src/drone_media_manager/logging.py src/drone_media_manager/jobs/recovery.py src/drone_media_manager/cli src/drone_media_manager/api/app.py tests
git commit -m "feat: add server lifecycle and recovery"
```

### Task 8: Document and verify Mac service operation and the phase checkpoint

**Files:**
- Create: `scripts/install_macos_launchd.py`
- Create: `scripts/uninstall_macos_launchd.py`
- Create: `README.md`
- Create: `Docs/operations/mac-server.md`
- Create: `Docs/operations/windows-worker.md`
- Create: `Docs/testing.md`
- Create: `tests/integration/test_server_worker_contract.py`

**Interfaces:**
- Consumes: the `dmm-server` and `dmm-worker` entrypoints.
- Produces: launch agent label `com.drone-media-manager.server` and a generated plist using the detected absolute `uv` and repository paths.

- [ ] **Step 1: Write the failing end-to-end contract test**

```python
def test_worker_registers_heartbeats_and_claims_one_job(server, fake_credentials):
    client = WorkerApiClient(server.url, credential_store=fake_credentials)
    identity = client.register("windows-laptop", {"health-check"}, server.bootstrap_token)
    client.heartbeat(identity)
    server.enqueue(kind="health-check", payload={})
    claimed = client.claim(identity)
    assert claimed.kind == "health-check"
    assert server.worker(identity.worker_id).status == "BUSY"
```

- [ ] **Step 2: Run the contract test before adding operational wiring**

Run: `uv run pytest tests/integration/test_server_worker_contract.py -v`

Expected: FAIL until test fixtures, entrypoint wiring, and worker lifecycle are complete.

- [ ] **Step 3: Add deterministic service installers and operating docs**

The installer must refuse non-macOS hosts, find `uv` with `shutil.which`, generate an absolute `ProgramArguments` list for `uv run dmm-server run`, write logs beneath `~/Library/Logs/DroneMediaManager`, and execute no command automatically. Documentation includes installation, migration, start/stop, token pairing, OMV mount prerequisites, database backup, log locations, and rollback.

- [ ] **Step 4: Run the complete automated phase gate**

Run: `uv sync --all-groups`

Run: `uv run ruff check .`

Run: `uv run ruff format --check .`

Run: `uv run mypy src`

Run: `uv run pytest tests/unit tests/integration tests/security --cov=drone_media_manager --cov-report=term-missing -q`

Expected: every command exits 0; no test requires a real SD card, OMV server, keyring, or ffmpeg installation.

- [ ] **Step 5: Perform the manual distributed checkpoint**

On the Mac, run `uv run dmm-server migrate` followed by `uv run dmm-server run`. On Windows, run `uv run dmm-worker pair`, then `uv run dmm-worker once`. Confirm the Mac reports the worker online, the worker claims a synthetic `health-check` job, and stopping/restarting both processes leaves the completed job and audit events intact.

- [ ] **Step 6: Commit**

```text
git add scripts README.md Docs/operations Docs/testing.md tests/integration/test_server_worker_contract.py
git commit -m "docs: add distributed foundation runbook"
```

## Phase 0 Completion Gate

- `dmm-server` starts on the Mac with a local SQLite database and verified migration revision.
- `dmm-worker` pairs, authenticates, heartbeats, disconnects, and reconnects without state loss.
- Job claim, renewal, stale revision, expiry, interruption, and reconciliation behavior is covered by tests.
- OMV mappings contain only canonical relative media paths in authoritative state.
- Missing ffmpeg/ffprobe is visible as degraded health and does not crash the control plane.
- Source-facing code contains no mutating filesystem operation.
- No Phase 1 ingestion implementation begins until this gate is reviewed and approved.
