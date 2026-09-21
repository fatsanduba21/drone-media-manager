"""Authentication and secret-handling boundaries for worker APIs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import Message, Scope

from drone_media_manager.api.app import create_app
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import AuditEvent, Job, Worker
from drone_media_manager.db.session import create_engine_from_settings, session_factory


@pytest.fixture
def secured_api(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, sessionmaker[Session], ServerSettings]]:
    settings = ServerSettings(
        database_path=tmp_path / "security.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("bootstrap-token-that-is-at-least-32-chars"),
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["server_settings"] = settings
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    with TestClient(create_app(settings, factory), raise_server_exceptions=False) as client:
        yield client, factory, settings
    engine.dispose()


def register(client: TestClient, settings: ServerSettings, name: str) -> tuple[str, str]:
    response = client.post(
        "/api/workers/register",
        headers={"Authorization": f"Bearer {settings.worker_bootstrap_token.get_secret_value()}"},
        json={"name": name, "capabilities": ["ingest"]},
    )
    assert response.status_code == 201
    return response.json()["worker_id"], response.json()["worker_token"]


def test_worker_api_module_is_importable() -> None:
    """The first production change is adding the application factory module."""
    from drone_media_manager.api.app import create_app

    assert callable(create_app)


def test_wrong_and_cross_worker_tokens_are_rejected(
    secured_api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = secured_api
    first_id, first_token = register(client, settings, "first")
    _, second_token = register(client, settings, "second")
    for token in ("wrong-token", second_token):
        response = client.post(
            f"/api/workers/{first_id}/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "invalid_worker_token"}}
    assert first_token not in str(client.post(f"/api/workers/{first_id}/heartbeat", json={}).json())


def test_request_schemas_reject_extras_with_stable_validation_error(
    secured_api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = secured_api
    response = client.post(
        "/api/workers/register",
        headers={"Authorization": f"Bearer {settings.worker_bootstrap_token.get_secret_value()}"},
        json={"name": "worker", "capabilities": ["ingest"], "admin": True},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "admin" in str(body)
    assert settings.worker_bootstrap_token.get_secret_value() not in str(body)


def test_body_larger_than_one_mebibyte_is_rejected_before_route_handling(
    secured_api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = secured_api
    response = client.post(
        "/api/workers/register",
        headers={
            "Authorization": f"Bearer {settings.worker_bootstrap_token.get_secret_value()}",
            "Content-Type": "application/json",
        },
        content=b'"' + b"x" * (1024 * 1024) + b'"',
    )
    assert response.status_code == 413
    assert response.json() == {"error": {"code": "request_body_too_large"}}
    with factory() as session:
        assert session.scalars(select(Worker)).all() == []


def test_fragmented_body_without_content_length_is_bounded_before_downstream(
    secured_api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = secured_api
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/workers/register",
        "raw_path": b"/api/workers/register",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (
                b"authorization",
                f"Bearer {settings.worker_bootstrap_token.get_secret_value()}".encode(),
            ),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    incoming = iter(
        [
            {"type": "http.request", "body": b"x" * 700_000, "more_body": True},
            {"type": "http.request", "body": b"y" * 700_000, "more_body": False},
        ]
    )
    outgoing: list[Message] = []

    async def receive() -> Message:
        return cast(Message, next(incoming))

    async def send(message: Message) -> None:
        outgoing.append(message)

    async def invoke() -> None:
        await client.app(scope, receive, send)

    asyncio.run(invoke())
    start = next(message for message in outgoing if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in outgoing
        if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert json.loads(body) == {"error": {"code": "request_body_too_large"}}
    with factory() as session:
        assert session.scalars(select(Worker)).all() == []


def test_rejected_job_mutation_does_not_write_success_audit_or_echo_secrets(
    secured_api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = secured_api
    worker_id, token = register(client, settings, "worker")
    lease_secret = "lease-secret-that-must-never-be-echoed"
    response = client.post(
        "/api/worker-jobs/missing/progress",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "worker_id": worker_id,
            "lease_token": lease_secret,
            "revision": 0,
            "progress": 0.5,
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "invalid_lease"}}
    assert lease_secret not in response.text
    assert token not in response.text
    with factory() as session:
        events = session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "job")).all()
        assert events == []
        assert session.get(Job, "missing") is None
