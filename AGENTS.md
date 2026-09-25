# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/drone_media_manager/`. The `api/` package contains FastAPI routes and the gallery HTML in `api/static/`; `cli/` exposes the server, worker, catalog, and derivatives commands. Domain work is grouped by purpose in `ingest/`, `catalog/`, `grouping/`, `derivatives/`, `jobs/`, `sources/`, and `storage/`. SQLAlchemy models and Alembic migrations live in `db/`. Tests are split into `tests/unit/`, `tests/integration/`, and `tests/security/`, with sample media under `tests/fixtures/`. Operational guides are in `Docs/operations/`; macOS service helpers are in `scripts/`.

## Build, Test, and Development Commands

Run these from the repository root with Python 3.12 or 3.13 and `uv`:

- `uv sync --all-groups` installs the application and development dependencies.
- `uv run dmm-server migrate` applies local database migrations; `uv run dmm-server run` starts the Mac control plane.
- `uv run dmm-worker once` runs one Windows worker polling cycle.
- `uv run pytest tests/unit tests/integration tests/security -q` runs the automated suite.
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src` run lint, formatting, and type checks.

## Coding Style & Naming Conventions

Use four-space indentation, Python type annotations, and `snake_case` for modules, functions, and tests; use `PascalCase` for classes. Follow Ruff's formatter and Python 3.12 target in `pyproject.toml`. Keep mypy's strict mode passing. Put new behavior in the relevant domain package.

## Testing Guidelines

Use pytest files named `test_*.py` and test functions named `test_*`. Add unit tests for domain rules, integration tests for database/API/CLI flows, and security tests for path, authentication, and source safety boundaries. Run the full suite with coverage using `uv run pytest tests/unit tests/integration tests/security --cov=drone_media_manager --cov-report=term-missing -q`; no numeric coverage threshold is configured. Fixtures must remain safe to run without a real SD card, NAS, keyring, or ffmpeg installation.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subjects with prefixes such as `feat:`, `fix:`, `docs:`, and `test:`. Keep each commit focused. In pull requests, describe the behavior changed, cite the related issue or phase document when applicable, list verification commands, and include screenshots for gallery or other UI changes. Call out migration and ingest-safety effects explicitly.

## Security & Configuration

Start from `.env.example`; never commit `.env`, tokens, or local media. Keep the active SQLite database and derivative cache on local storage, outside synchronized or OMV roots. Preserve read-only source handling and independent destination hash verification in ingest changes.

## Windows / Codex sandbox

When running this repository on Windows under Codex Desktop, always configure
repository-local runtime directories BEFORE invoking uv, Python, or pytest.

In PowerShell:

    New-Item -ItemType Directory -Force "$PWD\.codex-runtime\uv-cache" | Out-Null
    New-Item -ItemType Directory -Force "$PWD\.codex-runtime\temp" | Out-Null

    $env:UV_CACHE_DIR = "$PWD\.codex-runtime\uv-cache"
    $env:TEMP = "$PWD\.codex-runtime\temp"
    $env:TMP = "$PWD\.codex-runtime\temp"

Verify the environment before running Python tooling:

    Write-Host "UV_CACHE_DIR=$env:UV_CACHE_DIR"
    Write-Host "TEMP=$env:TEMP"
    Write-Host "TMP=$env:TMP"

Do not invoke uv, Python, or pytest on Windows before these variables are set.

Do not use the default uv cache under:
    C:\Users\<user>\AppData\Local\uv\cache

Do not use the default Windows TEMP directory for pytest.

Do not request elevation as a workaround for Python, uv, pytest, cache, or
temporary-directory access failures.

Prefer:
    uv run python ...
    uv run pytest ...

The repository `.venv` is the project virtual environment.

These overrides are Windows/Codex-specific. Do not apply them on macOS unless
required.

### Required Windows initialization

Before running any Python tooling in Codex Desktop on Windows, execute:

    . .\scripts\dev-env.ps1

Then verify:

    $env:UV_CACHE_DIR
    $env:TEMP
    $env:TMP

Only after that run uv/Python/pytest commands.

Do not skip this initialization.

### Running pytest on Windows / Codex Desktop

Do not invoke pytest directly on Windows under Codex Desktop.

Initialize the Windows development environment first:

    . .\scripts\dev-env.ps1

Run tests only through the Windows pytest wrapper:

    .\scripts\pytest-windows.ps1 tests/unit -q

For the complete validation suite:

    .\scripts\pytest-windows.ps1 tests/unit tests/integration tests/security -q

The wrapper creates a unique pytest base temporary directory for every
invocation under:

    .codex-runtime/pytest-runs/<unique-run-id>

The pytest cache is stored under:

    .codex-runtime/pytest-cache

Each pytest invocation must use a new unique temporary directory.

Do not reuse, delete, clean, reset ACLs, or modify permissions on temporary
directories created by previous Codex sandbox runs.

Do not manually pass --basetemp when using the wrapper.

Do not request elevated privileges to work around pytest temporary-directory
or cache access failures.

If pytest fails with a Windows permission error inside the unique temporary
directory created for the current invocation, report the failing path and
error instead of attempting ACL changes or privilege elevation.

