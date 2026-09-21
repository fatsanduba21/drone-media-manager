# Distributed Drone Media Manager Design

**Date:** 2026-09-21

**Status:** Approved in conversation; revised after written-spec review

**Canonical product requirements:** `Docs/Specs/DRONE_MEDIA_MANAGER_SPEC_AND_PLAN.md`

## Purpose

Build a reliable home-LAN media manager for DJI footage. A Windows laptop reads an SD card, local folder, local drive, or network location and performs storage-heavy or compute-heavy work when it is online. An always-on Mac hosts the control plane and user interface. A Linux OpenMediaVault server stores originals and generated media.

The system must make interrupted work recoverable and must never turn an automated classification into deletion. Every selected source is read-only from the application's perspective, including removable media, local paths, and network shares.

## Approved deployment topology

```text
Browser on the LAN
        |
        v
Always-on Mac
|- FastAPI and responsive UI
|- authentication and authorization
|- scheduler and persistent job queue
|- worker registry and lease manager
|- SQLite database on local Mac storage
`- media gateway reading proxies from OMV
        |
        | HTTPS job protocol
        v
Windows laptop, intermittently online
|- SD discovery and read-only inventory
|- streaming copy and SHA-256 verification
|- ffprobe and ffmpeg
|- analysis and export work in later phases
`- recovery and reconciliation
        |
        | SMB
        v
Linux/OpenMediaVault
|- original media and SRT files
|- partial ingest files
|- proxies and thumbnails
|- selects and exports
`- manifests and SQLite backups
```

The Mac and Windows machine mount the same OMV share at different host-specific paths. The database stores only paths relative to a configured logical media root. The active SQLite file never resides on SMB, iCloud, or another synchronized directory. Windows never connects directly to SQLite.

## Host responsibilities

### Mac control plane

The Mac owns all authoritative application state. It runs FastAPI, the web UI, authentication, the scheduler, worker registration, job leases, audit recording, and the media gateway. It reads already-generated proxies and thumbnails from OMV so review remains available while Windows is offline.

The production process runs as native Python managed by `launchd`. The application data directory is `~/Library/Application Support/DroneMediaManager`. Development may use `uv run`, but manual execution is not the production operating model.

SQLite backups are created through a consistent SQLite backup operation and may then be copied to OMV. Copying the active database file is not an accepted backup mechanism.

### Windows processing worker

The Windows worker connects outbound to the Mac API, registers its identity and capabilities, emits heartbeats, claims eligible jobs, and reports progress and results. It owns source discovery and validation, inventory, copying, hashing, ffprobe/ffmpeg execution, later analysis, and later export generation.

The worker is allowed to read explicitly selected source roots and write only beneath the configured OMV destination root. A source may be a removable drive such as `E:`, another local drive such as `C:` or `D:`, a local folder, or an existing network share. Every source is logically read-only regardless of its physical capabilities. The source abstraction intentionally exposes no write, rename, move, or delete operations.

## Source selection and media pairing

Source discovery is not limited to removable USB volumes. The Windows worker supports two source modes:

- discovered removable volumes offered as candidates; and
- a user-supplied absolute path to a local drive, local directory, mapped drive, or UNC network location.

The user must explicitly confirm the source snapshot before ingest. The worker canonicalizes the selected root, records its source kind, and applies the same read-only capability and path-boundary checks to every source kind. A network source becoming unavailable is treated as an interrupted read, not as permission to switch paths or skip verification.

MP4 and SRT discovery is case-insensitive and pairs files by complete stem. SRT is optional. Each discovered item receives one of the explicit pair states `PAIRED`, `VIDEO_WITHOUT_SRT`, or `ORPHAN_SRT`. Missing SRT never blocks copying, catalog creation, or later review; it only limits telemetry-derived features and produces an explicit warning.

### OpenMediaVault storage

OMV stores media and regenerable derivatives. The initial layout remains compatible with the canonical specification:

```text
trips/<trip-slug>-<trip-id>/
  00_INBOX_ORIGINALS/
  01_PREVIEWS/
  02_SELECTS/YOUTUBE_16x9/
  02_SELECTS/INSTAGRAM_9x16/
  03_KEEP_ORIGINALS/
  04_EXPORTS/
  05_MANIFESTS/
  99_QUARANTINE/
```

No phase before the retention phase purges media or formats an SD card.

## Worker communication model

The worker uses an authenticated pull protocol. It polls for work rather than accepting inbound connections, which works when the laptop changes address, sleeps, or is disconnected.

Initial internal endpoints are:

```text
POST /api/workers/register
POST /api/workers/{worker_id}/heartbeat
POST /api/worker-jobs/claim
POST /api/worker-jobs/{job_id}/progress
POST /api/worker-jobs/{job_id}/complete
POST /api/worker-jobs/{job_id}/fail
POST /api/sources/snapshots
```

Every job mutation includes `worker_id`, `job_id`, `lease_token`, an idempotency key, and the expected job revision. Server timestamps are authoritative. Payloads are size-limited and schema-validated.

A claimed job receives a renewable lease. An expired lease first enters reconciliation; it is not immediately reassigned. Reconciliation examines persisted progress, the partial file, any final file, and available hashes. A stale worker cannot complete a job with an expired lease.

## State ownership and transitions

The initial distributed states are:

```text
Worker: OFFLINE -> ONLINE -> BUSY

Job: PENDING -> LEASED -> RUNNING -> COMPLETE
                         |          
                         +-> INTERRUPTED -> PENDING
                         `-> FAILED

Ingest: DISCOVERED -> COPYING -> VERIFYING -> VERIFIED
                         |            |
                         +------------+-> INTERRUPTED or FAILED
```

Transitions are validated in the service layer and committed transactionally. UI requests and worker reports cannot bypass transition rules. Optimistic revisions reject lost updates.

## Safe ingest data flow

1. The Windows worker discovers removable candidates or validates a user-supplied local or network path, then reads the explicitly selected source recursively.
2. It produces an inventory of case-insensitive MP4/SRT files, `PAIRED`, `VIDEO_WITHOUT_SRT`, and `ORPHAN_SRT` states, sizes, timestamps, source kind, and a deterministic source fingerprint.
3. The Mac displays the snapshot and requires human confirmation of the source, trip, and destination.
4. The Mac creates an ingest job. The worker claims it with a lease.
5. Preflight checks OMV availability, authorized roots, permissions, free space plus safety margin, and source stability.
6. Each file is copied in bounded chunks to a uniquely named `.partial` file in the final destination directory. Progress is checkpointed on the Mac.
7. The worker hashes source bytes while reading and independently re-reads the destination to compute its SHA-256. Source metadata is checked before and after the operation.
8. Only equal size and hash allow atomic promotion to the final name. Promotion must never replace an existing file.
9. An existing identical final file is an idempotent success. Different content at the requested destination is a conflict and is never overwritten.
10. A manifest is written atomically under `05_MANIFESTS` and contains IDs, relative paths, sizes, hashes, pair states, and errors but no credentials or host-specific absolute paths.
11. The Mac marks the ingest `VERIFIED` only when all required files and the manifest are verified.
12. For a removable-card source only, the UI may display that the card can be formatted manually when the configured redundancy policy is satisfied. Local and network sources never receive a card-formatting message. The message never authorizes deletion of source or INBOX content.

The conservative default requires a second verified copy before card release. An explicitly configured `nas_only` policy may release after one verified OMV copy and must display the reduced-redundancy warning from the product specification.

## Security boundaries

- The SD source is accessed through a read-only capability with no mutating methods.
- Paths supplied by clients are never used directly. IDs resolve to server-owned relative paths beneath configured roots.
- Absolute paths, `..`, root escapes, symlinks, and Windows reparse points that escape an authorized root are rejected.
- All subprocesses use argument arrays with `shell=False` and explicit timeouts.
- Worker credentials are created during pairing and stored in macOS Keychain and Windows Credential Manager. Tokens are excluded from URLs, manifests, and logs.
- HTTPS is the production LAN protocol. Temporary HTTP bootstrap is allowed only on an explicitly configured private address and produces a visible warning.
- Secrets and detailed GPS data are redacted from default logs.
- SQLite is local to the Mac, uses foreign keys and a busy timeout, and may use WAL only after local-path validation.
- Destructive actions require separate future design and approval. They are absent from Phases 0 and 1.

## Failure behavior

- **Windows powers off:** partial files and progress remain; jobs become interrupted after lease expiry and are reconciled on reconnect.
- **Mac restarts:** workers stop claiming or finalizing work until the control plane returns. A worker cannot decide by itself that an ingest is complete.
- **OMV disconnects:** copying stops safely; the source and all verified destination files remain untouched.
- **Source disappears or changes:** the item fails or becomes interrupted and cannot reach `VERIFIED`.
- **Network source disconnects:** the item becomes interrupted and resumes only after the same canonical source is available again.
- **Destination hash differs:** the partial or conflicting file is preserved for diagnosis and the job fails.
- **Destination already exists:** identical content is reused; divergent content produces a conflict.
- **Space becomes insufficient:** the operation stops before promotion and reports the required and available bytes.
- **Lease expires:** stale results are rejected and files are reconciled before retry.

## Initial persistence model

Migration `0001_core` creates jobs, job attempts or leases, registered workers, and audit events. Migration `0002_safe_ingest` creates trips, ingest jobs, ingest items, media files, media pairs, and file operations. Stable UUIDs, UTC timestamps, foreign keys, indexes, uniqueness constraints, and explicit state checks are required.

`ingest_items` is an intentional addition to the initial product proposal because per-file progress, partial-file identity, retries, and reconciliation cannot be represented safely by an aggregate ingest row alone.

## Geolocation and POI discovery

The later POI phase includes a provider-neutral reverse-geocoding integration. Parsed GPS samples are filtered and geographically clustered before representative coordinates are submitted to an externally configured API. The system caches responses with provider, request coordinates, returned label, provider-specific identifier, retrieval time, and confidence or precision metadata when the provider supplies it.

External place names are suggestions, not verified facts. The UI shows their source and confidence, allows a user to replace the name or coordinates, and persists that override separately. A human override always wins over cached or newly fetched provider data until explicitly cleared. Failed requests, rate limits, unavailable Internet, or ambiguous responses leave the POI as coordinates plus an optional manual name; they never block ingest or media review.

API keys are stored as secrets outside the database and manifests. Requests use timeouts, bounded retries, provider rate limits, and a descriptive user agent when required. Raw GPS tracks are not sent when a representative coordinate is sufficient. The concrete API provider is configurable so a later phase can select a service based on cost, quota, privacy, and terms without changing domain models.

## Phase boundaries

### Phase 0: distributed foundation

Phase 0 delivers a single Python package with `dmm-server` and `dmm-worker` entrypoints; host-specific configuration; FastAPI health endpoints; local SQLite and Alembic; persistent jobs, leases, worker registration, heartbeat, and audit events; OMV logical-root mapping; ffmpeg/ffprobe capability detection on Windows; and documented native `launchd` operation on Mac.

Acceptance requires the Mac to preserve its database and queue across restart, the Windows worker to connect and disconnect without losing jobs, and all source-facing code to remain read-only.

### Phase 1: distributed safe ingest

Phase 1 delivers Windows discovery of removable sources plus explicit local or network paths, inventory with optional-SRT pair states, human confirmation on the Mac, leased ingest jobs, OMV preflight, chunked partial copies, safe resume and reconciliation, independent source/destination SHA-256, duplicate and conflict handling, atomic manifests, and the conditional manual-card-release notice for removable cards only.

Acceptance requires repeat imports to be idempotent; MP4 without SRT and orphan SRT to be reported without crashing; local, removable, and network sources to use the same read-only safety boundary; divergent content never to be overwritten; and Windows, Mac, source network, or OMV interruption never to create a false `VERIFIED` state.

Later phases retain the canonical specification's catalog, proxy/UI, analysis, selects, retention, and distribution goals. They are not included in the initial implementation plan.

## Testing strategy

Every implementation task follows red-green-refactor: introduce one focused failing test, observe the expected failure, implement the minimum behavior, run the focused test, run the related suite, review security implications, and commit the independently testable result.

The test portfolio includes platform-independent unit tests, real temporary SQLite migration tests, HTTP contract tests, simulated SD, local-drive, network-source, and OMV filesystems, MP4-without-SRT and orphan-SRT fixtures, injected network and filesystem failures, Windows-specific reparse-point and atomic-promotion tests, reverse-geocoder contract and cache tests in the later POI phase, and a manual Mac-to-Windows-to-OMV smoke test at each phase checkpoint.

Python 3.13 is the primary development runtime. The initial package supports `>=3.12,<3.14`, matching the product requirement while allowing the installed 3.13.14 runtime. Dependencies are introduced only by the task that uses them.

## Explicitly deferred decisions

Proxy parameters, the concrete reverse-geocoding provider, media analysis algorithms, review UI details, retention approval semantics, quarantine periods, and iCloud export behavior remain governed by later phases of the canonical specification. The provider-neutral POI behavior above is required, but its implementation must not be pulled into Phase 0 or Phase 1.
