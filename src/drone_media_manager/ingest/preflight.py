"""Read-only source and OMV destination preflight checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from drone_media_manager.ingest.inventory import Inventory
from drone_media_manager.sources.read_only import ReadOnlySource
from drone_media_manager.storage.capacity import CapacityProbe, FilesystemCapacity
from drone_media_manager.storage.destination import PlannedDestination


@dataclass(frozen=True, slots=True)
class PreflightPolicy:
    reserve_bytes: int = 0
    reserve_percent: float = 0.0


@dataclass(frozen=True, slots=True)
class PreflightError:
    code: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    allowed: bool
    errors: tuple[PreflightError, ...]


def run_preflight(
    inventory: Inventory,
    source: ReadOnlySource,
    destination: PlannedDestination,
    policy: PreflightPolicy,
    capacity: CapacityProbe | None = None,
) -> PreflightReport:
    """Validate current source and destination without ever opening source for write."""

    errors: list[PreflightError] = []
    for entry in inventory.entries:
        if source.stat(entry) != entry.stat:
            errors.append(PreflightError("source_changed"))
            break
    root = destination.final_path.parents[3]
    if not root.exists() or not root.is_dir():
        errors.append(PreflightError("destination_offline"))
    if destination.collision:
        errors.append(PreflightError("unsafe_destination"))
    if not errors:
        measured = (capacity or FilesystemCapacity()).inspect(root)
        reserve = max(
            policy.reserve_bytes, int(measured.total_bytes * policy.reserve_percent)
        )
        if measured.available_bytes < inventory.total_bytes + reserve:
            errors.append(PreflightError("insufficient_space"))
        else:
            try:
                _probe_destination(destination.final_path.parent)
            except OSError:
                errors.append(PreflightError("unsafe_destination"))
    return PreflightReport(allowed=not errors, errors=tuple(errors))


def _probe_destination(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / f".dmm-preflight-{uuid4().hex}.probe"
    try:
        with probe.open("xb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if probe.exists():
            probe.unlink()
