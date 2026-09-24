"""End-user HTTPS login and server-side catalog access control."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.auth.passwords import hash_password
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.db.models.catalog import CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.time import utc_now

ASSET = "a" * 64
PASSWORD = "correct horse battery staple"


@pytest.fixture
def auth_app(tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    omv = tmp_path / "omv"
    omv.mkdir()
    settings = ServerSettings(
        database_path=tmp_path / "auth.sqlite3",
        omv_root=omv,
        derivatives_root=tmp_path / "cache",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        user = User(username="editor", password_hash=hash_password(PASSWORD))
        trip = Trip(name="Viagem", slug="viagem", nas_rel_path="viagem")
        session.add_all([user, trip])
        session.flush()
        asset = CatalogAsset(
            asset_id=ASSET,
            trip_id=trip.id,
            media_type="VIDEO",
            classification="INSTAGRAM_9X16",
            verification_status="VERIFIED",
        )
        session.add(asset)
        session.flush()
        for kind, suffix, content in (
            ("THUMBNAIL", ".jpg", b"thumbnail"),
            ("PROXY", ".mp4", b"0123456789"),
        ):
            profile = "grid-v1" if kind == "THUMBNAIL" else "web-720p-v1"
            rel_path = f"{ASSET[:2]}/{ASSET}/{profile}{suffix}"
            path = settings.derivatives_root / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            session.add(
                Derivative(
                    catalog_asset_id=asset.id,
                    kind=kind,
                    status="READY",
                    profile_version=profile,
                    source_sha256="f" * 64,
                    rel_path=rel_path,
                    output_sha256=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                )
            )
        session.commit()
    with TestClient(
        create_app(settings, sessions), base_url="https://testserver"
    ) as client:
        yield client, sessions
    engine.dispose()


def login(client: TestClient, password: str = PASSWORD) -> object:
    page = client.get("/login")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match is not None
    return client.post(
        "/login",
        data={"username": "editor", "password": password, "csrf_token": match[1]},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )


def test_direct_catalog_and_media_require_user_session(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = auth_app
    assert client.get("/gallery", follow_redirects=False).status_code == 303
    for path in (
        "/api/catalog/trips",
        f"/api/catalog/assets/{ASSET}",
        f"/api/catalog/assets/{ASSET}/thumbnail",
        f"/api/catalog/assets/{ASSET}/proxy",
        f"/api/catalog/assets/{ASSET}/download",
    ):
        assert client.get(path).status_code == 401
    assert client.get("/health").status_code == 200


def test_login_cookie_logout_and_session_revocation(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = auth_app
    response = login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/gallery"
    cookie = response.headers["set-cookie"]
    assert "__Host-dmm_session=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert client.get("/api/catalog/trips").status_code == 200
    with sessions() as session:
        record = session.query(UserSession).one()
        csrf = record.csrf_token
    assert client.post("/logout").status_code == 403
    assert (
        client.post(
            "/logout",
            headers={"X-CSRF-Token": csrf, "Origin": "https://testserver"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.get("/api/catalog/trips").status_code == 401


def test_expired_session_and_bad_credentials(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = auth_app
    assert login(client, "incorrect").status_code == 401
    assert client.get("/api/catalog/trips").status_code == 401
    assert login(client).status_code == 303
    with sessions() as session:
        record = session.query(UserSession).one()
        record.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    assert client.get("/api/catalog/trips").status_code == 401


def test_http_cannot_use_a_copied_session_cookie(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = auth_app
    assert login(client).status_code == 303
    token = client.cookies.get("__Host-dmm_session")
    assert token is not None
    with TestClient(client.app, base_url="http://testserver") as insecure:
        response = insecure.get(
            "/api/catalog/trips",
            cookies={"__Host-dmm_session": token},
        )
    assert response.status_code == 426


def test_login_rejects_http_and_csrf_failure(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = auth_app
    with TestClient(client.app, base_url="http://testserver") as insecure:
        assert insecure.get("/login").status_code == 426
        assert (
            insecure.post(
                "/login", data={"username": "editor", "password": PASSWORD}
            ).status_code
            == 426
        )
    assert (
        client.post(
            "/login", data={"username": "editor", "password": PASSWORD}
        ).status_code
        == 403
    )


def test_repeated_invalid_login_is_limited(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = auth_app
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    assert login(client, PASSWORD).status_code == 429


def test_selection_persists_across_sessions_and_is_idempotent(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = auth_app
    assert login(client).status_code == 303
    with sessions() as session:
        csrf = session.query(UserSession).one().csrf_token
    url = f"/api/catalog/assets/{ASSET}/selection"
    headers = {"X-CSRF-Token": csrf, "Origin": "https://testserver"}
    assert client.get(f"/api/catalog/assets/{ASSET}").json()["selected"] is False
    assert client.put(url, json={"selected": True}).status_code == 403
    for _ in range(2):
        response = client.put(url, json={"selected": True}, headers=headers)
        assert response.status_code == 200
        assert response.json()["selected"] is True
        assert response.json()["selected_count"] == 1
    assert client.get(f"/api/catalog/assets/{ASSET}").json()["selected"] is True
    assert "1 selecionado" in client.get("/gallery/viagem").text
    assert "Selecionado" in client.get(f"/gallery/viagem/assets/{ASSET}").text
    assert (
        client.post("/logout", headers=headers, follow_redirects=False).status_code
        == 303
    )
    assert login(client).status_code == 303
    assert client.get(f"/api/catalog/assets/{ASSET}").json()["selected"] is True
    with sessions() as session:
        csrf = (
            session.query(UserSession).order_by(UserSession.created_at.desc()).first()
        )
        assert csrf is not None
        new_token = csrf.csrf_token
    response = client.put(
        url, json={"selected": False}, headers={"X-CSRF-Token": new_token}
    )
    assert response.status_code == 200
    assert response.json()["selected_count"] == 0
    response = client.put(
        url, json={"selected": False}, headers={"X-CSRF-Token": new_token}
    )
    assert response.status_code == 200
    assert response.json()["selected_count"] == 0


def test_gallery_selection_keeps_post_fallback_and_exposes_progressive_controls(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = auth_app
    assert login(client).status_code == 303
    page = client.get("/gallery/viagem")
    assert 'method="post"' in page.text
    assert f'data-asset-id="{ASSET}"' in page.text
    assert "data-selection-count" in page.text
    assert "data-download-panel" in page.text
    assert "X-CSRF-Token" in page.text


def test_bulk_selection_is_atomic_idempotent_and_keeps_hidden_assets(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = auth_app
    assert login(client).status_code == 303
    ids = [f"{number:064x}" for number in range(1, 101)]
    foreign_id = "f" * 64
    with sessions() as session:
        trip = session.query(Trip).filter_by(slug="viagem").one()
        other = Trip(name="Outra", slug="outra", nas_rel_path="outra")
        session.add(other)
        session.flush()
        session.add_all(
            CatalogAsset(
                asset_id=asset_id,
                trip_id=trip.id,
                media_type="PHOTO",
                classification="FOTOS",
                verification_status="VERIFIED",
            )
            for asset_id in ids
        )
        session.add(
            CatalogAsset(
                asset_id=foreign_id,
                trip_id=other.id,
                media_type="PHOTO",
                classification="FOTOS",
                verification_status="VERIFIED",
            )
        )
        session.commit()
        csrf = session.query(UserSession).one().csrf_token
    url = "/api/catalog/trips/viagem/selection"
    headers = {"X-CSRF-Token": csrf}
    body = {"asset_ids": ids, "selected": True}
    assert client.put(url, json=body).status_code == 403
    for _ in range(2):
        response = client.put(url, json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["selected_count"] == 100
    for bad in (foreign_id, "e" * 64):
        response = client.put(
            url, json={"asset_ids": [ASSET, bad], "selected": True}, headers=headers
        )
        assert response.status_code == 404
        assert client.get(f"/api/catalog/assets/{ASSET}").json()["selected"] is False
    assert (
        client.put(
            url, json={"asset_ids": ids + ids[:1], "selected": True}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.put(
            url, json={"asset_ids": [], "selected": True}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.put(
            url, json={"asset_ids": ["x"] * 2001, "selected": True}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.put(
            url, json={"asset_ids": ids[:20], "selected": False}, headers=headers
        ).json()["selected_count"]
        == 80
    )
    assert client.get(f"/api/catalog/assets/{ids[20]}").json()["selected"] is True
    page = client.get("/gallery/viagem", params={"media_type": "VIDEO"})
    assert "data-bulk-selection" in page.text
    with sessions() as session:
        session.add(
            User(
                username="viewer", password_hash=hash_password("another password here")
            )
        )
        session.commit()
    with TestClient(client.app, base_url="https://testserver") as viewer:
        login_page = viewer.get("/login")
        match = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
        assert match is not None
        assert (
            viewer.post(
                "/login",
                data={
                    "username": "viewer",
                    "password": "another password here",
                    "csrf_token": match[1],
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        with sessions() as session:
            other_csrf = (
                session.query(UserSession)
                .order_by(UserSession.created_at.desc())
                .first()
            )
            assert other_csrf is not None
        response = viewer.put(
            url,
            json={"asset_ids": ids[:1], "selected": True},
            headers={"X-CSRF-Token": other_csrf.csrf_token},
        )
        assert response.status_code == 200
        assert response.json()["selected_count"] == 1
    assert "80 selecionados" in client.get("/gallery/viagem").text


def test_selection_is_private_to_user_and_gallery_form_checks_csrf(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = auth_app
    assert login(client).status_code == 303
    with sessions() as session:
        csrf = session.query(UserSession).one().csrf_token
        session.add(
            User(
                username="viewer", password_hash=hash_password("another password here")
            )
        )
        session.commit()
    form_url = f"/gallery/viagem/assets/{ASSET}/selection"
    assert client.post(form_url, data={"selected": "true"}).status_code == 403
    selected = client.post(
        form_url,
        data={"selected": "true", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert selected.status_code == 303
    assert "Selecionado" in client.get("/gallery/viagem").text
    with TestClient(client.app, base_url="https://testserver") as other:
        page = other.get("/login")
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match is not None
        assert (
            other.post(
                "/login",
                data={
                    "username": "viewer",
                    "password": "another password here",
                    "csrf_token": match[1],
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert other.get(f"/api/catalog/assets/{ASSET}").json()["selected"] is False
        assert "0 selecionados" in other.get("/gallery/viagem").text


def test_gallery_has_working_logout_form(
    auth_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = auth_app
    assert login(client).status_code == 303
    page = client.get("/gallery")
    assert 'action="/logout"' in page.text
    with sessions() as session:
        csrf = session.query(UserSession).one().csrf_token
    response = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/api/catalog/trips").status_code == 401
