from __future__ import annotations

from drone_media_manager.sources.read_only import ReadOnlySource


def test_read_only_protocol_has_no_mutating_methods() -> None:
    methods = {
        name
        for name, value in ReadOnlySource.__dict__.items()
        if callable(value) and not name.startswith("_")
    }

    assert methods == {"iter_files", "open_read", "stat"}
