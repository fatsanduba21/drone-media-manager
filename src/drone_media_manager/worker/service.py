"""Safe polling orchestration for an intermittently connected Windows worker."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from threading import Event
from typing import Protocol

from drone_media_manager.api.schemas.jobs import ClaimResponse
from drone_media_manager.api.schemas.workers import WorkerHeartbeatResponse
from drone_media_manager.worker.client import WorkerTransportError
from drone_media_manager.worker.handlers.ingest import IngestJobHandler


class WorkerApi(Protocol):
    def heartbeat(self, worker_id: str) -> WorkerHeartbeatResponse: ...
    def claim(self, worker_id: str) -> ClaimResponse | None: ...


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
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._wait = wait or _wait_for_stop
        self._handler = handler or IngestJobHandler()

    def run_once(self) -> PollResult:
        try:
            self._api.heartbeat(self._worker_id)
            job = self._api.claim(self._worker_id)
        except WorkerTransportError:
            return PollResult.OFFLINE
        if job is None:
            return PollResult.IDLE
        if job.kind == "ingest":
            self._handler.execute(job)
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
