"""Validate and import Phase 1 manifests without consulting Windows source paths."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.db.models.catalog import (
    AssetFile,
    CatalogAsset,
    ManifestImport,
)
from drone_media_manager.db.models.ingest import Trip

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
_VIDEO = {"YOUTUBE_16X9", "INSTAGRAM_9X16", "OUTROS_REVISAR"}


class ManifestError(ValueError):
    """Invalid or unsupported manifest; no catalog changes are made."""


@dataclass(frozen=True)
class ParsedManifest:
    trip_name: str
    trip_slug: str
    assets: tuple[dict[str, Any], ...]
    rel_path: str
    sha256: str


@dataclass
class ImportReport:
    status: str
    trip: str
    schema_version: int = 1
    assets_found: int = 0
    created_assets: int = 0
    already_imported: int = 0
    created_files: int = 0
    conflicts: int = 0
    possible_duplicates: int = 0
    available_files: int = 0
    missing_files: int = 0
    unavailable_files: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _FilePlan:
    role: str
    rel_path: str
    sha256: str
    status: str
    size_bytes: int | None


def resolve_omv_path(root: Path, rel_path: str) -> Path:
    """Reject absolute, Windows, traversal and symlink escapes from the OMV root."""
    if (
        not isinstance(rel_path, str)
        or not rel_path
        or "\\" in rel_path
        or ":" in rel_path
    ):
        raise ManifestError(f"unsafe path: {rel_path!r}")
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or any(
        part in {".", "..", ""} for part in rel_path.split("/")
    ):
        raise ManifestError(f"unsafe path: {rel_path!r}")
    resolved_root = root.expanduser().resolve(strict=False)
    result = (resolved_root / Path(*pure.parts)).resolve(strict=False)
    if not result.is_relative_to(resolved_root):
        raise ManifestError(f"unsafe path: {rel_path!r}")
    return result


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} is required")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ManifestError(f"{label} must be a lowercase SHA-256")
    return value


def _relative(root: Path, value: Any, slug: str, label: str, suffixes: set[str]) -> str:
    rel = _nonempty(value, label)
    path = resolve_omv_path(root, rel)
    if PurePosixPath(rel).parts[0] != slug or path.suffix.lower() not in suffixes:
        raise ManifestError(f"{label} must be under {slug} with a supported extension")
    if len(rel) > 1024:
        raise ManifestError(f"{label} is too long")
    return rel


def load_manifest(root: Path, manifest_path: Path) -> ParsedManifest:
    """Parse and validate the entire schema-1 handoff before touching SQLite."""
    resolved_root = root.expanduser().resolve(strict=False)
    path = manifest_path.expanduser().resolve(strict=False)
    if not path.is_relative_to(resolved_root) or path.name != "MANIFESTO.json":
        raise ManifestError("unsafe path: manifest must be an OMV MANIFESTO.json")
    raw = path.read_bytes()
    try:
        document = _object(json.loads(raw), "manifest")
    except (ValueError, UnicodeError) as error:
        raise ManifestError(f"invalid manifest JSON: {error}") from error
    if document.get("schema_version") != 1 or isinstance(
        document.get("schema_version"), bool
    ):
        raise ManifestError("UNSUPPORTED_SCHEMA: only schema_version=1 is supported")
    trip = _object(document.get("trip"), "trip")
    name = _nonempty(trip.get("name"), "trip.name")
    slug = _nonempty(trip.get("slug"), "trip.slug")
    if len(slug) > 60 or _SLUG.fullmatch(slug) is None:
        raise ManifestError("invalid trip.slug")
    if path.parent.name != slug:
        raise ManifestError("manifest path does not match trip.slug")
    assets = document.get("assets")
    if not isinstance(assets, list):
        raise ManifestError("assets must be an array")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, raw_asset in enumerate(assets):
        asset = _object(raw_asset, f"assets[{index}]")
        asset_id = _sha(asset.get("asset_id"), f"assets[{index}].asset_id")
        if asset_id in seen_ids:
            raise ManifestError(f"duplicate asset_id: {asset_id}")
        seen_ids.add(asset_id)
        embedded_trip = _object(asset.get("trip"), f"assets[{index}].trip")
        if embedded_trip.get("slug") != slug or embedded_trip.get("name") != name:
            raise ManifestError(f"assets[{index}].trip conflicts with manifest trip")
        classification = asset.get("classification")
        if classification not in _VIDEO | {"FOTOS"}:
            raise ManifestError(f"assets[{index}].classification is invalid")
        output = _object(asset.get("output"), f"assets[{index}].output")
        source = _object(asset.get("source"), f"assets[{index}].source")
        _object(asset.get("location"), f"assets[{index}].location")
        _object(asset.get("editorial"), f"assets[{index}].editorial")
        if output.get("verification_status") not in {"VERIFIED", "PLANNED"}:
            raise ManifestError(f"assets[{index}].verification_status is invalid")
        _sha(output.get("sha256"), f"assets[{index}].output.sha256")
        is_video = classification in _VIDEO
        if is_video:
            _object(asset.get("video"), f"assets[{index}].video")
            if output.get("photo_relative_path") is not None:
                raise ManifestError("VIDEO cannot have photo_relative_path")
            main = _relative(
                root,
                output.get("video_relative_path"),
                slug,
                "video_relative_path",
                {".mp4"},
            )
        else:
            if (
                asset.get("video") is not None
                or output.get("video_relative_path") is not None
            ):
                raise ManifestError("PHOTO cannot have video metadata or path")
            main = _relative(
                root,
                output.get("photo_relative_path"),
                slug,
                "photo_relative_path",
                {".jpg", ".jpeg"},
            )
        paths = [main]
        srt_path = output.get("srt_relative_path")
        srt_sha = output.get("srt_sha256")
        if srt_path is not None or srt_sha is not None:
            if not is_video or source.get("srt_status") != "paired":
                raise ManifestError("SRT requires paired VIDEO")
            paths.append(_relative(root, srt_path, slug, "srt_relative_path", {".srt"}))
            _sha(srt_sha, "srt_sha256")
        elif is_video and source.get("srt_status") not in {"missing", None}:
            raise ManifestError("paired VIDEO requires SRT path and hash")
        for rel in paths:
            if rel in seen_paths:
                raise ManifestError(f"duplicate output path: {rel}")
            seen_paths.add(rel)
    rel_manifest = path.relative_to(resolved_root).as_posix()
    return ParsedManifest(
        name, slug, tuple(assets), rel_manifest, hashlib.sha256(raw).hexdigest()
    )


def _file_state(
    root: Path, rel: str, sha: str, verified: bool, verify_hash: bool
) -> tuple[str, int | None]:
    path = resolve_omv_path(root, rel)
    if not path.is_file():
        return "MISSING", None
    size = path.stat().st_size
    if not verified:
        return "UNVERIFIED", size
    if verify_hash:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != sha:
            return "HASH_MISMATCH", size
    return "AVAILABLE", size


def _plans(root: Path, asset: dict[str, Any], verify_hash: bool) -> list[_FilePlan]:
    output = asset["output"]
    verified = output["verification_status"] == "VERIFIED"
    main = output["video_relative_path"] or output["photo_relative_path"]
    specs = [("ORIGINAL", main, output["sha256"])]
    if output["srt_relative_path"] is not None:
        specs.append(("SRT", output["srt_relative_path"], output["srt_sha256"]))
    result = []
    for role, rel, sha in specs:
        status, size = _file_state(root, rel, sha, verified, verify_hash)
        result.append(_FilePlan(role, rel, sha, status, size))
    return result


def _preview(
    session: Session, root: Path, manifest: ParsedManifest, verify_hash: bool
) -> tuple[
    ImportReport,
    list[
        tuple[
            dict[str, Any], CatalogAsset | None, list[_FilePlan], dict[str, AssetFile]
        ]
    ],
    Trip | None,
]:
    report = ImportReport(
        "READY", manifest.trip_slug, assets_found=len(manifest.assets)
    )
    trip = session.scalar(select(Trip).where(Trip.slug == manifest.trip_slug))
    if trip is not None and trip.name != manifest.trip_name:
        report.conflicts += 1
        report.errors.append("Trip slug already belongs to a different name")
    planned = []
    seen_hashes: set[str] = set()
    for asset in manifest.assets:
        asset_id = asset["asset_id"]
        existing = session.scalar(
            select(CatalogAsset).where(CatalogAsset.asset_id == asset_id)
        )
        specs = _plans(root, asset, verify_hash)
        old_files = (
            {
                row.role: row
                for row in session.scalars(
                    select(AssetFile).where(AssetFile.catalog_asset_id == existing.id)
                )
            }
            if existing
            else {}
        )
        if not verify_hash:
            specs = [
                _FilePlan(
                    spec.role,
                    spec.rel_path,
                    spec.sha256,
                    "HASH_MISMATCH"
                    if spec.status == "AVAILABLE"
                    and spec.role in old_files
                    and old_files[spec.role].availability_status == "HASH_MISMATCH"
                    else spec.status,
                    spec.size_bytes,
                )
                for spec in specs
            ]
        if existing:
            report.already_imported += 1
            if (
                trip is None
                or existing.trip_id != trip.id
                or existing.classification != asset["classification"]
                or set(old_files) != {spec.role for spec in specs}
                or any(
                    old_files[spec.role].sha256 != spec.sha256
                    or old_files[spec.role].rel_path != spec.rel_path
                    for spec in specs
                    if spec.role in old_files
                )
            ):
                report.conflicts += 1
                report.errors.append(f"asset_id conflict: {asset_id}")
        else:
            report.created_assets += 1
            report.created_files += len(specs)
        main_sha = specs[0].sha256
        if main_sha in seen_hashes or (
            trip is not None
            and session.scalar(
                select(CatalogAsset.id)
                .join(AssetFile, AssetFile.catalog_asset_id == CatalogAsset.id)
                .where(
                    CatalogAsset.trip_id == trip.id,
                    CatalogAsset.asset_id != asset_id,
                    AssetFile.role == "ORIGINAL",
                    AssetFile.sha256 == main_sha,
                )
            )
            is not None
        ):
            report.possible_duplicates += 1
            report.errors.append(f"possible duplicate content: {asset_id}")
        seen_hashes.add(main_sha)
        for spec in specs:
            if spec.status == "AVAILABLE":
                report.available_files += 1
            else:
                report.unavailable_files += 1
                if spec.status == "MISSING":
                    report.missing_files += 1
                report.errors.append(f"{spec.status}: {spec.rel_path}")
        planned.append((asset, existing, specs, old_files))
    if report.conflicts:
        report.status = "CONFLICT"
    elif report.unavailable_files:
        report.status = "PARTIAL_AVAILABILITY"
    return report, planned, trip


def preview_manifest(
    session: Session, root: Path, manifest_path: Path, *, verify_hash: bool = False
) -> ImportReport:
    manifest = load_manifest(root, manifest_path)
    report, _, _ = _preview(session, root, manifest, verify_hash)
    return report


def import_manifest(
    session: Session, root: Path, manifest_path: Path, *, verify_hash: bool = False
) -> ImportReport:
    manifest = load_manifest(root, manifest_path)
    report, planned, trip = _preview(session, root, manifest, verify_hash)
    if report.conflicts:
        report.created_assets = 0
        report.created_files = 0
        return report
    try:
        if trip is None:
            trip = Trip(
                name=manifest.trip_name,
                slug=manifest.trip_slug,
                nas_rel_path=manifest.trip_slug,
            )
            session.add(trip)
            session.flush()
        for asset, existing, specs, old_files in planned:
            if existing is None:
                video = asset["video"] or {}
                location = asset["location"]
                editorial = asset["editorial"]
                existing = CatalogAsset(
                    asset_id=asset["asset_id"],
                    trip_id=trip.id,
                    media_type="VIDEO"
                    if asset["classification"] in _VIDEO
                    else "PHOTO",
                    classification=asset["classification"],
                    codec=video.get("codec"),
                    duration_ms=video.get("duration_ms"),
                    fps=video.get("fps"),
                    encoded_width=video.get("encoded_width"),
                    encoded_height=video.get("encoded_height"),
                    display_width=video.get("display_width"),
                    display_height=video.get("display_height"),
                    rotation_degrees=video.get("rotation_degrees"),
                    capture_date=editorial.get("capture_date"),
                    capture_date_source=editorial.get("capture_date_source"),
                    poi_final=location.get("poi_final"),
                    poi_suggested=location.get("poi_suggested"),
                    movement=editorial.get("movement"),
                    people=editorial.get("people"),
                    verification_status=asset["output"]["verification_status"],
                )
                session.add(existing)
                session.flush()
            existing.verification_status = asset["output"]["verification_status"]
            for spec in specs:
                old = old_files.get(spec.role)
                if old is None:
                    session.add(
                        AssetFile(
                            catalog_asset_id=existing.id,
                            role=spec.role,
                            rel_path=spec.rel_path,
                            sha256=spec.sha256,
                            size_bytes=spec.size_bytes,
                            availability_status=spec.status,
                        )
                    )
                else:
                    old.size_bytes = spec.size_bytes
                    old.availability_status = spec.status
        status = "PARTIAL_AVAILABILITY" if report.unavailable_files else "IMPORTED"
        session.add(
            ManifestImport(
                trip_id=trip.id,
                manifest_rel_path=manifest.rel_path,
                manifest_sha256=manifest.sha256,
                schema_version=1,
                status=status,
                asset_count=len(manifest.assets),
                error_count=report.unavailable_files,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    report.status = status
    return report
