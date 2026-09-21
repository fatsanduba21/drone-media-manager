"""Typed HTTP boundary for the authenticated worker API."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
from typing import Any, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from drone_media_manager.api.schemas.jobs import (
    ClaimRequest,
    ClaimResponse,
    CompleteRequest,
    FailRequest,
    JobMutationResponse,
    ProgressRequest,
)
from drone_media_manager.api.schemas.workers import (
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegistration,
    WorkerRegistrationResponse,
)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
RequestRunner = Callable[[Callable[[], httpx.Response], float], httpx.Response]


class WorkerTransportError(RuntimeError):
    """The Mac control plane could not be reached safely."""


class WorkerProtocolError(RuntimeError):
    """The control plane returned a response outside the worker contract."""


class WorkerApiError(RuntimeError):
    """A stable non-success response from the control plane."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"worker api request failed: {status_code} ({code})")


class WorkerApiClient:
    """Makes authenticated worker API calls without exposing credentials in reprs."""

    def __init__(
        self,
        server_url: str,
        token: str,
        *,
        http_client: httpx.Client | None = None,
        request_runner: RequestRunner | None = None,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._token = token
        self.http_client = http_client or httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))
        self._request_runner = request_runner or _run_with_deadline

    def __repr__(self) -> str:
        return f"WorkerApiClient(server_url={self._server_url!r}, token=[REDACTED])"

    def register(self, worker_name: str, capabilities: list[str]) -> WorkerRegistrationResponse:
        return self._post("/api/workers/register", WorkerRegistration(name=worker_name, capabilities=capabilities), WorkerRegistrationResponse)

    def heartbeat(self, worker_id: str) -> WorkerHeartbeatResponse:
        return self._post(f"/api/workers/{worker_id}/heartbeat", WorkerHeartbeat(), WorkerHeartbeatResponse)

    def claim(self, worker_id: str, lease_seconds: int = 60) -> ClaimResponse | None:
        request = ClaimRequest(worker_id=worker_id, idempotency_key=uuid4(), lease_seconds=lease_seconds)
        response = self._request("POST", "/api/worker-jobs/claim", request.model_dump(mode="json"))
        if response.status_code == 204:
            return None
        return self._parse_response(response, ClaimResponse)

    def progress(self, job_id: str, worker_id: str, lease_token: str, revision: int, progress: float) -> JobMutationResponse:
        return self._mutate(job_id, ProgressRequest(worker_id=worker_id, lease_token=lease_token, revision=revision, idempotency_key=uuid4(), progress=progress), "progress")

    def complete(self, job_id: str, worker_id: str, lease_token: str, revision: int) -> JobMutationResponse:
        return self._mutate(job_id, CompleteRequest(worker_id=worker_id, lease_token=lease_token, revision=revision, idempotency_key=uuid4()), "complete")

    def fail(self, job_id: str, worker_id: str, lease_token: str, revision: int, error: str) -> JobMutationResponse:
        return self._mutate(job_id, FailRequest(worker_id=worker_id, lease_token=lease_token, revision=revision, idempotency_key=uuid4(), error=error), "fail")

    def _mutate(self, job_id: str, request: ProgressRequest | CompleteRequest | FailRequest, action: str) -> JobMutationResponse:
        return self._post(f"/api/worker-jobs/{job_id}/{action}", request, JobMutationResponse)

    def _post(
        self, path: str, request: BaseModel, response_type: type[ResponseModel]
    ) -> ResponseModel:
        return self._parse_response(self._request("POST", path, request.model_dump(mode="json")), response_type)

    def _request(self, method: str, path: str, json: dict[str, Any]) -> httpx.Response:
        try:
            response = self._request_runner(
                lambda: self.http_client.request(
                    method,
                    f"{self._server_url}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {self._token}"},
                ),
                30.0,
            )
        except TimeoutError as error:
            raise WorkerTransportError("control plane request deadline exceeded") from error
        except httpx.TransportError as error:
            raise WorkerTransportError("control plane unavailable") from error
        if response.is_error:
            raise WorkerApiError(response.status_code, _response_code(response))
        return response

    @staticmethod
    def _parse_response(
        response: httpx.Response, response_type: type[ResponseModel]
    ) -> ResponseModel:
        try:
            return response_type.model_validate(response.json())
        except (ValidationError, ValueError, TypeError) as error:
            raise WorkerProtocolError("invalid control-plane response") from error


def _response_code(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", {})
        code = detail.get("code") if isinstance(detail, dict) else None
        return code if isinstance(code, str) else "request_failed"
    except (ValueError, AttributeError):
        return "request_failed"


def _run_with_deadline(
    operation: Callable[[], httpx.Response], total_seconds: float
) -> httpx.Response:
    """Return at a total wall-clock deadline even if HTTP phase timeouts add up."""
    completed = Event()
    outcome: list[httpx.Response | httpx.HTTPError] = []

    def execute() -> None:
        try:
            outcome.append(operation())
        except httpx.HTTPError as error:
            outcome.append(error)
        finally:
            completed.set()

    Thread(target=execute, daemon=True).start()
    if not completed.wait(total_seconds):
        raise TimeoutError
    result = outcome[0]
    if isinstance(result, httpx.HTTPError):
        raise result
    return result
