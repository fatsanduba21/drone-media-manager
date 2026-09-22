"""Canonical persisted control-plane states."""

from enum import StrEnum


class SourceKind(StrEnum):
    """Classifies a user-selected source without changing its safety contract."""

    REMOVABLE = "REMOVABLE"
    LOCAL = "LOCAL"
    NETWORK = "NETWORK"


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
