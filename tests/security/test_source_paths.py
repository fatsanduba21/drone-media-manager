from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.sources.paths import (
    UnsafeSourcePath,
    canonicalize_source_root,
    validate_source_entry,
)


@pytest.fixture
def source_root(tmp_path: Path):
    return canonicalize_source_root(tmp_path)


@pytest.mark.parametrize(
    "relative", ["../secret.mp4", "/etc/passwd", r"C:\\other\\clip.mp4"]
)
def test_source_entry_rejects_escape(source_root, relative: str) -> None:
    with pytest.raises(UnsafeSourcePath):
        validate_source_entry(source_root, source_root.path / relative)


def test_source_entry_rejects_nul_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    link = root / "linked.mp4"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    escaped_candidate = link
    canonical_root = canonicalize_source_root(root)

    with pytest.raises(UnsafeSourcePath):
        validate_source_entry(canonical_root, root / "bad\x00.mp4")
    with pytest.raises(UnsafeSourcePath):
        validate_source_entry(canonical_root, escaped_candidate)
