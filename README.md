# Drone Media Manager

Drone Media Manager is the Phase 0 distributed foundation for a Mac-hosted
control plane and an intermittently connected Windows worker. It currently
provides local SQLite migrations, authenticated worker pairing, heartbeats,
durable job leases, health reporting, structured audit logs, and recovery of
expired work.

Phase 0 does **not** ingest, copy, process, delete, retain, or format media.
The SD card remains outside the application boundary. OMV/NAS paths are
configured as logical roots and are not touched by the worker contract tests.

## Operating the foundation

- Mac server: [the server runbook](Docs/operations/mac-server.md)
- Windows worker: [the worker runbook](Docs/operations/windows-worker.md)
- Verification and safe fixtures: [testing](Docs/testing.md)

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
