"""Leased safe-ingest job execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drone_media_manager.ingest.promote import promote_no_replace
from drone_media_manager.ingest.verify import verify_copy


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    status: str
    bytes_verified: int = 0
    error_code: str | None = None


class IngestJobHandler:
    """Execute the file-level safety checks for one claimed job."""

    def execute(self, claimed_job: Any) -> JobExecutionResult:
        total = 0
        for item in claimed_job.payload.get("items", []):
            source = Path(item["source"])
            partial = Path(item["partial"])
            final = Path(item["final"])
            result = verify_copy(source, partial, item["source_sha256"])
            if not result.verified:
                return JobExecutionResult("FAILED", total, result.error_code)
            promotion = promote_no_replace(partial, final)
            if promotion.status == "DIVERGENT_CONFLICT":
                return JobExecutionResult("FAILED", total, "destination_conflict")
            total += source.stat().st_size
        return JobExecutionResult("VERIFIED", total)
