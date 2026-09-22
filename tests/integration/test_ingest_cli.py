from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from drone_media_manager.cli.worker import main
from drone_media_manager.config import WorkerSettings


def test_worker_dry_run_requires_a_source_directory(tmp_path: Path) -> None:
    assert (
        main(
            ["ingest", "--dry-run", str(tmp_path)],
            settings_loader=lambda: _settings(tmp_path),
        )
        == 0
    )
    assert main(["ingest", "--dry-run", str(tmp_path / "missing")]) == 2


def test_worker_verify_requires_an_ingest_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "drone_media_manager.cli.worker.CredentialStore.get_token", lambda *_: "token"
    )
    monkeypatch.setattr(
        "drone_media_manager.cli.worker.CredentialStore.get_worker_id",
        lambda *_: "worker-1",
    )
    assert (
        main(
            ["verify", "ingest-1"],
            settings_loader=lambda: _settings(tmp_path),
            client_factory=lambda *_: FakeWorkerClient(),
        )
        == 0
    )


class FakeWorkerClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def create_snapshot(
        self, worker_id, source_kind, source_volume_identity, expires_at
    ):
        self.calls.append(("create_snapshot", source_kind))
        return SimpleNamespace(snapshot_id="snapshot-1", revision=0)

    def append_snapshot_entries(self, snapshot_id, worker_id, revision, entries):
        self.calls.append(("append_snapshot_entries", len(entries)))
        return SimpleNamespace(revision=1)

    def finalize_snapshot(self, snapshot_id, worker_id, revision, declared_item_count):
        self.calls.append(("finalize_snapshot", declared_item_count))
        return SimpleNamespace(snapshot_id=snapshot_id, revision=2)

    def get_ingest(self, ingest_id):
        self.calls.append(("get_ingest", ingest_id))
        return SimpleNamespace(ingest_id=ingest_id, status="VERIFIED")


def _settings(tmp_path: Path) -> WorkerSettings:
    (tmp_path / "omv").mkdir(exist_ok=True)
    return WorkerSettings(
        server_url="http://127.0.0.1:8000",
        worker_name="worker",
        omv_root=tmp_path / "omv",
    )


def test_worker_scan_executes_inventory_and_prints_pair_states(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "clip.MP4").write_bytes(b"video")
    (tmp_path / "clip.SRT").write_text("1", encoding="utf-8")
    (tmp_path / "orphan.srt").write_text("1", encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "PAIRED" in output
    assert "ORPHAN_SRT" in output
    assert "fingerprint=" in output


def test_worker_submit_uploads_immutable_snapshot(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    (tmp_path / "clip.mp4").write_bytes(b"video")
    fake = FakeWorkerClient()
    monkeypatch.setattr(
        "drone_media_manager.cli.worker.CredentialStore.get_token", lambda *_: "token"
    )
    monkeypatch.setattr(
        "drone_media_manager.cli.worker.CredentialStore.get_worker_id",
        lambda *_: "worker-1",
    )
    assert (
        main(
            ["submit", str(tmp_path)],
            settings_loader=lambda: _settings(tmp_path),
            client_factory=lambda *_: fake,
        )
        == 0
    )
    assert [name for name, _ in fake.calls] == [
        "create_snapshot",
        "append_snapshot_entries",
        "finalize_snapshot",
    ]
    assert "snapshot-1" in capsys.readouterr().out


def test_worker_verify_queries_real_ingest_status(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    fake = FakeWorkerClient()
    monkeypatch.setattr(
        "drone_media_manager.cli.worker.CredentialStore.get_token", lambda *_: "token"
    )
    monkeypatch.setattr(
        "drone_media_manager.cli.worker.CredentialStore.get_worker_id",
        lambda *_: "worker-1",
    )
    assert (
        main(
            ["verify", "ingest-1"],
            settings_loader=lambda: _settings(tmp_path),
            client_factory=lambda *_: fake,
        )
        == 0
    )
    assert fake.calls == [("get_ingest", "ingest-1")]
    assert "VERIFIED" in capsys.readouterr().out
