# SDD ledger — plan: Docs/superpowers/plans/2026-09-21-phase-0-distributed-foundation.md

Pre-flight: Task 8 consumes the Task 7 server/worker entrypoints and API; verified present at baseline `423406b`.

Task 8: Ruling: The contract test uses the existing Task 7 `WorkerApiClient` API rather than the plan's illustrative three-argument registration pseudo-interface; this preserves the shipped interface, cost if wrong: the test would need a small adapter if the public API is later changed.
Task 8: Ruling: The full repository format check remains red on pre-existing files outside the allowed scope; Task 8 files pass focused formatting, cost if wrong: unrelated formatting debt remains visible until a separate cleanup task.
Task 8: complete (tests: contract 1 passed; full suite 142 passed; lint/checks passed except pre-existing full format debt)

Phase 1 continuation (2026-09-22): complete for the requested distributed ingest path.
- Added worker-local snapshot registry; server payloads and manifests contain logical paths only.
- Confirmation now emits the complete ingest item payload; worker resolves source and OMV paths at execution time.
- Worker reports API-backed progress/revisions; server mirrors ingest/item states on progress, completion, and failure.
- Worker persists and replays the canonical manifest atomically; divergent manifest/destination content remains a conflict.
- RED→GREEN evidence: snapshot registry, logical path execution, manifest persistence, and payload contract tests.
- Verification: `uv run pytest tests/unit tests/integration tests/security -q` => 201 passed, 1 skipped; `uv run ruff check .` => passed; `uv run mypy src` => passed.
- Full `ruff format --check .` remains red only on pre-existing files outside the touched scope, as recorded above.
