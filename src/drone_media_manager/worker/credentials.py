"""OS credential-manager boundary for worker credentials."""

from __future__ import annotations

from typing import Protocol

import keyring


class KeyringBackend(Protocol):
    """The narrow keyring interface needed by the worker."""

    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...


class CredentialStore:
    """Stores each worker's permanent token in the local OS credential manager."""

    service_name = "DroneMediaManager"

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend: KeyringBackend = backend if backend is not None else keyring

    def get_token(self, worker_name: str) -> str | None:
        return self._backend.get_password(self.service_name, worker_name)

    def set_token(self, worker_name: str, token: str) -> None:
        self._backend.set_password(self.service_name, worker_name, token)
