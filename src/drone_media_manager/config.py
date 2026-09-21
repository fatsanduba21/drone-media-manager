"""Validated host-specific configuration for the control plane and worker."""

from __future__ import annotations

import ipaddress
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _BaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DMM_",
        extra="ignore",
    )


class ServerSettings(_BaseSettings):
    """Settings for the Mac-hosted control plane."""

    database_path: Path
    omv_root: Path
    bind_host: str = "127.0.0.1"
    port: int = 8000
    allow_insecure_lan: bool = False
    worker_bootstrap_token: SecretStr
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None
    synced_roots: tuple[Path, ...] = ()

    @field_validator("tls_certfile", "tls_keyfile", mode="before")
    @classmethod
    def empty_tls_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("worker_bootstrap_token")
    @classmethod
    def bootstrap_token_is_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("Worker bootstrap token must be at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_server_safety(self) -> ServerSettings:
        database_path_text = str(self.database_path)
        if database_path_text.startswith(("\\\\", "//")):
            raise ValueError("SQLite database must be local; UNC paths are not allowed")

        resolved_database_path = self.database_path.expanduser().resolve(strict=False)
        for synced_root in self.synced_roots:
            resolved_synced_root = synced_root.expanduser().resolve(strict=False)
            if resolved_database_path.is_relative_to(resolved_synced_root):
                raise ValueError("SQLite database must not be under a synchronized root")

        if (self.tls_certfile is None) != (self.tls_keyfile is None):
            raise ValueError(
                "DMM_TLS_CERTFILE and DMM_TLS_KEYFILE must be supplied together"
            )

        if not _is_loopback_host(self.bind_host):
            has_tls = self.tls_certfile is not None
            if not has_tls and not self.allow_insecure_lan:
                raise ValueError(
                    "Non-loopback binds require TLS or DMM_ALLOW_INSECURE_LAN=true"
                )

        return self


class WorkerSettings(_BaseSettings):
    """Settings for the intermittently connected Windows worker."""

    server_url: AnyHttpUrl
    worker_name: str = Field(min_length=1)
    omv_root: Path
    poll_seconds: float = Field(default=10.0, gt=0)
    heartbeat_seconds: float = Field(default=30.0, gt=0)


def get_server_settings() -> ServerSettings:
    """Read control-plane settings from the current host environment."""
    return ServerSettings()  # type: ignore[call-arg]  # Populated from DMM_* env.


def get_worker_settings() -> WorkerSettings:
    """Read worker settings from the current host environment."""
    return WorkerSettings()  # type: ignore[call-arg]  # Populated from DMM_* env.


def _is_loopback_host(host: str) -> bool:
    normalized_host = host.strip().lower()
    if normalized_host == "localhost":
        return True

    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False
