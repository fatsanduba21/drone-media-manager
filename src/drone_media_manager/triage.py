"""Sort a local working folder by editorial format before cutting.

Uses the organizer's exact classification (ffprobe display aspect ratio) to
move top-level originals into ``YOUTUBE_16x9``, ``INSTAGRAM_9x16``, ``FOTOS``
and ``OUTROS_REVISAR`` subfolders, so one format can be edited before another.
Only the working copy is touched (never the SD card or the OMV), each video's
SRT moves with it, and an existing destination is never replaced.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drone_media_manager.organize import _CATEGORIES, classify_video, probe_video

_VIDEO = {".mp4"}
_PHOTO = {".jpg", ".jpeg"}

Prober = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class SortMove:
    source: Path
    target: Path | None
    category: str | None
    status: str
    detail: str | None = None
    sidecars: tuple[tuple[Path, Path], ...] = ()


def _category(path: Path, prober: Prober) -> str:
    if path.suffix.lower() in _PHOTO:
        return "FOTOS"
    video = prober(path)
    return classify_video(
        int(video["encoded_width"]),
        int(video["encoded_height"]),
        video.get("rotation_degrees"),
    )


def plan_sort(folder: Path, *, prober: Prober | None = None) -> list[SortMove]:
    """Plan moves for top-level media only; already sorted subfolders are left alone."""
    probe = prober or probe_video
    moves = []
    entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
    by_name = {p.name.casefold(): p for p in entries if p.is_file()}
    for path in entries:
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in _VIDEO | _PHOTO:
            continue
        try:
            category = _category(path, probe)
        except (ValueError, KeyError, TypeError) as error:
            moves.append(SortMove(path, None, None, "ERROR", str(error)))
            continue
        destination = folder / _CATEGORIES[category][0]
        target = destination / path.name
        srt = by_name.get(f"{path.stem}.srt".casefold()) if suffix in _VIDEO else None
        sidecars = ((srt, destination / srt.name),) if srt is not None else ()
        clash = [t for t in (target, *(t for _, t in sidecars)) if t.exists()]
        if clash:
            moves.append(
                SortMove(path, target, category, "CONFLICT", f"exists: {clash[0].name}")
            )
            continue
        moves.append(SortMove(path, target, category, "MOVE", sidecars=sidecars))
    return moves


def _move_no_replace(source: Path, target: Path) -> None:
    target.parent.mkdir(exist_ok=True)
    try:
        # Hard link + unlink never replaces an existing file on any platform.
        os.link(source, target)
    except FileExistsError:
        raise
    except OSError as error:
        if error.errno == errno.EXDEV or target.exists():
            raise
        # Filesystems without hard links (e.g. exFAT): rename after the check.
        os.rename(source, target)
        return
    source.unlink()


def apply_sort(moves: list[SortMove]) -> list[tuple[SortMove, str]]:
    results = []
    for move in moves:
        if move.status != "MOVE" or move.target is None:
            results.append((move, move.status))
            continue
        try:
            _move_no_replace(move.source, move.target)
            for sidecar, target in move.sidecars:
                _move_no_replace(sidecar, target)
        except FileExistsError:
            results.append((move, "CONFLICT"))
            continue
        except OSError as error:
            results.append((move, f"ERROR: {error}"))
            continue
        results.append((move, "MOVED"))
    return results
