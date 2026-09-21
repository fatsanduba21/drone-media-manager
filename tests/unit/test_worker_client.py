from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from drone_media_manager.worker.client import (
    WorkerApiClient,
    WorkerApiError,
    WorkerProtocolError,
    WorkerTransportError,
)


def test_register_sends_bootstrap_bearer_and_parses_typed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/workers/register"
        assert request.headers["authorization"] == "Bearer bootstrap-secret"
        assert json.loads(request.content) == {
            "name": "windows-laptop",
            "capabilities": ["ingest"],
        }
        return httpx.Response(
            201,
            json={
                "worker_id": "worker-1",
                "worker_token": "permanent-secret",
                "status": "OFFLINE",
                "revision": 0,
            },
        )

    client = WorkerApiClient(
        "https://mac.example",
        "bootstrap-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    registered = client.register("windows-laptop", ["ingest"])

    assert registered.worker_id == "worker-1"
    assert registered.worker_token == "permanent-secret"


def test_claim_returns_none_for_no_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/worker-jobs/claim"
        return httpx.Response(204)

    client = WorkerApiClient(
        "https://mac.example",
        "permanent-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.claim("worker-1") is None


def test_rejects_malformed_job_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "missing-required-fields"})

    client = WorkerApiClient(
        "https://mac.example",
        "permanent-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WorkerProtocolError):
        client.claim("worker-1")


def test_non_success_response_is_stable_and_redacts_token() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"code": "invalid_token"}})

    client = WorkerApiClient(
        "https://mac.example",
        "permanent-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WorkerApiError) as captured:
        client.heartbeat("worker-1")

    assert captured.value.status_code == 401
    assert captured.value.code == "invalid_token"
    assert "permanent-secret" not in repr(captured.value)


def test_client_repr_never_exposes_permanent_or_lease_token() -> None:
    client = WorkerApiClient("https://mac.example", "permanent-secret")

    assert "permanent-secret" not in repr(client)
    assert "permanent-secret" not in str(client)


def test_progress_uses_a_fresh_uuid_idempotency_key() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"job_id": "job-1", "status": "RUNNING", "revision": 3, "progress": 0.5},
        )

    client = WorkerApiClient(
        "https://mac.example",
        "permanent-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.progress("job-1", "worker-1", "lease-secret", 2, 0.5)

    assert response.revision == 3
    assert UUID(str(captured["idempotency_key"]))
    assert captured["lease_token"] == "lease-secret"


def test_client_uses_required_timeout_limits() -> None:
    client = WorkerApiClient("https://mac.example", "permanent-secret")

    assert client.http_client.timeout.connect == 5.0
    assert client.http_client.timeout.read == 30.0


def test_client_enforces_one_total_request_deadline() -> None:
    deadlines: list[float] = []

    def deadline_runner(operation, seconds: float) -> httpx.Response:
        del operation
        deadlines.append(seconds)
        raise TimeoutError

    client = WorkerApiClient(
        "https://mac.example",
        "permanent-secret",
        request_runner=deadline_runner,
    )

    with pytest.raises(WorkerTransportError, match="deadline"):
        client.heartbeat("worker-1")

    assert deadlines == [30.0]
