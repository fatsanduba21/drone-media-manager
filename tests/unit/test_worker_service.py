from __future__ import annotations

from dataclasses import dataclass
from threading import Event

import pytest

from drone_media_manager.api.schemas.jobs import ClaimResponse
from drone_media_manager.api.schemas.workers import WorkerHeartbeatResponse
from drone_media_manager.cli.worker import main
from drone_media_manager.config import WorkerSettings
from drone_media_manager.worker.client import WorkerTransportError
from drone_media_manager.worker.credentials import CredentialStore
from drone_media_manager.worker.service import PollResult, WorkerService


@dataclass
class FakeApi:
    heartbeat_error: Exception | None = None
    claim_error: Exception | None = None
    claim_calls: int = 0

    def heartbeat(self, worker_id: str) -> WorkerHeartbeatResponse:
        if self.heartbeat_error:
            raise self.heartbeat_error
        return WorkerHeartbeatResponse(
            worker_id=worker_id,
            status="ONLINE",
            revision=1,
            last_seen_at="2026-09-21T00:00:00Z",
        )

    def claim(self, worker_id: str) -> ClaimResponse | None:
        self.claim_calls += 1
        if self.claim_error:
            raise self.claim_error
        return None


def test_connection_loss_before_heartbeat_returns_offline_without_claiming() -> None:
    api = FakeApi(heartbeat_error=WorkerTransportError("mac offline"))
    service = WorkerService(api, "worker-1")

    assert service.run_once() is PollResult.OFFLINE
    assert api.claim_calls == 0


def test_connection_loss_mid_poll_never_finalizes_a_job() -> None:
    api = FakeApi(claim_error=WorkerTransportError("mac offline"))
    service = WorkerService(api, "worker-1")

    assert service.run_once() is PollResult.OFFLINE
    assert api.claim_calls == 1


def test_idle_poll_returns_idle_after_heartbeat() -> None:
    service = WorkerService(FakeApi(), "worker-1")

    assert service.run_once() is PollResult.IDLE


def test_run_forever_caps_exponential_recovery_backoff_and_honors_stop() -> None:
    api = FakeApi(heartbeat_error=WorkerTransportError("mac offline"))
    sleeps: list[float] = []
    stop = Event()

    def wait(_: Event, seconds: float) -> bool:
        sleeps.append(seconds)
        if len(sleeps) == 6:
            stop.set()
        return stop.is_set()

    WorkerService(api, "worker-1", wait=wait).run_forever(stop)

    assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0]


def test_run_forever_wait_is_interruptible_by_stop_event() -> None:
    api = FakeApi(heartbeat_error=WorkerTransportError("mac offline"))
    stop = Event()
    waits: list[float] = []

    def wait(event: Event, seconds: float) -> bool:
        waits.append(seconds)
        event.set()
        return True

    WorkerService(api, "worker-1", wait=wait).run_forever(stop)

    assert waits == [2.0]


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password


def test_credential_store_uses_worker_name_and_fixed_service_name() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring)

    store.set_token("windows-laptop", "permanent-secret")

    assert keyring.values == {("DroneMediaManager", "windows-laptop"): "permanent-secret"}
    assert store.get_token("windows-laptop") == "permanent-secret"


def test_pair_reads_environment_bootstrap_token_before_hidden_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = WorkerSettings(
        server_url="https://mac.example",
        worker_name="windows-laptop",
        omv_root="C:/media",
    )
    received: list[str] = []

    class PairClient:
        def __init__(self, _: str, token: str) -> None:
            received.append(token)

        def register(self, _: str, __: list[str]):
            return type("Registration", (), {"worker_token": "stored-token"})()

    keyring = FakeKeyring()
    monkeypatch.setenv("DMM_WORKER_BOOTSTRAP_TOKEN", "environment-bootstrap")

    assert main(
        ["pair"],
        settings_loader=lambda: settings,
        client_factory=PairClient,
        credential_store=CredentialStore(keyring),
        prompt_secret=lambda _: (_ for _ in ()).throw(AssertionError("prompted")),
    ) == 0
    assert received == ["environment-bootstrap"]
    assert keyring.values[("DroneMediaManager", "windows-laptop")] == "stored-token"


def test_once_requires_stored_token_without_leaking_it(capsys: pytest.CaptureFixture[str]) -> None:
    settings = WorkerSettings(
        server_url="https://mac.example",
        worker_name="windows-laptop",
        omv_root="C:/media",
    )

    assert main(
        ["once"],
        settings_loader=lambda: settings,
        credential_store=CredentialStore(FakeKeyring()),
    ) == 2
    assert "token" in capsys.readouterr().err.lower()


def test_run_parses_subcommand_and_uses_stored_permanent_token() -> None:
    settings = WorkerSettings(
        server_url="https://mac.example",
        worker_name="windows-laptop",
        omv_root="C:/media",
    )
    keyring = FakeKeyring()
    keyring.set_password("DroneMediaManager", "windows-laptop", "stored-token")
    calls: list[str] = []

    class RunClient:
        def __init__(self, _: str, token: str) -> None:
            calls.append(token)

    class RunService:
        def __init__(self, _: RunClient, __: str) -> None:
            pass

        def run_forever(self, _: Event) -> None:
            calls.append("run")

    assert main(
        ["run"],
        settings_loader=lambda: settings,
        client_factory=RunClient,
        service_factory=RunService,
        credential_store=CredentialStore(keyring),
    ) == 0
    assert calls == ["stored-token", "run"]
