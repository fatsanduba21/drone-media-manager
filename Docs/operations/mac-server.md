# Mac server runbook

The Mac is the control-plane host. It owns the local SQLite database and
serves the authenticated API used by the Windows worker. This runbook covers
only the Phase 0 foundation; it does not authorize media ingestion or
deletion.

## Prerequisites

1. Install Python 3.12 or 3.13 and `uv`.
2. Clone the repository to a stable local path.
3. Create a local `.env` from `.env.example` and set a bootstrap token of at
   least 32 characters.
4. Set `DMM_DATABASE_PATH` to a local path such as
   `~/Library/Application Support/DroneMediaManager/server.sqlite3`.
5. Set `DMM_OMV_ROOT` to the mounted OMV media root. The active database must
   remain outside that root.

## Install the launch agent

From the repository root:

```bash
uv run python scripts/install_macos_launchd.py
```

The installer validates macOS, resolves `uv`, and writes a deterministic
`~/Library/LaunchAgents/com.drone-media-manager.server.plist`. It does not
call `launchctl`, start the server, or stop an existing server. Logs are
configured below `~/Library/Logs/DroneMediaManager`.

Inspect the generated file before loading it:

```bash
plutil -lint ~/Library/LaunchAgents/com.drone-media-manager.server.plist
```

## Migration and start/stop

Run migrations explicitly before the first start or after an upgrade:

```bash
uv run dmm-server migrate
uv run dmm-server run
```

For launchd operation, loading and unloading are deliberate operator actions:

```bash
launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/com.drone-media-manager.server.plist
launchctl kickstart -k gui/"$(id -u)"/com.drone-media-manager.server
launchctl kill SIGTERM gui/"$(id -u)"/com.drone-media-manager.server
launchctl bootout gui/"$(id -u)"/com.drone-media-manager.server
```

The plist's `KeepAlive` setting is useful for an always-on server, but it is
not a substitute for checking the logs and database revision after restart.

## Pairing the worker

On Windows, set `DMM_WORKER_BOOTSTRAP_TOKEN` only for the pairing command or
enter it at the hidden prompt. The token is exchanged once for a permanent
worker token stored by the worker credential store. Do not put either token in
shell history or a command-line argument.

## Backup and rollback

Stop the server before taking a simple file backup. Keep the database and its
SQLite sidecars together, or use SQLite's online backup facility:

```bash
sqlite3 "$DMM_DATABASE_PATH" ".backup '$DMM_DATABASE_PATH.backup'"
```

Keep a copy of the repository and the previous database backup before
migrations. To roll back an application release, stop the service, restore a
known-good database backup if the schema changed, check out the previous
revision, and run the matching `uv sync`; do not delete media or logs as part
of rollback.

To uninstall only the managed launch agent plist:

```bash
uv run python scripts/uninstall_macos_launchd.py --yes
```

This command never unloads launchd and never removes the database, OMV media,
logs, `.env`, or other user configuration. Stop/unload the service explicitly
first when that is desired.

## Logs

- `~/Library/Logs/DroneMediaManager/server.log`
- `~/Library/Logs/DroneMediaManager/server.error.log`

Logs are structured and intentionally omit bearer tokens, credential values,
full GPS tracks, and secret settings. A worker showing `BUSY` indicates a
leased job, not that media processing exists in Phase 0.
