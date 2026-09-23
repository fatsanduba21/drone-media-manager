# Phase 2C: catalog API and first gallery

Base: `origin/main` at `1c8e475ae16cbb0c1fbb6dbcdf5b9668327143af`.
The existing catalog and derivatives tables are sufficient; this phase has no migration.

1. Add integration tests for trip and asset responses, all five filters, missing records, and the browser pages. Use a migrated temporary SQLite database with real local derivative files. Run the new tests and confirm they fail for absent routes.
2. Implement read-only catalog routes over `Trip`, `CatalogAsset`, and `Derivative`. Return only editorial metadata and media links addressed by `asset_id`; expose no original paths. Run focused tests.
3. Add tests for READY-only derivatives, path traversal and symlink escape, thumbnail cache validation, and proxy byte ranges (including invalid and unsatisfiable ranges). Confirm failures, then implement bounded file serving and rerun tests.
4. Add a small server-rendered trips, gallery, and detail/player UI with a portrait-safe player. Verify the pages and navigation with integration tests.
5. Run full `pytest`, `ruff check .`, and `mypy src`. Review the diff and commit. Push the branch without merging main.
6. If remote Mac access is available, update its checkout from GitHub, restart the existing LaunchAgent only to load changed server code, and validate the 14 real assets, two portrait filters, proxy seek, return navigation, and `/health`. Record exactly what was observed.
