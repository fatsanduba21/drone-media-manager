# Mac server runbook

The Mac is the control-plane host. It owns the local SQLite database and
serves the authenticated API used by the Windows worker. This runbook covers
the Phase 0 foundation and Phase 2A catalog import. It does not copy or
delete media.

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

## Phase 2A: import the Phase 1 editorial manifest

On the Mac, mount the OMV share so `DMM_OMV_ROOT` points to the directory
containing each trip slug. Keep `DMM_DATABASE_PATH` on local storage. The
normal server settings also require `DMM_WORKER_BOOTSTRAP_TOKEN` (at least 32
characters), even when using the catalog CLI. Set these in the existing
`.env` or export them in the shell. Replace the example mount path below:

```bash
export DMM_OMV_ROOT='/Volumes/OMV/drone-organizado'
export DMM_DATABASE_PATH="$HOME/Library/Application Support/DroneMediaManager/server.sqlite3"
# Set DMM_WORKER_BOOTSTRAP_TOKEN in .env or the environment; do not put its value in shell history.
uv run dmm-server migrate
manifest="$DMM_OMV_ROOT/teste-fase-1/MANIFESTO.json"
uv run dmm-catalog preview "$manifest"
uv run dmm-catalog import "$manifest"
uv run dmm-catalog import "$manifest"
```

`preview` is the dry run and does not write. Both commands print JSON with
trip, schema version, asset counts, conflicts, possible duplicates, and file
availability. The import stores one audit row per accepted execution. Exit
code 2 means invalid/unsupported manifest, conflict, or partial physical
availability. `--verify-hash` after either command checks every media hash,
which can take time for large videos; without it, the CLI still checks that
every physical file exists and is a regular file.

Expected after the first import of the accepted manifest: 1 Trip, 14
CatalogAssets, 18 AssetFiles (5 MP4 originals, 4 SRT, 9 JPG originals),
18 `AVAILABLE`. The second import must report `created_assets=0`,
`created_files=0`, `conflicts=0`, `possible_duplicates=0`.

To check the Mac handoff independently of Windows:

1. Stop or disconnect the Windows machine used for Phase 1. Keep the Mac and
   OMV online.
2. Run `uv run dmm-catalog preview "$manifest" --verify-hash` on the Mac.
   Confirm 18 available, zero missing/unavailable, zero conflicts. This reads
   all 18 files from the Mac's OMV mount and compares their SHA-256 hashes.
3. Check SQLite counts locally:

   ```bash
   sqlite3 "$DMM_DATABASE_PATH" 'SELECT COUNT(*) FROM trips; SELECT COUNT(*) FROM catalog_assets; SELECT COUNT(*) FROM asset_files; SELECT role, COUNT(*) FROM asset_files GROUP BY role; SELECT availability_status, COUNT(*) FROM asset_files GROUP BY availability_status;'
   ```

4. Record mount path, command output, database counts, and whether Windows
   remained off. The Windows acceptance documented in
   `Docs/FASE_2A_CHECKPOINT_2026-09-22.md` does not replace this Mac test.

The new Alembic revision is `0003_catalog`; it adds `catalog_assets`,
`asset_files`, and `manifest_imports` without modifying legacy ingest tables.
`Trip.nas_rel_path` for a newly created trip is the trip slug, matching
`DMM_OMV_ROOT/<slug>`. A same-slug Trip with a different name is a conflict.
A compatible existing Trip retains its `nas_rel_path` to avoid changing legacy
ingest behavior; editorial files are resolved from manifest output paths.
Files from a `PLANNED` asset are `UNVERIFIED`; missing files
are `MISSING`; hash mismatches under `--verify-hash` are `HASH_MISMATCH`. A known mismatch stays unavailable until a successful
new `--verify-hash` run. None are counted as `AVAILABLE`.
