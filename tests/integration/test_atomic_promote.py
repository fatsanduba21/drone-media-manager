from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.ingest.promote import promote_no_replace


def test_divergent_final_is_never_replaced(tmp_path: Path) -> None:
    partial = tmp_path / ".clip.partial"
    final = tmp_path / "clip.mp4"
    partial.write_bytes(b"new")
    final.write_bytes(b"existing")

    result = promote_no_replace(partial, final)

    assert result.status == "DIVERGENT_CONFLICT"
    assert final.read_bytes() == b"existing"
    assert partial.read_bytes() == b"new"


def test_identical_final_is_reused_and_partial_removed(tmp_path: Path) -> None:
    partial = tmp_path / ".clip.partial"
    final = tmp_path / "clip.mp4"
    partial.write_bytes(b"same")
    final.write_bytes(b"same")

    result = promote_no_replace(partial, final)

    assert result.status == "IDENTICAL_EXISTING"
    assert not partial.exists()
    assert final.read_bytes() == b"same"


def test_cross_volume_promotion_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = tmp_path / ".clip.partial"
    final = tmp_path / "clip.mp4"
    partial.write_bytes(b"new")

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr("drone_media_manager.ingest.promote.os.link", fail_link)
    with pytest.raises(OSError, match="same volume"):
        promote_no_replace(partial, final)
    assert partial.read_bytes() == b"new"
    assert not final.exists()
