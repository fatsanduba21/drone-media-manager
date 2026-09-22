"""Capacity abstraction for OMV preflight checks."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Capacity:
    available_bytes: int
    total_bytes: int


class CapacityProbe(Protocol):
    def inspect(self, root: Path) -> Capacity: ...


class FilesystemCapacity:
    def inspect(self, root: Path) -> Capacity:
        usage = shutil.disk_usage(root)
        return Capacity(available_bytes=usage.free, total_bytes=usage.total)
