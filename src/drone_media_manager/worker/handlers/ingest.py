"""Leased safe-ingest job execution with durable progress callbacks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

from drone_media_manager.ingest.copy import CopyEngine, CopyItem, PartialPrefixMismatch
from drone_media_manager.ingest.manifest import build_manifest, write_manifest_atomic
from drone_media_manager.ingest.promote import promote_no_replace
from drone_media_manager.ingest.verify import verify_copy
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)
from drone_media_manager.sources.paths import validate_source_entry
from drone_media_manager.storage.roots import LogicalMediaPath, RootMapper
from drone_media_manager.worker.snapshots import LocalSnapshotRegistry


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    status: str
    bytes_verified: int = 0
    error_code: str | None = None


class IngestJobHandler:
    """Execute each item under a live lease and never manufacture VERIFIED."""

    def __init__(
        self,
        *,
        snapshot_registry: LocalSnapshotRegistry | None = None,
        omv_root: Path | None = None,
    ) -> None:
        self._snapshot_registry = snapshot_registry
        self._root_mapper = RootMapper(omv_root) if omv_root is not None else None

    def execute(self, claimed_job: Any) -> JobExecutionResult:
        total = 0
        reporter = getattr(claimed_job, "reporter", None)
        if isinstance(claimed_job, dict):
            payload = claimed_job.get("payload", claimed_job)
        else:
            payload = claimed_job.payload
        lease_valid: Callable[[], bool] = getattr(
            claimed_job, "lease_valid", lambda: True
        )
        for item in payload.get("items", []):
            if not lease_valid():
                self._report(reporter, "interrupted", "lease_expired")
                return JobExecutionResult("INTERRUPTED", total, "lease_expired")
            try:
                outcome = self._process_item(
                    item, lease_valid, reporter, str(payload.get("snapshot_id", ""))
                )
            except PartialPrefixMismatch:
                self._report(reporter, "failed", "partial_prefix_mismatch")
                return JobExecutionResult("FAILED", total, "partial_prefix_mismatch")
            if outcome.status != "VERIFIED":
                self._report(reporter, outcome.status.lower(), outcome.error_code)
                return JobExecutionResult(outcome.status, total, outcome.error_code)
            total += outcome.bytes_verified
            self._report(reporter, "checkpoint", total)
        manifest_result = self._write_manifest(payload)
        if (
            manifest_result is not None
            and manifest_result.status == "DIVERGENT_CONFLICT"
        ):
            self._report(reporter, "failed", manifest_result.error_code)
            return JobExecutionResult("FAILED", total, manifest_result.error_code)
        self._report(reporter, "complete", total)
        return JobExecutionResult("VERIFIED", total)

    def _process_item(
        self,
        item: dict[str, Any],
        lease_valid: Callable[[], bool],
        reporter: Any,
        snapshot_id: str,
    ) -> JobExecutionResult:
        source = Path(item["source"]) if "source" in item else None
        partial = Path(item["partial"]) if "partial" in item else None
        final = Path(item["final"]) if "final" in item else None
        source_for_verify: Path | Any = source
        source_api: FilesystemReadOnlySource | None = None
        source_entry: Any = None
        if self._snapshot_registry is not None and self._root_mapper is not None:
            source_entry = self._snapshot_registry.resolve_entry(
                snapshot_id, str(item["source_rel_path"])
            )
            source_for_verify = source_entry
            partial = self._root_mapper.to_host_path(
                LogicalMediaPath.parse(str(item["partial_rel_path"]))
            )
            final = self._root_mapper.to_host_path(
                LogicalMediaPath.parse(str(item["destination_rel_path"]))
            )
            source_api = FilesystemReadOnlySource(
                self._snapshot_registry.descriptor(snapshot_id)
            )
        elif item.get("source_root"):
            descriptor = source_from_explicit_path(item["source_root"])
            source_api = FilesystemReadOnlySource(descriptor)
            relative = Path(item["source_rel_path"])
            source_entry = validate_source_entry(
                descriptor.root, descriptor.root.path / relative
            )
            source_for_verify = source_entry
        assert partial is not None
        if source_api is not None and source_entry is not None:
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
        assert partial is not None and final is not None
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
        item["source_sha256"] = result.source_sha256
        item["destination_sha256"] = result.destination_sha256
        item["status"] = "VERIFIED"
        promotion = promote_no_replace(partial, final)
        if promotion.status == "DIVERGENT_CONFLICT":
            return JobExecutionResult("FAILED", 0, "destination_conflict")
        if source_entry is not None:
            size = source_entry.stat.size
        else:
            assert source is not None
            size = source.stat().st_size
        return JobExecutionResult("VERIFIED", size)

    def _write_manifest(self, payload: dict[str, Any]) -> Any:
        if self._root_mapper is None or not payload.get("ingest_id"):
            return None
        items = [
            SimpleNamespace(
                source_rel_path=item["source_rel_path"],
                destination_rel_path=item["destination_rel_path"],
                source_size_bytes=int(item.get("source_size_bytes", 0)),
                source_sha256=item.get("source_sha256"),
                destination_sha256=item.get("destination_sha256"),
                pair_status=item.get("pair_status", "VIDEO_WITHOUT_SRT"),
                status=item.get("status", "VERIFIED"),
                error=item.get("error"),
            )
            for item in payload.get("items", [])
        ]
        manifest = build_manifest(
            SimpleNamespace(
                id=payload["ingest_id"],
                source_kind=payload.get("source_kind", "LOCAL"),
                source_fingerprint=payload.get("source_fingerprint", ""),
                items=items,
            )
        )
        first = items[0].destination_rel_path if items else "trips/unknown"
        parts = PurePosixPath(first).parts
        if len(parts) < 2:
            return None
        logical = "/".join(
            (*parts[:2], "05_MANIFESTS", f"ingest_manifest.{payload['ingest_id']}.json")
        )
        return write_manifest_atomic(
            manifest,
            self._root_mapper.to_host_path(LogicalMediaPath.parse(logical)),
        )

    @staticmethod
    def _report(reporter: Any, event: str, value: Any) -> None:
        if reporter is None:
            return
        method = getattr(reporter, event, None)
        if callable(method):
            method(value)
