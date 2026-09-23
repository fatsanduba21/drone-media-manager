# Phase 2D Selection and Separate Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Protect the gallery, persist per-user selection, and deliver selected OMV originals as separate files without ZIP.

**Architecture:** A local user/session schema supports HTTPS-only cookie login and CSRF. Server-side catalog authorization protects every media URL. Selection is stored in SQLite, and a preflight endpoint lists validated originals for browser-initiated individual downloads.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, Alembic, SQLite, Argon2id, server-rendered HTML, pytest.

**Spec:** Docs/PHASE_2D_DOWNLOAD_DESIGN.md

## Global Constraints

- Branch codex/phase-2d-selection-download starts at origin/main 3aaeafc.
- Do not change worker authentication, /health, bind exposure, originals, proxies, or derivative cache.
- Use only ORIGINAL AssetFile rows; reject client-supplied paths and unsafe OMV resolution.
- Require HTTPS for browser credentials and Secure cookies.
- No ZIP, no CapCut integration, and no Phase 2E features.
- Preserve the untracked documents in the main checkout.

## Review Focus

- A direct thumbnail or proxy URL without a session returns 401 even if the page is bypassed.
- A valid session belonging to another user does not expose that user's selection.
- A file removed between preflight and download is rejected by the individual request.
- Editorial filenames with Unicode, controls, separators, or collisions remain safe and deterministic.
- A browser blocking automatic multiple downloads leaves visible individual recovery links.

---

### Task 1: Schema and password primitives

**Files:** src/drone_media_manager/db/models/auth.py, src/drone_media_manager/db/migrations/versions/0005_gallery_auth.py, src/drone_media_manager/db/migrations/env.py, src/drone_media_manager/auth/passwords.py, pyproject.toml, uv.lock, tests/integration/test_phase_2d_schema.py, tests/unit/test_passwords.py.

- [ ] Write tests for upgrade/downgrade, foreign keys, unique selection, password verification and wrong passwords.
- [ ] Run targeted pytest and confirm the expected failure.
- [ ] Add Argon2id dependency and implement models, migration, and password helpers.
- [ ] Run targeted pytest, Ruff and mypy; commit the schema slice.

### Task 2: HTTPS login, session, CSRF, and access gate

**Files:** src/drone_media_manager/api/app.py, src/drone_media_manager/api/auth.py, src/drone_media_manager/api/routes/auth.py, src/drone_media_manager/cli/server.py, tests/integration/test_phase_2d_auth.py, tests/integration/test_catalog_gallery.py.

- [ ] Write failing tests for HTTP refusal, login/logout, expiration, invalid credentials, rate limit, CSRF, direct media authorization and worker/health regression.
- [ ] Implement opaque digested session tokens, Secure cookies, login CSRF, authenticated route gate and hidden-password user CLI.
- [ ] Adapt existing gallery fixture to authenticate over HTTPS.
- [ ] Run targeted pytest and full suite; commit the authentication slice.

### Task 3: Persistent selection

**Files:** src/drone_media_manager/api/routes/selection.py, src/drone_media_manager/api/routes/catalog.py, src/drone_media_manager/api/gallery.py, tests/integration/test_phase_2d_selection.py.

- [ ] Write failing tests for user isolation, idempotent select/unselect, persistence after login, CSRF and trip counts.
- [ ] Implement selection API and gallery forms with state shown on cards and detail.
- [ ] Run targeted pytest and full suite; commit the selection slice.

### Task 4: Original downloads and batch preflight

**Files:** src/drone_media_manager/catalog/downloads.py, src/drone_media_manager/api/routes/catalog.py, src/drone_media_manager/api/gallery.py, tests/integration/test_phase_2d_downloads.py.

- [ ] Write failing tests for ORIGINAL bytes, editorial names, duplicates, missing/unavailable files, traversal, symlink, wrong trip, empty selection and bounded delivery.
- [ ] Implement safe original resolution, individual FileResponse and selected-download preflight.
- [ ] Add Chrome batch initiation and individual recovery links without ZIP.
- [ ] Run targeted pytest and full suite; commit the download slice.

### Task 5: Operations and verification

**Files:** Docs/02_FASE_2_OMV_MAC_GALERIA_SELECAO_DOWNLOAD.md, Docs/operations/gallery.md, Docs/FASE_2D_CHECKPOINT_2026-09-23.md.

- [ ] Document backup, HTTPS, migration, user creation, Chrome permission and hash verification.
- [ ] Run pytest general, Ruff check/format, mypy and record exact results.
- [ ] Publish the branch; on the Mac, back up and verify SQLite before migration, preserve local state, migrate, restart only when needed, and run real acceptance.
- [ ] Record executed evidence and pending checks without claiming unexecuted acceptance.
