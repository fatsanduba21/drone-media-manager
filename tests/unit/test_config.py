from pathlib import Path

import pytest

from drone_media_manager.config import (
    ServerSettings,
    WorkerSettings,
    get_server_settings,
    get_worker_settings,
)

TOKEN = "0123456789abcdef0123456789abcdef"


def test_server_rejects_unc_sqlite_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SQLite database must be local"):
        ServerSettings(
            database_path=Path(r"\\omv\media\dmm.sqlite3"),
            omv_root=tmp_path / "omv",
            worker_bootstrap_token=TOKEN,
        )


def test_server_rejects_cleartext_non_loopback_without_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DMM_ALLOW_INSECURE_LAN"):
        ServerSettings(
            database_path=tmp_path / "dmm.sqlite3",
            omv_root=tmp_path / "omv",
            bind_host="0.0.0.0",
            worker_bootstrap_token=TOKEN,
        )


def test_server_rejects_database_under_configured_synced_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced_root = tmp_path / "synced"
    monkeypatch.setenv("DMM_SYNCED_ROOTS", f'["{synced_root.as_posix()}"]')

    with pytest.raises(ValueError, match="synchronized root"):
        ServerSettings(
            database_path=synced_root / "dmm.sqlite3",
            omv_root=tmp_path / "omv",
            worker_bootstrap_token=TOKEN,
        )


def test_server_rejects_database_under_omv_root(tmp_path: Path) -> None:
    omv_root = tmp_path / "omv"

    with pytest.raises(ValueError, match="OMV root"):
        ServerSettings(
            database_path=omv_root / "dmm.sqlite3",
            omv_root=omv_root,
            worker_bootstrap_token=TOKEN,
        )


def test_server_requires_bootstrap_token_with_at_least_32_characters(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        ServerSettings(
            database_path=tmp_path / "dmm.sqlite3",
            omv_root=tmp_path / "omv",
            worker_bootstrap_token="0123456789abcdef0123456789abcde",
        )


@pytest.mark.parametrize(
    ("tls_certfile", "tls_keyfile"),
    [(Path("server.crt"), None), (None, Path("server.key"))],
)
def test_server_requires_tls_cert_and_key_together(
    tmp_path: Path, tls_certfile: Path | None, tls_keyfile: Path | None
) -> None:
    with pytest.raises(ValueError, match="supplied together"):
        ServerSettings(
            database_path=tmp_path / "dmm.sqlite3",
            omv_root=tmp_path / "omv",
            worker_bootstrap_token=TOKEN,
            tls_certfile=tls_certfile,
            tls_keyfile=tls_keyfile,
        )


def test_server_allows_lan_bind_with_tls_pair(tmp_path: Path) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "dmm.sqlite3",
        omv_root=tmp_path / "omv",
        bind_host="192.168.1.10",
        worker_bootstrap_token=TOKEN,
        tls_certfile=Path("server.crt"),
        tls_keyfile=Path("server.key"),
    )

    assert settings.bind_host == "192.168.1.10"
    assert settings.allow_insecure_lan is False


def test_server_allows_lan_bind_with_explicit_insecure_opt_in(tmp_path: Path) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "dmm.sqlite3",
        omv_root=tmp_path / "omv",
        bind_host="0.0.0.0",
        allow_insecure_lan=True,
        worker_bootstrap_token=TOKEN,
    )

    assert settings.bind_host == "0.0.0.0"
    assert settings.allow_insecure_lan is True


def test_server_defaults_to_loopback_and_keeps_bootstrap_token_secret(
    tmp_path: Path,
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "dmm.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=TOKEN,
    )

    assert settings.bind_host == "127.0.0.1"
    assert settings.worker_bootstrap_token.get_secret_value() == TOKEN


def test_worker_preserves_configured_host_values(tmp_path: Path) -> None:
    settings = WorkerSettings(
        server_url="https://control-plane.example:8443",
        worker_name="windows-laptop",
        omv_root=tmp_path,
        poll_seconds=7.5,
        heartbeat_seconds=22.0,
    )

    assert str(settings.server_url) == "https://control-plane.example:8443/"
    assert settings.worker_name == "windows-laptop"
    assert settings.omv_root == tmp_path
    assert settings.poll_seconds == 7.5
    assert settings.heartbeat_seconds == 22.0


def test_settings_factories_read_host_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "dmm.sqlite3"
    monkeypatch.setenv("DMM_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("DMM_OMV_ROOT", str(tmp_path / "omv"))
    monkeypatch.setenv("DMM_WORKER_BOOTSTRAP_TOKEN", TOKEN)
    monkeypatch.setenv("DMM_SERVER_URL", "https://control-plane.example")
    monkeypatch.setenv("DMM_WORKER_NAME", "windows-laptop")

    server_settings = get_server_settings()
    worker_settings = get_worker_settings()

    assert server_settings.database_path == database_path
    assert worker_settings.worker_name == "windows-laptop"
