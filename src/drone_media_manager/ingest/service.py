"""Small orchestration boundary joining leased jobs to the ingest handler."""

from __future__ import annotations

from drone_media_manager.worker.handlers.ingest import (
    IngestJobHandler,
    JobExecutionResult,
)


class IngestService:
    def __init__(self, handler: IngestJobHandler | None = None) -> None:
        self.handler = handler or IngestJobHandler()

    def execute_claimed(self, claimed_job: object) -> JobExecutionResult:
        return self.handler.execute(claimed_job)
