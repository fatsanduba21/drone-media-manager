"""Explicit job lifecycle edges; interruption needs separate reconciliation."""

from drone_media_manager.domain.enums import JobStatus
from drone_media_manager.domain.errors import InvalidTransition

_EDGES: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.LEASED}),
    JobStatus.LEASED: frozenset({JobStatus.RUNNING, JobStatus.INTERRUPTED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({JobStatus.COMPLETE, JobStatus.INTERRUPTED, JobStatus.FAILED}),
    JobStatus.INTERRUPTED: frozenset({JobStatus.PENDING}),
    JobStatus.COMPLETE: frozenset(),
    JobStatus.FAILED: frozenset(),
}


def assert_job_transition(current: JobStatus, target: JobStatus) -> None:
    """Reject self transitions, terminal reopening and lifecycle shortcuts."""
    if target not in _EDGES[current]:
        raise InvalidTransition(f"Cannot transition job from {current} to {target}")
