"""Canonical persisted control-plane states."""

from enum import StrEnum


class SourceKind(StrEnum):
    """Classifies a user-selected source without changing its safety contract."""

    REMOVABLE = "REMOVABLE"
    LOCAL = "LOCAL"
    NETWORK = "NETWORK"


class PairStatus(StrEnum):
    """Describes the optional-SRT state of one logical media item."""

    PAIRED = "PAIRED"
    VIDEO_WITHOUT_SRT = "VIDEO_WITHOUT_SRT"
    ORPHAN_SRT = "ORPHAN_SRT"


class IngestStatus(StrEnum):
    """Aggregate safe-ingest lifecycle owned by the Mac control plane."""

    DISCOVERED = "DISCOVERED"
    COPYING = "COPYING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class IngestItemStatus(StrEnum):
    """Per-file safe-ingest lifecycle persisted with durable checkpoints."""

    PENDING = "PENDING"
    COPYING = "COPYING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


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
