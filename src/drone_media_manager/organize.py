"""Local Windows to OMV editorial organization, independent of the Mac database."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


def display_dimensions(
    width: int, height: int, rotation: float | None
) -> tuple[int, int]:
    """Return dimensions as displayed for orthogonal rotation metadata."""

    if width <= 0 or height <= 0:
        return 0, 0
    normalized = round(rotation or 0) % 360
    if normalized not in (0, 90, 180, 270) or (
        rotation is not None and abs((rotation % 360) - normalized) > 0.01
    ):
        return 0, 0
    return (height, width) if normalized in (90, 270) else (width, height)


def classify_video(width: int, height: int, rotation: float | None) -> str:
    """Classify exact display aspect ratios without cropping."""

    display_width, display_height = display_dimensions(width, height, rotation)
    if display_width and display_width * 9 == display_height * 16:
        return "YOUTUBE_16X9"
    if display_height and display_height * 9 == display_width * 16:
        return "INSTAGRAM_9X16"
    return "OUTROS_REVISAR"


def probe_video(
    path: Path, ffprobe: str = "ffprobe", timeout: int = 60
) -> dict[str, Any]:
    """Read ffprobe JSON and retain evidence for the display interpretation."""

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,avg_frame_rate,duration:stream_tags=rotate,creation_time:stream_side_data=rotation,displaymatrix:format=duration:format_tags=creation_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"ffprobe failed for {path}: {error}") from error
    try:
        result = json.loads(completed.stdout)
        stream = next(
            item
            for item in result.get("streams", [])
            if item.get("codec_type") == "video"
        )
        width = int(stream["width"])
        height = int(stream["height"])
        rotation: float | None = None
        display_matrix: str | None = None
        for side_data in stream.get("side_data_list", []):
            if "displaymatrix" in side_data:
                display_matrix = str(side_data["displaymatrix"])
            if "rotation" in side_data:
                rotation = float(side_data["rotation"])
        if rotation is None and "rotate" in stream.get("tags", {}):
            rotation = float(stream["tags"]["rotate"])
        if rotation is None and display_matrix:
            rows = [
                re.findall(r"-?\d+", line.split(":", 1)[1])
                for line in display_matrix.splitlines()
                if ":" in line
            ]
            if len(rows) >= 2 and rows[0] and rows[1]:
                x = int(rows[0][0])
                y = int(rows[1][0])
                if x or y:
                    rotation = math.degrees(math.atan2(y, x))
        fps_raw = str(stream.get("avg_frame_rate", "0/0"))
        fps_fraction = (
            Fraction(fps_raw) if fps_raw not in {"0/0", "N/A"} else Fraction(0)
        )
        duration_raw = stream.get("duration") or result.get("format", {}).get(
            "duration"
        )
        duration_ms = round(float(duration_raw) * 1000) if duration_raw else None
        display_width, display_height = display_dimensions(width, height, rotation)
        return {
            "codec": stream.get("codec_name"),
            "duration_ms": duration_ms,
            "fps": round(float(fps_fraction), 5) if fps_fraction else None,
            "encoded_width": width,
            "encoded_height": height,
            "rotation_degrees": rotation,
            "display_matrix": display_matrix,
            "display_width": display_width or None,
            "display_height": display_height or None,
            "creation_time": stream.get("tags", {}).get("creation_time")
            or result.get("format", {}).get("tags", {}).get("creation_time"),
        }
    except (KeyError, TypeError, ValueError, StopIteration) as error:
        raise ValueError(f"invalid ffprobe output for {path}: {error}") from error


import hashlib
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4

from drone_media_manager.domain.enums import PairStatus
from drone_media_manager.ingest.copy import CopyEngine, CopyItem
from drone_media_manager.ingest.inventory import build_inventory
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)
from drone_media_manager.sources.models import SourceEntry
from drone_media_manager.storage.roots import LogicalMediaPath, RootMapper

_CATEGORIES = {
    "YOUTUBE_16X9": ("YOUTUBE_16x9", "16x9"),
    "INSTAGRAM_9X16": ("INSTAGRAM_9x16", "9x16"),
    "OUTROS_REVISAR": ("OUTROS_REVISAR", "outros"),
    "FOTOS": ("FOTOS", "foto"),
}
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")[:60].strip("-")
    if not slug:
        raise ValueError("editorial field cannot be empty after sanitization")
    return f"x-{slug}" if slug in _RESERVED else slug


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_source(source: FilesystemReadOnlySource, entry: SourceEntry) -> str:
    if source.stat(entry) != entry.stat:
        raise ValueError(f"source changed before hashing: {entry.relative_path}")
    digest = hashlib.sha256()
    with source.open_read(entry) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if source.stat(entry) != entry.stat:
        raise ValueError(f"source changed during hashing: {entry.relative_path}")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PlannedFile:
    asset_id: str
    kind: str
    entry: SourceEntry
    relative_path: str
    sha256: str


@dataclass(slots=True)
class OrganizePlan:
    source: FilesystemReadOnlySource
    output_root: Path
    trip_name: str
    trip_slug: str
    assets: list[dict[str, Any]]
    files: list[PlannedFile]
    orphan_srt: list[str]
    unsupported: list[str]
    errors: list[str]
    naming_scheme: str | None

    def file_state(self, planned: PlannedFile) -> str:
        target = RootMapper(self.output_root).to_host_path(
            LogicalMediaPath.parse(planned.relative_path)
        )
        if not target.exists():
            return "CREATE"
        if not target.is_file():
            return "CONFLICT"
        return "ALREADY_OK" if _hash_path(target) == planned.sha256 else "CONFLICT"

    def preview(self) -> dict[str, Any]:
        file_actions = [
            {
                "asset_id": item.asset_id,
                "kind": item.kind,
                "source": str(item.entry.absolute_path),
                "destination": str(self.output_root / Path(item.relative_path)),
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "status": self.file_state(item),
            }
            for item in self.files
        ]
        return {
            "trip": {
                "name": self.trip_name,
                "slug": self.trip_slug,
                "external_id": None,
            },
            "source_root": str(self.source.descriptor.root.path),
            "output_omv": str(self.output_root),
            "assets": self.assets,
            "files": file_actions,
            "orphan_srt": self.orphan_srt,
            "unsupported": self.unsupported,
            "errors": self.errors,
            "manifest_preview": {
                "schema_version": 1,
                **({"naming_scheme": self.naming_scheme} if self.naming_scheme else {}),
                "trip": {
                    "name": self.trip_name,
                    "slug": self.trip_slug,
                    "external_id": None,
                },
                "assets": self.assets,
                "orphan_srt": self.orphan_srt,
                "unsupported": self.unsupported,
            },
        }


def _naming_scheme(manifest_path: Path) -> str | None:
    if not manifest_path.exists():
        return "neutral-v1"
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return existing.get("naming_scheme") if isinstance(existing, dict) else None


def build_plan(
    source_path: str | Path,
    output_omv: str | Path,
    trip_name: str,
    poi: str | None = None,
    *,
    movement: str | None = None,
    people: str | None = None,
    capture_date: str | None = None,
    ffprobe: str = "ffprobe",
) -> OrganizePlan:
    source_root = Path(source_path).expanduser().resolve(strict=True)
    if not source_root.is_dir():
        raise ValueError("source must be a directory")
    output_root = Path(output_omv).expanduser().resolve(strict=False)
    if (
        source_root == output_root
        or source_root.is_relative_to(output_root)
        or output_root.is_relative_to(source_root)
    ):
        raise ValueError("source and output roots must not overlap")
    trip_slug = _slug(trip_name)
    manifest_path = output_root / trip_slug / "MANIFESTO.json"
    naming_scheme = _naming_scheme(manifest_path)
    if naming_scheme not in (None, "neutral-v1"):
        raise ValueError("unsupported naming scheme")
    if naming_scheme is None and manifest_path.exists() and poi is None:
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            first = existing["assets"][0]
            first_video = next(
                (
                    asset
                    for asset in existing["assets"]
                    if asset.get("video") is not None
                ),
                first,
            )
            poi = first["location"]["poi_final"]
            movement = movement or first_video["editorial"].get("movement")
            people = people or first_video["editorial"].get("people")
        except (OSError, KeyError, IndexError, TypeError, ValueError):
            pass
    poi_slug = _slug(poi) if poi else "a-classificar"
    movement_slug = (
        _slug(movement or "desconhecido")
        if naming_scheme is None
        else (_slug(movement) if movement else None)
    )
    people_slug = (
        _slug(people or "desconhecido")
        if naming_scheme is None
        else (_slug(people) if people else None)
    )
    if capture_date is not None:
        date.fromisoformat(capture_date)
    source = FilesystemReadOnlySource(source_from_explicit_path(source_root))
    inventory = build_inventory(source)
    all_entries = sorted(
        source.iter_files(), key=lambda item: item.relative_path.as_posix().casefold()
    )
    errors: list[str] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for entry in inventory.entries:
        key = (
            entry.relative_path.parent.as_posix().casefold(),
            entry.relative_path.stem.casefold(),
            entry.relative_path.suffix.casefold(),
        )
        if key in seen_pairs:
            errors.append(
                f"duplicate case-insensitive media name: {entry.relative_path}"
            )
        seen_pairs.add(key)
    orphan_srt = [
        str(item.srt_entry.relative_path.as_posix())
        for item in inventory.items
        if item.pair_status is PairStatus.ORPHAN_SRT and item.srt_entry is not None
    ]
    unsupported = [
        entry.relative_path.as_posix()
        for entry in all_entries
        if entry.relative_path.suffix.casefold()
        not in {".mp4", ".srt", ".jpg", ".jpeg"}
    ]
    if not output_root.is_dir():
        errors.append(f"destination offline: {output_root}")
    assets: list[dict[str, Any]] = []
    files: list[PlannedFile] = []
    seen_ids: set[str] = set()
    candidates: list[tuple[SourceEntry, SourceEntry | None]] = [
        (item.video_entry, item.srt_entry)
        for item in inventory.items
        if item.video_entry is not None
    ]
    candidates.extend(
        (entry, None)
        for entry in all_entries
        if entry.relative_path.suffix.casefold() in {".jpg", ".jpeg"}
    )
    for primary, srt in candidates:
        try:
            primary_hash = _hash_source(source, primary)
            identity = f"{source.descriptor.volume_identity}\0{primary.stat.file_identity}\0{primary_hash}"
            asset_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            if asset_id in seen_ids:
                errors.append(f"duplicate asset identity: {primary.relative_path}")
                continue
            seen_ids.add(asset_id)
            is_photo = primary.relative_path.suffix.casefold() in {".jpg", ".jpeg"}
            if is_photo:
                metadata = None
                classification = "FOTOS"
            else:
                metadata = probe_video(primary.absolute_path, ffprobe)
                classification = classify_video(
                    int(metadata["encoded_width"]),
                    int(metadata["encoded_height"]),
                    metadata["rotation_degrees"],
                )
            date_label = capture_date or "desconhecido"
            date_source = "user" if capture_date else "unknown"
            if not capture_date and metadata and metadata.get("creation_time"):
                try:
                    date_label = (
                        datetime.fromisoformat(str(metadata["creation_time"]))
                        .date()
                        .isoformat()
                    )
                    date_source = "mp4_creation_time"
                except ValueError:
                    pass
            if date_source == "unknown":
                filename_date = re.match(
                    r"^DJI_(\d{14})_", primary.relative_path.stem, re.IGNORECASE
                )
                if filename_date:
                    try:
                        date_label = date.fromisoformat(
                            filename_date.group(1)[:8]
                        ).isoformat()
                        date_source = "dji_filename"
                    except ValueError:
                        pass
            folder, format_label = _CATEGORIES[classification]
            if naming_scheme == "neutral-v1":
                stem = _slug(primary.relative_path.stem)[:48].rstrip("-")
                physical_date = (
                    "sem-data" if date_label == "desconhecido" else date_label
                )
                basename = f"{physical_date}_{stem}_{format_label}_{asset_id[:8]}"
                if is_photo:
                    basename = f"{physical_date}_{stem}_foto_{asset_id[:8]}"
            elif is_photo:
                basename = f"{date_label}_{poi_slug}_foto_{asset_id[:8]}"
            else:
                basename = (
                    f"{date_label}_{poi_slug}_{movement_slug}_pessoas-{people_slug}"
                    f"_{format_label}_{asset_id[:8]}"
                )
            if is_photo:
                extension = primary.relative_path.suffix.lower()
            else:
                extension = ".mp4"
            relative = f"{trip_slug}/{poi_slug}/{folder}/{basename}{extension}"
            srt_relative = (
                f"{trip_slug}/{poi_slug}/{folder}/{basename}.srt" if srt else None
            )
            source_data = {
                "video_name": None if is_photo else primary.relative_path.name,
                "video_path": None if is_photo else str(primary.absolute_path),
                "photo_name": primary.relative_path.name if is_photo else None,
                "photo_path": str(primary.absolute_path) if is_photo else None,
                "srt_status": "paired"
                if srt
                else ("not_applicable" if is_photo else "missing"),
                "srt_name": srt.relative_path.name if srt else None,
                "srt_path": str(srt.absolute_path) if srt else None,
                "source_sha256": primary_hash,
            }
            srt_hash = _hash_source(source, srt) if srt else None
            record = {
                "asset_id": asset_id,
                "trip": {"name": trip_name, "slug": trip_slug, "external_id": None},
                "source": source_data,
                "video": metadata,
                "classification": classification,
                "location": {
                    "gps_source": None,
                    "poi_suggested": None,
                    "poi_final": poi,
                },
                "editorial": {
                    "movement": movement_slug if not is_photo else None,
                    "people": people_slug if not is_photo else None,
                    "capture_date": date_label,
                    "capture_date_source": date_source,
                },
                "output": {
                    "video_relative_path": None if is_photo else relative,
                    "srt_relative_path": srt_relative,
                    "photo_relative_path": relative if is_photo else None,
                    "sha256": primary_hash,
                    "srt_sha256": srt_hash,
                    "verification_status": "PLANNED",
                },
            }
            assets.append(record)
            files.append(
                PlannedFile(
                    asset_id,
                    "photo" if is_photo else "video",
                    primary,
                    relative,
                    primary_hash,
                )
            )
            if srt and srt_relative and srt_hash:
                files.append(PlannedFile(asset_id, "srt", srt, srt_relative, srt_hash))
        except (OSError, ValueError) as error:
            errors.append(f"{primary.relative_path}: {error}")
    destinations = [item.relative_path.casefold() for item in files]
    if len(destinations) != len(set(destinations)):
        errors.append("editorial destination collision")
    return OrganizePlan(
        source,
        output_root,
        trip_name,
        trip_slug,
        assets,
        files,
        orphan_srt,
        unsupported,
        errors,
        naming_scheme,
    )


def _compatible_manifest(
    plan: OrganizePlan, path: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], []
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [], [f"invalid existing manifesto: {error}"]
    if not isinstance(existing, dict) or not isinstance(existing.get("trip"), dict):
        return [], ["invalid existing manifesto structure"]
    if (
        existing.get("schema_version") != 1
        or existing.get("naming_scheme") != plan.naming_scheme
        or existing["trip"].get("slug") != plan.trip_slug
        or existing["trip"].get("name") != plan.trip_name
    ):
        return [], ["existing manifesto belongs to a different schema or trip"]
    old_assets = existing.get("assets")
    if not isinstance(old_assets, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("asset_id"), str)
        or not isinstance(item.get("source"), dict)
        or not isinstance(item.get("output"), dict)
        for item in old_assets
    ):
        return [], ["existing manifesto has invalid assets"]
    if len({item["asset_id"] for item in old_assets}) != len(old_assets):
        return [], ["existing manifesto has duplicate assets"]
    by_id = {
        item.get("asset_id"): item for item in old_assets if isinstance(item, dict)
    }
    conflicts: list[str] = []
    for item in plan.assets:
        old = by_id.get(item["asset_id"])
        if old is None:
            continue
        if (
            old.get("output", {}).get("video_relative_path")
            != item["output"]["video_relative_path"]
            or old.get("output", {}).get("srt_relative_path")
            != item["output"]["srt_relative_path"]
            or old.get("output", {}).get("photo_relative_path")
            != item["output"]["photo_relative_path"]
            or old.get("source", {}).get("source_sha256")
            != item["source"]["source_sha256"]
        ):
            conflicts.append(
                f"asset already published with different path/content: {item['asset_id']}"
            )
    return old_assets, conflicts


def apply_plan(plan: OrganizePlan) -> dict[str, Any]:
    if plan.errors:
        return {
            "status": "ERROR",
            "errors": plan.errors,
            "counts": {"CREATED": 0, "ALREADY_OK": 0},
        }
    manifest_path = plan.output_root / plan.trip_slug / "MANIFESTO.json"
    old_assets, conflicts = _compatible_manifest(plan, manifest_path)
    states: list[tuple[PlannedFile, str]] = []
    for item in plan.files:
        try:
            state = plan.file_state(item)
            states.append((item, state))
            if state == "CONFLICT":
                conflicts.append(f"divergent destination: {item.relative_path}")
            if plan.source.stat(item.entry) != item.entry.stat:
                conflicts.append(f"source changed: {item.entry.relative_path}")
        except (OSError, ValueError) as error:
            conflicts.append(f"{item.relative_path}: {error}")
    if conflicts:
        return {
            "status": "CONFLICT",
            "errors": conflicts,
            "counts": {"CREATED": 0, "ALREADY_OK": 0},
        }
    counts = {"CREATED": 0, "ALREADY_OK": 0}
    engine = CopyEngine(plan.source)
    mapper = RootMapper(plan.output_root)
    try:
        for item, state in states:
            if state == "ALREADY_OK":
                counts["ALREADY_OK"] += 1
                continue
            final_path = mapper.to_host_path(LogicalMediaPath.parse(item.relative_path))
            final_path.parent.mkdir(parents=True, exist_ok=True)
            partial = (
                final_path.parent / f".{final_path.name}.{item.asset_id[:8]}.partial"
            )
            outcome = engine.copy_or_resume(
                CopyItem(item.asset_id, item.entry, partial)
            )
            if outcome.status != "COPIED" or outcome.source_sha256 != item.sha256:
                raise ValueError(
                    f"copy interrupted or source changed: {item.relative_path}"
                )
            if _hash_path(partial) != item.sha256:
                raise ValueError(f"partial verification failed: {item.relative_path}")
            if final_path.exists():
                if _hash_path(final_path) != item.sha256:
                    raise ValueError(
                        f"destination appeared with different content: {item.relative_path}"
                    )
                partial.unlink()
                counts["ALREADY_OK"] += 1
                continue
            os.rename(partial, final_path)
            if _hash_path(final_path) != item.sha256:
                raise ValueError(f"final verification failed: {item.relative_path}")
            counts["CREATED"] += 1
        merged = {item["asset_id"]: item for item in old_assets}
        for asset_record in plan.assets:
            asset_record["output"]["verification_status"] = "VERIFIED"
            merged[asset_record["asset_id"]] = asset_record
        if (
            plan.naming_scheme is None
            and old_assets
            and counts["CREATED"] == 0
            and {item["asset_id"] for item in old_assets}
            == {item["asset_id"] for item in plan.assets}
        ):
            return {
                "status": "APPLIED",
                "errors": [],
                "counts": counts,
                "manifest": str(manifest_path),
            }
        manifest = {
            "schema_version": 1,
            **({"naming_scheme": plan.naming_scheme} if plan.naming_scheme else {}),
            "trip": {
                "name": plan.trip_name,
                "slug": plan.trip_slug,
                "external_id": None,
            },
            "assets": sorted(merged.values(), key=lambda item: item["asset_id"]),
            "orphan_srt": plan.orphan_srt,
            "unsupported": plan.unsupported,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest_path.parent / f".MANIFESTO.{uuid4().hex}.partial"
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(
                    manifest, stream, ensure_ascii=False, indent=2, sort_keys=True
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, manifest_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    except (OSError, ValueError) as error:
        return {"status": "ERROR", "errors": [str(error)], "counts": counts}
    return {
        "status": "APPLIED",
        "errors": [],
        "counts": counts,
        "manifest": str(manifest_path),
    }
