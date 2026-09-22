from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pydantic import SecretStr

from drone_media_manager.cli.server import main
from drone_media_manager.config import ServerSettings


class FakeAdminClient:
    def __init__(self) -> None:
        self.calls = []

    def confirm_ingest(self, snapshot_id: str, trip_id: str, revision: int = 2):
        self.calls.append(("confirm", snapshot_id, trip_id, revision))
        return SimpleNamespace(ingest_id="ingest-1", status="DISCOVERED")

    def get_ingest(self, ingest_id: str):
        self.calls.append(("status", ingest_id))
        return SimpleNamespace(ingest_id=ingest_id, status="VERIFIED")


def settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("bootstrap-token-that-is-at-least-32-chars"),
    )


def test_server_confirm_calls_local_admin_confirmation(tmp_path: Path, capsys) -> None:
    client = FakeAdminClient()
    assert (
        main(
            ["ingest", "confirm", "snapshot-1", "--trip", "trip-1"],
            settings_loader=lambda: settings(tmp_path),
            admin_client_factory=lambda _: client,
        )
        == 0
    )
    assert client.calls == [("confirm", "snapshot-1", "trip-1", 2)]
    assert "ingest-1" in capsys.readouterr().out


def test_server_status_queries_real_ingest(tmp_path: Path, capsys) -> None:
    client = FakeAdminClient()
    assert (
        main(
            ["ingest", "status", "ingest-1"],
            settings_loader=lambda: settings(tmp_path),
            admin_client_factory=lambda _: client,
        )
        == 0
    )
    assert client.calls == [("status", "ingest-1")]
    assert "VERIFIED" in capsys.readouterr().out
