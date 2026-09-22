# Windows worker runbook

The Windows worker is a client of the Mac control plane. In Phase 0 it proves
pairing, liveness, and synthetic job leasing. It does not read an SD card,
copy media, invoke ffmpeg, delete files, or format a card.

## Prerequisites

1. Windows 11, Python 3.12 or 3.13, and `uv`.
2. A checkout of the same project revision as the Mac server.
3. A reachable Mac URL in `DMM_SERVER_URL`.
4. A local worker name in `DMM_WORKER_NAME`.
5. `DMM_OMV_ROOT` pointing to the expected local representation of the OMV
   share. The share must be mounted and readable before a real media feature
   is introduced; Phase 0 does not create files or validate a NAS.

The active Mac SQLite database is never placed on this mount. Use a stable
SMB mapping or UNC path for future media configuration; do not rely on a
drive letter in authoritative state.

## Pair and run

From the repository root:

```powershell
uv sync --all-groups
$env:DMM_WORKER_BOOTSTRAP_TOKEN = Read-Host -AsSecureString
uv run dmm-worker pair
uv run dmm-worker once
uv run dmm-worker run
```

Prefer the hidden prompt when the environment variable would persist longer
than the pairing command. `pair` stores the worker identity and permanent
token through the configured credential store; later commands use that token.
If the token or identity is missing, pair again rather than copying secrets
into a command-line argument.

The worker heartbeats before claiming work. A connection failure reports an
offline state and does not claim a job. A claimed job changes the server-side
worker state to `BUSY`; completing or failing it returns the worker to
`ONLINE`.

## OMV mount checklist

Before any future media feature is enabled, confirm manually that:

- the Windows account running the worker can read the intended OMV share;
- the mount survives reconnects and sleep/wake;
- the configured logical root is below the approved share root;
- the Mac server and Windows worker agree on the logical relative path;
- the active database remains on local disk, never SMB or iCloud.

These checks are operational prerequisites, not evidence that synchronization
or backup has occurred.
