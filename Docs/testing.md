# Testing and Phase 0 checkpoint

The test suite uses temporary SQLite databases, FastAPI's in-process client,
fake HTTP transports, and fake credential stores. It never requires a real SD
card, NAS/OMV server, keyring, or ffmpeg installation.

## Local gate

Run from the repository root:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest tests/unit tests/integration tests/security --cov=drone_media_manager --cov-report=term-missing -q
git diff --check
```

The distributed contract is isolated and can be run while iterating:

```bash
uv run pytest tests/integration/test_server_worker_contract.py -v
```

It registers a synthetic Windows worker, sends a heartbeat, enqueues a
synthetic `health-check` job, claims it, and verifies `BUSY`. No real network
socket is opened.

## Manual distributed checkpoint

On the Mac:

```bash
uv run dmm-server migrate
uv run dmm-server run
```

On Windows:

```powershell
uv run dmm-worker pair
uv run dmm-worker once
```

Confirm the worker becomes online, claims the synthetic health-check job, and
that a stop/restart preserves the completed job and audit events. This manual
checkpoint is operational evidence only; it does not authorize Phase 1
ingestion.

## Safety review checklist

Before accepting the Phase 0 checkpoint, inspect the diff for:

- no `launchctl` invocation in the installer or uninstaller;
- absolute `uv`, project, plist, and log paths;
- no delete outside the managed plist;
- no source-facing write, copy, ingest, media processing, retention, or card
  formatting code;
- no documentation claim that local files are synchronized to iCloud or that
  a local copy is a backup without a verified restore.

## Phase 1 safe-ingest checkpoint

See [the safe-ingest runbook](operations/safe-ingest.md). The automated gate
covers independent hashing, no-replace promotion, resumable partials,
idempotent repeat import, and source non-mutation.
