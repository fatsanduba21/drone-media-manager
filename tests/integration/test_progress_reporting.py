"""Long commands report coherent progress; bars always reach their totals."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr

from drone_media_manager.catalog.importer import import_manifest, preview_manifest
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.derivatives.service import generate_derivatives
from drone_media_manager.organize import apply_plan, build_plan
from drone_media_manager.progress import TerminalProgress
from drone_media_manager.triage import apply_sort, plan_sort


class RecordingProgress:
    def __init__(self) -> None:
        self.stages: list[dict[str, object]] = []

    def stage(self, label: str, total: int | None, *, unit: str = "item") -> None:
        self.stages.append({"label": label, "total": total, "unit": unit, "done": 0})

    def advance(self, amount: int = 1) -> None:
        current = self.stages[-1]
        current["done"] = int(str(current["done"])) + amount

    def note(self, text: str) -> None:
        self.stages[-1]["note"] = text

    def close(self) -> None:
        return

    def bars(self) -> list[tuple[object, object, object]]:
        return [
            (s["label"], s["total"], s["done"])
            for s in self.stages
            if s["total"] is not None
        ]


def _probe(path: Path, ffprobe: str = "ffprobe") -> dict[str, object]:
    return {
        "codec": "h264",
        "duration_ms": 1000,
        "fps": 30.0,
        "encoded_width": 3840,
        "encoded_height": 2160,
        "rotation_degrees": 0,
        "display_matrix": None,
        "display_width": 3840,
        "display_height": 2160,
    }


class FakeRenderer:
    def render(self, source: Path, target: Path, kind: str) -> None:
        target.write_bytes(f"{kind}:{source.name}".encode())

    def valid(self, path: Path, kind: str) -> bool:
        return path.is_file() and path.stat().st_size > 0


def test_organize_catalog_and_derivatives_bars_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("drone_media_manager.organize.probe_video", _probe)
    source = tmp_path / "source"
    source.mkdir()
    (source / "DJI_001.MP4").write_bytes(b"v" * 5000)
    (source / "DJI_001.SRT").write_bytes(b"s" * 300)
    (source / "photo.JPG").write_bytes(b"p" * 700)
    omv = tmp_path / "omv"
    omv.mkdir()

    progress = RecordingProgress()
    plan = build_plan(source, omv, "Caconde", progress=progress)
    plan.preview(progress)
    result = apply_plan(plan, progress)
    assert result["status"] == "APPLIED"

    labels = [s["label"] for s in progress.stages]
    assert labels[0] == "Lendo a origem" and labels[-1] == "Gravando MANIFESTO.json"
    assert progress.bars() == [
        ("Conferindo vídeos", 1, 1),
        ("Origem: hash", 6000, 6000),
        ("Conferindo o destino", 3, 3),
        ("Conferindo o destino", 3, 3),
        ("Copiando e verificando", 18000, 18000),
    ]

    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=omv,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    sessions = session_factory(create_engine_from_settings(settings))
    manifest = omv / "caconde" / "MANIFESTO.json"
    catalog = RecordingProgress()
    with sessions() as session:
        preview_manifest(session, omv, manifest, verify_hash=True, progress=catalog)
        report = import_manifest(session, omv, manifest, progress=catalog)
    assert report.status == "IMPORTED"
    assert catalog.bars() == [
        ("Conferindo hashes no OMV", 6000, 6000),
        ("Conferindo arquivos", 2, 2),
    ]
    assert [s["label"] for s in catalog.stages if s["total"] is None] == [
        "Lendo o manifesto",
        "Lendo o manifesto",
        "Gravando no catálogo",
    ]

    derived = RecordingProgress()
    with sessions() as session:
        generated = generate_derivatives(
            session, settings, renderer=FakeRenderer(), progress=derived
        )
    assert generated.generated == 3 and generated.failed == 0
    assert derived.bars() == [("Miniaturas e proxies", 3, 3)]


def test_sort_reports_classification_and_moves(tmp_path: Path) -> None:
    for name in ("a.MP4", "b.MP4", "c.JPG", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    progress = RecordingProgress()

    moves = plan_sort(
        tmp_path,
        prober=lambda _: {"encoded_width": 1920, "encoded_height": 1080},
        progress=progress,
    )
    apply_sort(moves, progress)

    assert progress.bars() == [
        ("Classificando por formato", 3, 3),
        ("Movendo", 3, 3),
    ]


def test_terminal_progress_is_silent_when_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress = TerminalProgress(enabled=False)
    progress.stage("Lendo", None)
    progress.stage("Copiando", 10, unit="B")
    progress.advance(10)
    progress.note("x")
    progress.close()

    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_terminal_progress_writes_bars_to_stderr_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress = TerminalProgress(enabled=True)
    progress.stage("Copiando", 2048, unit="B")
    progress.advance(2048)
    progress.close()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Copiando" in captured.err and "100%" in captured.err


def test_progress_disabled_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMM_NO_PROGRESS", "1")

    assert TerminalProgress().enabled is False
