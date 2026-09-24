# Drone Media Manager

Drone Media Manager is the Phase 0 distributed foundation for a Mac-hosted
control plane and an intermittently connected Windows worker. It currently
provides local SQLite migrations, authenticated worker pairing, heartbeats,
durable job leases, health reporting, structured audit logs, and recovery of
expired work.

Phase 1 adds a guarded safe-ingest checkpoint: sources are read-only,
destination files are independently hashed, divergent files are never
overwritten, and removable-card release remains policy-controlled. See the
[safe-ingest runbook](Docs/operations/safe-ingest.md).

## Safe ingest (Phase 1)

```powershell
uv run dmm-worker scan C:\DMM-TestSource
uv run dmm-worker ingest --dry-run C:\DMM-TestSource
uv run dmm-worker submit C:\DMM-TestSource
```

Confirm and monitor on the Mac with `uv run dmm-server ingest confirm SNAPSHOT_ID --trip TRIP_ID` and `uv run dmm-server ingest status INGEST_ID`. Exit codes are 0 (success), 2 (configuration), 3 (retryable interruption), and 4 (integrity/conflict). The source is never modified; see [the complete runbook](Docs/operations/safe-ingest.md).

## Operating the foundation

- Mac server: [the server runbook](Docs/operations/mac-server.md)
- Windows worker: [the worker runbook](Docs/operations/windows-worker.md)
- Verification and safe fixtures: [testing](Docs/testing.md)
- Phase 3A grouping and gallery: [grouping runbook](Docs/operations/grouping.md)

The service is LAN-oriented. Keep the server bound to loopback until TLS,
authentication, and a restricted LAN firewall rule are configured for a real
deployment.

## Development

```text
uv sync --all-groups
uv run pytest tests/unit tests/integration tests/security -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

The database is local to the Mac. Do not place the active SQLite file on OMV,
SMB, iCloud, or another synchronized directory.
