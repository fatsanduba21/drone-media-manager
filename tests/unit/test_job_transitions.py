"""Legal lifecycle edges prevent terminal jobs from being reopened accidentally."""

import pytest

from drone_media_manager.domain.enums import JobStatus
from drone_media_manager.domain.errors import InvalidTransition
from drone_media_manager.jobs.transitions import assert_job_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.PENDING, JobStatus.LEASED),
        (JobStatus.LEASED, JobStatus.RUNNING),
        (JobStatus.LEASED, JobStatus.INTERRUPTED),
        (JobStatus.LEASED, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.COMPLETE),
        (JobStatus.RUNNING, JobStatus.INTERRUPTED),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.INTERRUPTED, JobStatus.PENDING),
    ],
)
def test_lifecycle_accepts_legal_edges(current: JobStatus, target: JobStatus) -> None:
    assert_job_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.COMPLETE, JobStatus.RUNNING),
        (JobStatus.FAILED, JobStatus.PENDING),
        (JobStatus.PENDING, JobStatus.COMPLETE),
        (JobStatus.LEASED, JobStatus.PENDING),
        (JobStatus.RUNNING, JobStatus.PENDING),
        (JobStatus.INTERRUPTED, JobStatus.LEASED),
        (JobStatus.RUNNING, JobStatus.RUNNING),
    ],
)
def test_lifecycle_rejects_bypasses(current: JobStatus, target: JobStatus) -> None:
    with pytest.raises(InvalidTransition):
        assert_job_transition(current, target)
