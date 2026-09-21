"""Map canonical logical media paths to a configured host root."""

from __future__ import annotations

import ntpath
from dataclasses import dataclass
from pathlib import Path


class UnsafePath(ValueError):
    """Raised when a logical or physical path crosses a storage boundary."""


@dataclass(frozen=True, slots=True)
class LogicalMediaPath:
    value: str

    @classmethod
    def parse(cls, value: str) -> LogicalMediaPath:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise UnsafePath("logical media paths must be non-empty and contain no NUL")
        if "\\" in value or value.startswith("/") or ntpath.splitdrive(value)[0]:
            raise UnsafePath("logical media paths must use relative / separators")
        components = value.split("/")
        if any(component in {"", ".", ".."} for component in components):
            raise UnsafePath("logical media paths contain an unsafe component")
        return cls("/".join(components))

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.value.split("/"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RootMapper:
    omv_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "omv_root", self.omv_root.expanduser().resolve(strict=False))

    def to_host_path(self, relative: LogicalMediaPath) -> Path:
        logical = relative if isinstance(relative, LogicalMediaPath) else LogicalMediaPath.parse(relative)
        candidate = (self.omv_root.joinpath(*logical.parts)).resolve(strict=False)
        self._assert_beneath_root(candidate)
        return candidate

    def to_relative(self, host_path: Path) -> LogicalMediaPath:
        if "\x00" in str(host_path):
            raise UnsafePath("paths must contain no NUL")
        candidate = Path(host_path).expanduser().resolve(strict=False)
        self._assert_beneath_root(candidate)
        return LogicalMediaPath.parse(candidate.relative_to(self.omv_root).as_posix())

    def _assert_beneath_root(self, candidate: Path) -> None:
        try:
            candidate.relative_to(self.omv_root)
        except ValueError as error:
            raise UnsafePath("path escapes the configured OMV root") from error
