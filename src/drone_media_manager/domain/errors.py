"""Domain failures for lifecycle and optimistic lease operations."""


class InvalidTransition(ValueError):
    """The requested lifecycle edge is not legal."""


class LeaseConflict(ValueError):
    """The worker, token, revision, or validity of a lease does not match."""
