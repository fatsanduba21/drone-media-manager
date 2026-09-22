"""Deterministic OMV-relative destination planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.sources.models import SourceEntry
from drone_media_manager.storage.roots import LogicalMediaPath, RootMapper, UnsafePath

_SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class TripDestination:
    id: str
    slug: str


@dataclass(frozen=True, slots=True)
class PlannedDestination:
    relative_path: LogicalMediaPath
    final_path: Path
    partial_path: Path
    collision: bool


class DestinationPlanner:
    def __init__(self, mapper: RootMapper) -> None:
        self.mapper = mapper

    def plan(
        self, trip: TripDestination, source_entry: SourceEntry
    ) -> PlannedDestination:
        if not _SAFE_SLUG.fullmatch(trip.slug) or not trip.id:
            raise UnsafePath("trip destination requires a sanitized slug and stable id")
        source_relative = source_entry.relative_path.as_posix()
        relative = LogicalMediaPath.parse(
            f"trips/{trip.slug}-{trip.id}/00_INBOX_ORIGINALS/{source_relative}"
        )
        final_path = self.mapper.to_host_path(relative)
        partial = final_path.parent / f".{final_path.name}.{trip.id}.partial"
        return PlannedDestination(
            relative_path=relative,
            final_path=final_path,
            partial_path=partial,
            collision=final_path.exists(),
        )
