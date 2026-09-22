"""Domain failures for lifecycle and optimistic lease operations."""

from enum import StrEnum


class StaleRevision(ValueError):
    """The supplied optimistic revision no longer owns the requested write."""


class InvalidTransition(ValueError):
    """The requested lifecycle edge is not legal."""


class LeaseConflictReason(StrEnum):
    """Publicly safe lease-fencing outcomes determined under the write lock."""

    INVALID_LEASE = "invalid_lease"
    STALE_REVISION = "stale_revision"
    EXPIRED_LEASE = "expired_lease"


class LeaseConflict(ValueError):
    """A categorized lease failure whose reason is safe for API mapping."""

    def __init__(self, reason: LeaseConflictReason) -> None:
        self.reason = reason
        super().__init__(reason.value)
