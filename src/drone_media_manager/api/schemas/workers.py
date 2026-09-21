"""Worker registration and heartbeat wire schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkerRegistration(StrictSchema):
    name: str = Field(min_length=1, max_length=255)
    capabilities: list[str] = Field(min_length=1, max_length=64)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_bounded_and_unique(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            capability = value.strip()
            if not capability or len(capability) > 128:
                raise ValueError("capabilities must contain names of 1 to 128 characters")
            if capability not in normalized:
                normalized.append(capability)
        return normalized


class WorkerRegistrationResponse(StrictSchema):
    worker_id: str
    worker_token: str
    status: str
    revision: int


class WorkerHeartbeat(StrictSchema):
    pass


class WorkerHeartbeatResponse(StrictSchema):
    worker_id: str
    status: str
    revision: int
    last_seen_at: datetime
