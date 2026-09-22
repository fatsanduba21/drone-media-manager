"""Conservative policy for releasing removable source cards."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BackupPolicy(StrEnum):
    REQUIRE_SECOND_COPY = "REQUIRE_SECOND_COPY"
    NAS_ONLY = "NAS_ONLY"


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    card_format_allowed: bool
    reason: str
    warning: str | None = None


def evaluate_release(ingest: object, backup_policy: BackupPolicy) -> ReleaseDecision:
    if str(getattr(ingest, "source_kind", "")) != "REMOVABLE":
        return ReleaseDecision(False, "source_is_not_removable")
    if str(getattr(ingest, "status", "")) != "VERIFIED":
        return ReleaseDecision(False, "ingest_not_verified")
    if str(getattr(ingest, "manifest_status", "")) != "VERIFIED":
        return ReleaseDecision(False, "manifest_not_verified")
    if any(
        str(getattr(item, "status", "")) != "VERIFIED"
        for item in getattr(ingest, "items", ())
    ):
        return ReleaseDecision(False, "items_not_verified")

    if backup_policy is BackupPolicy.REQUIRE_SECOND_COPY:
        if not _backup_verified(ingest):
            return ReleaseDecision(False, "second_verified_copy_required")
        return ReleaseDecision(True, "second_copy_verified")
    if backup_policy is BackupPolicy.NAS_ONLY:
        return ReleaseDecision(
            True,
            "nas_only",
            "Only one verified copy exists; keep the source card until a second copy is verified.",
        )
    raise ValueError(f"unsupported backup policy: {backup_policy}")


def _backup_verified(ingest: object) -> bool:
    return bool(
        getattr(ingest, "backup_verified", False)
        or getattr(ingest, "verified_backup", False)
        or getattr(ingest, "backup_status", "") == "VERIFIED"
    )
