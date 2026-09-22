"""No-replacement promotion of verified partial files."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.ingest.verify import hash_file


@dataclass(frozen=True, slots=True)
class PromotionResult:
    status: str
    error_code: str | None = None


def promote_no_replace(partial: Path, final: Path) -> PromotionResult:
    """Publish ``partial`` atomically without ever replacing ``final``."""

    if final.exists():
        return _resolve_existing(partial, final)

    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        # A hard-link create is atomic, same-volume, and fails if the target exists.
        # It is the portable no-replace primitive available on Windows and POSIX.
        os.link(partial, final)
    except FileExistsError:
        return _resolve_existing(partial, final)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise OSError("partial and final must be on the same volume") from exc
        raise
    partial.unlink()
    return PromotionResult("PROMOTED")


def _resolve_existing(partial: Path, final: Path) -> PromotionResult:
    if hash_file(partial) == hash_file(final):
        partial.unlink()
        return PromotionResult("IDENTICAL_EXISTING")
    return PromotionResult("DIVERGENT_CONFLICT", "existing_content_differs")
