"""Canonical persisted control-plane states."""

from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class WorkerStatus(StrEnum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    BUSY = "BUSY"
