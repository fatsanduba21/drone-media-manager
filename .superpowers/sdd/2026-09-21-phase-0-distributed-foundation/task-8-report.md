# Task 8 report — distributed foundation runbook

## Scope and baseline

- Task: Phase 0, Task 8 only.
- Branch: `main`.
- Baseline HEAD: `423406b feat: add server lifecycle and recovery`.
- Existing untracked `Docs/superpowers/prompts/` was preserved; `uv.lock` was not modified.
- Task 7 was present: `dmm-server`, `dmm-worker`, worker registration/heartbeat, job claim, and recovery are implemented.
- No source-facing ingestion, copy, media processing, deletion, retention, or card-formatting implementation was added.

## Changes

- Added `scripts/install_macos_launchd.py`.
  - Refuses non-Darwin hosts.
  - Resolves `uv` with `shutil.which` and fails clearly when absent.
  - Emits deterministic plist label `com.drone-media-manager.server`.
  - Uses absolute `uv`, project, plist, and log paths; `ProgramArguments` is `uv run dmm-server run`.
  - Places logs under `~/Library/Logs/DroneMediaManager`.
  - Writes only; it does not invoke `launchctl` or start/stop a service.
  - Sets `RunAtLoad` false so a deliberate load does not implicitly start the server.
- Added `scripts/uninstall_macos_launchd.py`.
  - Requires macOS and explicit `--yes` confirmation.
  - Removes only the managed plist; it does not unload launchd or delete database, media, logs, or configuration.
- Added `README.md`, `Docs/operations/mac-server.md`, `Docs/operations/windows-worker.md`, and `Docs/testing.md` covering installation, migration, start/stop, pairing, OMV mount prerequisites, backup, logs, rollback, and the Phase 0 boundary.
- Added `tests/integration/test_server_worker_contract.py` for registration, heartbeat, synthetic `health-check` claim, and `BUSY` state using temporary SQLite and an in-process HTTP transport.

## Evidence

- Contract test: `uv run pytest tests/integration/test_server_worker_contract.py -v` → `1 passed`.
- Installer contract smoke check with fake macOS/uv state → `installer contract passed`.
- `uv sync --all-groups` → passed.
- `uv run ruff check .` → passed.
- Focused `ruff check` and `ruff format --check` for new scripts/test → passed.
- `uv run mypy src` → passed.
- Full suite: `uv run pytest tests/unit tests/integration tests/security --cov=drone_media_manager --cov-report=term-missing -q` → `142 passed`.
- `git diff --check` → passed.

## Gate exception

The literal full command `uv run ruff format --check .` exits 1 because pre-existing files outside this task are unformatted, including the phase plan markdown and existing source/tests. Formatting those files would violate the allowed-file scope and alter unrelated work. All files created by Task 8 pass focused formatting checks.

## Independent review

- No installer/uninstaller code invokes `launchctl`.
- The only unlink operation targets the exact managed plist path and is confirmation-gated.
- Paths written into the plist are resolved absolute paths.
- Documentation explicitly avoids claiming iCloud synchronization, backup completion, or Phase 1 media behavior.
- The contract uses no real SD card, NAS/OMV, keyring, ffmpeg, or external network.

## Decisions

1. Adapted the plan's illustrative client/server pseudo-interfaces to the existing Task 7 `WorkerApiClient` API (`register(name, capabilities)` plus a second client with the returned token). This preserves the implemented public contract.
2. The contract test passed immediately because Task 7 already implemented the required lifecycle. This is recorded as evidence of the checkpoint.
3. Did not format unrelated pre-existing files; the full format-gate failure remains explicitly reported above.

## Commit

Pending: `docs: add distributed foundation runbook`