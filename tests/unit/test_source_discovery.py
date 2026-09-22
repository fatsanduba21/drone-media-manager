from __future__ import annotations

from pathlib import Path

from drone_media_manager.domain.enums import SourceKind
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    discover_removable_sources,
    source_from_explicit_path,
)


def test_explicit_local_source_has_a_canonical_read_only_descriptor(
    tmp_path: Path,
) -> None:
    descriptor = source_from_explicit_path(tmp_path)

    assert descriptor.kind is SourceKind.LOCAL
    assert descriptor.is_removable is False
    assert descriptor.root.path == tmp_path.resolve()


def test_discovered_removable_roots_are_labeled_as_removable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "drone_media_manager.sources.discovery._iter_removable_roots",
        lambda: iter([tmp_path]),
    )

    descriptors = discover_removable_sources()

    assert [(item.kind, item.is_removable) for item in descriptors] == [
        (SourceKind.REMOVABLE, True)
    ]


def test_filesystem_source_only_enumerates_valid_files_below_the_root(
    tmp_path: Path,
) -> None:
    media = tmp_path / "DCIM" / "clip.MP4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    descriptor = source_from_explicit_path(tmp_path)
    source = FilesystemReadOnlySource(descriptor)

    entries = list(source.iter_files())

    assert [entry.relative_path.as_posix() for entry in entries] == ["DCIM/clip.MP4"]
    with source.open_read(entries[0]) as stream:
        assert stream.read() == b"video"
