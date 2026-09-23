"""Generate verified local media derivatives from catalog originals."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.catalog.importer import resolve_omv_path
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.time import utc_now

PROFILES = {"THUMBNAIL": "grid-v1", "PROXY": "web-720p-v1"}


class Renderer(Protocol):
    def render(self, source: Path, target: Path, kind: str) -> None: ...

    def valid(self, path: Path, kind: str) -> bool: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise TypeError("ffprobe returned an invalid document")
    return data


class FFmpegRenderer:
    """FFmpeg for video, Pillow for EXIF-safe photo thumbnails."""

    def render(self, source: Path, target: Path, kind: str) -> None:
        if kind == "THUMBNAIL" and source.suffix.lower() in {".jpg", ".jpeg"}:
            with Image.open(source) as image:
                oriented = ImageOps.exif_transpose(image)
                oriented.thumbnail((480, 480), Image.Resampling.LANCZOS)
                oriented.convert("RGB").save(target, format="JPEG", quality=85)
            return
        if kind == "THUMBNAIL":
            args = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                "scale=480:480:force_original_aspect_ratio=decrease",
                "-c:v",
                "mjpeg",
                "-q:v",
                "3",
                "-f",
                "image2",
                "-update",
                "1",
                str(target),
            ]
        else:
            args = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                "scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(target),
            ]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(
                result.stderr[-1000:] or f"ffmpeg exit {result.returncode}"
            )

    def valid(self, path: Path, kind: str) -> bool:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            if kind == "THUMBNAIL":
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    return image.format == "JPEG" and max(image.size) <= 480
            streams = _probe(path).get("streams", [])
            if not isinstance(streams, list):
                return False
            video = [item for item in streams if item.get("codec_type") == "video"]
            audio = [item for item in streams if item.get("codec_type") == "audio"]
            return (
                len(video) == 1
                and video[0].get("codec_name") == "h264"
                and video[0].get("pix_fmt") == "yuv420p"
                and max(int(video[0]["width"]), int(video[0]["height"])) <= 720
                and all(item.get("codec_name") == "aac" for item in audio)
            )
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
            return False


@dataclass
class GenerationReport:
    generated: int = 0
    reused: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _record(
    session: Session,
    asset: CatalogAsset,
    kind: str,
    source_sha: str,
) -> Derivative:
    row = session.scalar(
        select(Derivative).where(
            Derivative.catalog_asset_id == asset.id, Derivative.kind == kind
        )
    )
    if row is None:
        row = Derivative(
            catalog_asset_id=asset.id,
            kind=kind,
            status="ERROR",
            profile_version=PROFILES[kind],
            source_sha256=source_sha,
        )
        session.add(row)
    return row


def generate_derivatives(
    session: Session,
    settings: ServerSettings,
    *,
    trip_slug: str | None = None,
    renderer: Renderer | None = None,
) -> GenerationReport:
    """Process the imported catalog, committing each kind independently."""
    cache = settings.derivatives_root
    assert cache is not None
    backend = renderer or FFmpegRenderer()
    report = GenerationReport()
    query = (
        select(CatalogAsset, AssetFile)
        .join(AssetFile, AssetFile.catalog_asset_id == CatalogAsset.id)
        .join(Trip, Trip.id == CatalogAsset.trip_id)
        .where(AssetFile.role == "ORIGINAL")
        .order_by(CatalogAsset.asset_id)
    )
    if trip_slug:
        query = query.where(Trip.slug == trip_slug)
    for asset, original in session.execute(query).all():
        kinds = (
            ("THUMBNAIL", "PROXY") if asset.media_type == "VIDEO" else ("THUMBNAIL",)
        )
        for kind in kinds:
            source_sha = ""
            try:
                if original.availability_status != "AVAILABLE":
                    raise ValueError(f"original status {original.availability_status}")
                source = resolve_omv_path(settings.omv_root, original.rel_path)
                if not source.is_file():
                    raise FileNotFoundError(str(source))
                source_sha = _sha256(source)
                row = _record(session, asset, kind, source_sha)
                profile = PROFILES[kind]
                suffix = ".mp4" if kind == "PROXY" else ".jpg"
                rel_path = f"{asset.asset_id[:2]}/{asset.asset_id}/{profile}{suffix}"
                target = resolve_omv_path(cache, rel_path)
                if (
                    row.status == "READY"
                    and row.source_sha256 == source_sha
                    and row.profile_version == profile
                    and row.rel_path == rel_path
                    and row.output_sha256 is not None
                    and target.is_file()
                    and _sha256(target) == row.output_sha256
                    and backend.valid(target, kind)
                ):
                    report.reused += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=".dmm-", suffix=".tmp", dir=target.parent
                )
                os.close(descriptor)
                temp = Path(temp_name)
                try:
                    backend.render(source, temp, kind)
                    if not backend.valid(temp, kind):
                        raise ValueError("rendered derivative failed validation")
                    output_sha = _sha256(temp)
                    size = temp.stat().st_size
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
                row.status = "READY"
                row.source_sha256 = source_sha
                row.profile_version = profile
                row.rel_path = rel_path
                row.output_sha256 = output_sha
                row.size_bytes = size
                row.error = None
                row.updated_at = utc_now()
                session.commit()
                report.generated += 1
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as error:
                session.rollback()
                row = _record(session, asset, kind, source_sha)
                row.status = "ERROR"
                row.source_sha256 = source_sha
                row.profile_version = PROFILES[kind]
                row.error = str(error)[:1024]
                row.updated_at = utc_now()
                session.commit()
                report.failed += 1
                report.errors.append(f"{asset.asset_id} {kind}: {error}")
    return report
