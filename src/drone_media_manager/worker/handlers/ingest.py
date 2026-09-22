"""Leased safe-ingest job execution with durable progress callbacks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drone_media_manager.ingest.copy import CopyEngine, CopyItem, PartialPrefixMismatch
from drone_media_manager.ingest.promote import promote_no_replace
from drone_media_manager.ingest.verify import verify_copy
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)
from drone_media_manager.sources.paths import validate_source_entry


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    status: str
    bytes_verified: int = 0
    error_code: str | None = None


class IngestJobHandler:
    """Execute each item under a live lease and never manufacture VERIFIED."""

    def execute(self, claimed_job: Any) -> JobExecutionResult:
        total = 0
        reporter = getattr(claimed_job, "reporter", None)
        lease_valid: Callable[[], bool] = getattr(
            claimed_job, "lease_valid", lambda: True
        )
        for item in claimed_job.payload.get("items", []):
            if not lease_valid():
                self._report(reporter, "interrupted", "lease_expired")
                return JobExecutionResult("INTERRUPTED", total, "lease_expired")
            try:
                outcome = self._process_item(item, lease_valid, reporter)
            except PartialPrefixMismatch:
                self._report(reporter, "failed", "partial_prefix_mismatch")
                return JobExecutionResult("FAILED", total, "partial_prefix_mismatch")
            if outcome.status != "VERIFIED":
                self._report(reporter, outcome.status.lower(), outcome.error_code)
                return JobExecutionResult(outcome.status, total, outcome.error_code)
            total += outcome.bytes_verified
            self._report(reporter, "checkpoint", total)
        self._report(reporter, "complete", total)
        return JobExecutionResult("VERIFIED", total)

    def _process_item(
        self, item: dict[str, Any], lease_valid: Callable[[], bool], reporter: Any
    ) -> JobExecutionResult:
        source = Path(item["source"])
        partial = Path(item["partial"])
        final = Path(item["final"])
        source_for_verify: Path | Any = source
        source_api: FilesystemReadOnlySource | None = None
        source_entry: Any = None
        if item.get("source_root"):
            descriptor = source_from_explicit_path(item["source_root"])
            source_api = FilesystemReadOnlySource(descriptor)
            relative = Path(item["source_rel_path"])
            source_entry = validate_source_entry(
                descriptor.root, descriptor.root.path / relative
            )
            source_for_verify = source_entry
        if not partial.exists() and source_api is not None and source_entry is not None:
            copied = CopyEngine(source_api).copy_or_resume(
                CopyItem(
                    str(item.get("id", source_entry.relative_path)),
                    source_entry,
                    partial,
                ),
                progress=lambda value: self._report(reporter, "progress", value),
                lease_valid=lease_valid,
            )
            if copied.status == "INTERRUPTED":
                return JobExecutionResult(
                    "INTERRUPTED", copied.bytes_copied, "lease_expired"
                )
            expected_hash = copied.source_sha256
            if expected_hash is None:
                return JobExecutionResult(
                    "FAILED", copied.bytes_copied, "source_unavailable"
                )
        else:
            expected_hash = item["source_sha256"]
        self._report(reporter, "verifying", None)
        result = verify_copy(source_for_verify, partial, expected_hash)
        if not result.verified:
            status = (
                "INTERRUPTED"
                if result.error_code
                in {"source_unavailable", "destination_unavailable"}
                else "FAILED"
            )
            return JobExecutionResult(status, 0, result.error_code)
        self._report(reporter, "verified", result.destination_sha256)
        promotion = promote_no_replace(partial, final)
        if promotion.status == "DIVERGENT_CONFLICT":
            return JobExecutionResult("FAILED", 0, "destination_conflict")
        return JobExecutionResult("VERIFIED", source.stat().st_size)

    @staticmethod
    def _report(reporter: Any, event: str, value: Any) -> None:
        if reporter is None:
            return
        method = getattr(reporter, event, None)
        if callable(method):
            method(value)
