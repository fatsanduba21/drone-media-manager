"""Safe polling orchestration for an intermittently connected Windows worker."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Protocol

from drone_media_manager.api.schemas.jobs import ClaimResponse, JobMutationResponse
from drone_media_manager.api.schemas.workers import WorkerHeartbeatResponse
from drone_media_manager.worker.client import WorkerTransportError
from drone_media_manager.worker.handlers.ingest import IngestJobHandler
from drone_media_manager.worker.snapshots import LocalSnapshotRegistry


class WorkerApi(Protocol):
    def heartbeat(self, worker_id: str) -> WorkerHeartbeatResponse: ...
    def claim(self, worker_id: str) -> ClaimResponse | None: ...
    def progress(
        self,
        job_id: str,
        worker_id: str,
        lease_token: str,
        revision: int,
        progress: float,
    ) -> JobMutationResponse: ...
    def complete(
        self, job_id: str, worker_id: str, lease_token: str, revision: int
    ) -> object: ...
    def fail(
        self, job_id: str, worker_id: str, lease_token: str, revision: int, error: str
    ) -> object: ...


class PollResult(StrEnum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    CLAIMED = "CLAIMED"


class WorkerService:
    """Polls safely; media work and job finalization are intentionally deferred."""

    def __init__(
        self,
        api: WorkerApi,
        worker_id: str,
        *,
        wait: Callable[[Event, float], bool] | None = None,
        handler: IngestJobHandler | None = None,
        snapshot_registry: LocalSnapshotRegistry | None = None,
        omv_root: Path | None = None,
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._wait = wait or _wait_for_stop
        self._handler = handler or IngestJobHandler(
            snapshot_registry=snapshot_registry,
            omv_root=omv_root,
        )

    def run_once(self) -> PollResult:
        try:
            self._api.heartbeat(self._worker_id)
            job = self._api.claim(self._worker_id)
        except WorkerTransportError:
            return PollResult.OFFLINE
        if job is None:
            return PollResult.IDLE
        if job.kind == "ingest":
            reporter = _ApiProgressReporter(
                self._api,
                job_id=job.job_id,
                worker_id=self._worker_id,
                lease_token=job.lease_token,
                revision=job.revision,
                bytes_total=_payload_bytes_total(job.payload),
            )
            execution_job = SimpleNamespace(
                payload=job.payload,
                reporter=reporter,
                lease_valid=lambda: True,
            )
            result = self._handler.execute(execution_job)
            if job.lease_token is not None:
                if result.status == "VERIFIED":
                    self._api.complete(
                        job.job_id,
                        self._worker_id,
                        job.lease_token,
                        reporter.revision,
                    )
                else:
                    self._api.fail(
                        job.job_id,
                        self._worker_id,
                        job.lease_token,
                        reporter.revision,
                        result.error_code or result.status,
                    )
        return PollResult.CLAIMED

    def run_forever(self, stop_event: Event) -> None:
        offline_attempt = 0
        while not stop_event.is_set():
            result = self.run_once()
            if result is PollResult.OFFLINE:
                delay = min(2.0 * (2**offline_attempt), 60.0)
                offline_attempt += 1
            else:
                delay = 2.0
                offline_attempt = 0
            self._wait(stop_event, delay)


def _wait_for_stop(stop_event: Event, seconds: float) -> bool:
    return stop_event.wait(seconds)


class _ApiProgressReporter:
    def __init__(
        self,
        api: WorkerApi,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str | None,
        revision: int,
        bytes_total: int,
    ) -> None:
        self._api = api
        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_token = lease_token
        self.revision = revision
        self._bytes_total = max(bytes_total, 1)

    def progress(self, value: float | None) -> None:
        if self._lease_token is None or value is None:
            return
        progress = min(float(value) / self._bytes_total, 1.0)
        response = self._api.progress(
            self._job_id, self._worker_id, self._lease_token, self.revision, progress
        )
        self.revision = response.revision

    def checkpoint(self, value: float | None) -> None:
        self.progress(value)

    def verifying(self, _: object) -> None:
        return

    def verified(self, _: object) -> None:
        return

    def complete(self, _: object) -> None:
        return

    def interrupted(self, _: object) -> None:
        return

    def failed(self, _: object) -> None:
        return


def _payload_bytes_total(payload: dict[str, object]) -> int:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return 1
    return sum(
        int(item.get("source_size_bytes", 0))
        for item in items
        if isinstance(item, dict)
    )
