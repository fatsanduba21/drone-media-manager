"""HTTPS-only end-user login and revocable cookie sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.auth.passwords import hash_password, verify_password
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.time import utc_now

SESSION_COOKIE = "__Host-dmm_session"
LOGIN_CSRF_COOKIE = "__Host-dmm_login_csrf"
SESSION_SECONDS = 12 * 60 * 60
_DUMMY_HASH = hash_password("unused-dummy-password")


@dataclass(frozen=True)
class BrowserIdentity:
    user_id: str
    csrf_token: str
    token_digest: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def browser_identity(
    request: Request, session_factory: Callable[[], Session]
) -> BrowserIdentity | None:
    """Resolve a cookie through an unexpired and unrevoked database session."""
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 128:
        return None
    digest = _token_digest(token)
    with session_factory() as session:
        record = session.get(UserSession, digest)
        if (
            record is None
            or record.revoked_at is not None
            or _utc(record.expires_at) <= utc_now()
            or session.get(User, record.user_id) is None
        ):
            return None
        return BrowserIdentity(record.user_id, record.csrf_token, digest)


def require_browser_identity(request: Request) -> BrowserIdentity:
    identity = getattr(request.state, "browser_identity", None)
    if not isinstance(identity, BrowserIdentity):
        raise HTTPException(status_code=401, detail={"code": "login_required"})
    return identity


def require_csrf(request: Request, supplied: str | None) -> BrowserIdentity:
    identity = require_browser_identity(request)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail={"code": "csrf_invalid"})
    if not supplied or not hmac.compare_digest(identity.csrf_token, supplied):
        raise HTTPException(status_code=403, detail={"code": "csrf_invalid"})
    return identity


def _require_https(request: Request) -> None:
    if request.url.scheme != "https":
        raise HTTPException(status_code=426, detail={"code": "https_required"})


async def _form_fields(request: Request) -> dict[str, str]:
    if not request.headers.get("content-type", "").startswith(
        "application/x-www-form-urlencoded"
    ):
        raise HTTPException(status_code=415, detail={"code": "form_required"})
    try:
        parsed = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=8,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail={"code": "invalid_form"}) from error
    return {key: values[0] for key, values in parsed.items() if values}


class LoginThrottle:
    """Bound failed attempts per source IP and username for this server process."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _keys(self, ip: str, username: str) -> tuple[str, str]:
        return f"ip:{ip}", f"user:{ip}:{username}"

    def allowed(self, ip: str, username: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for key in self._keys(ip, username):
                self._failures[key] = [
                    stamp for stamp in self._failures.get(key, []) if now - stamp < 900
                ]
                if len(self._failures[key]) >= 5:
                    return False
        return True

    def failure(self, ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in self._keys(ip, username):
                self._failures.setdefault(key, []).append(now)

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop(f"user:{ip}:{username}", None)
            self._failures.pop(f"ip:{ip}", None)


def auth_router(session_factory: Callable[[], Session]) -> APIRouter:
    router = APIRouter()
    throttle = LoginThrottle()

    @router.get("/login", response_model=None)
    def login_page(request: Request) -> Response:
        _require_https(request)
        token = secrets.token_urlsafe(32)
        page = (
            '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Entrar · Atlas de voo</title></head><body><main>"
            '<h1>Entrar no Atlas de voo</h1><form method="post" action="/login">'
            '<label>Usuário<input name="username" autocomplete="username" required></label>'
            '<label>Senha<input name="password" type="password" autocomplete="current-password" required></label>'
            f'<input type="hidden" name="csrf_token" value="{escape(token, quote=True)}">'
            '<button type="submit">Entrar</button></form></main></body></html>'
        )
        response = HTMLResponse(page, headers={"Cache-Control": "no-store"})
        response.set_cookie(
            LOGIN_CSRF_COOKIE,
            token,
            max_age=600,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    @router.post("/login", response_model=None)
    async def login(request: Request) -> Response:
        _require_https(request)
        fields = await _form_fields(request)
        csrf = fields.get("csrf_token", "")
        cookie_csrf = request.cookies.get(LOGIN_CSRF_COOKIE, "")
        origin = request.headers.get("origin")
        if (
            not csrf
            or not cookie_csrf
            or not hmac.compare_digest(csrf, cookie_csrf)
            or (origin and origin != str(request.base_url).rstrip("/"))
        ):
            raise HTTPException(status_code=403, detail={"code": "csrf_invalid"})
        username = fields.get("username", "").strip().casefold()
        password = fields.get("password", "")
        if not username or len(username) > 255 or not password or len(password) > 1024:
            raise HTTPException(status_code=401, detail={"code": "invalid_credentials"})
        ip = request.client.host if request.client else "unknown"
        if not throttle.allowed(ip, username):
            raise HTTPException(status_code=429, detail={"code": "login_rate_limited"})
        with session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            valid = verify_password(
                password, user.password_hash if user is not None else _DUMMY_HASH
            )
            if user is None or not valid:
                throttle.failure(ip, username)
                raise HTTPException(
                    status_code=401, detail={"code": "invalid_credentials"}
                )
            throttle.success(ip, username)
            token = secrets.token_urlsafe(32)
            record = UserSession(
                token_digest=_token_digest(token),
                user_id=user.id,
                csrf_token=secrets.token_urlsafe(32),
                expires_at=utc_now() + timedelta(seconds=SESSION_SECONDS),
            )
            session.add(record)
            session.commit()
        response = RedirectResponse("/gallery", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_SECONDS,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/logout", response_model=None)
    async def logout(request: Request) -> Response:
        _require_https(request)
        identity = browser_identity(request, session_factory)
        if identity is None:
            raise HTTPException(status_code=401, detail={"code": "login_required"})
        request.state.browser_identity = identity
        csrf = request.headers.get("x-csrf-token")
        if csrf is None and request.headers.get("content-type", "").startswith(
            "application/x-www-form-urlencoded"
        ):
            fields = await _form_fields(request)
            csrf = fields.get("csrf_token")
        require_csrf(request, csrf)
        with session_factory() as session:
            record = session.get(UserSession, identity.token_digest)
            if record is not None:
                record.revoked_at = utc_now()
                session.commit()
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(
            SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return router


async def browser_gate(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    session_factory: Callable[[], Session],
) -> Response:
    """Protect all gallery and catalog paths before route or static file handling."""
    path = request.url.path
    if path == "/gallery" or path.startswith(("/gallery/", "/api/catalog/")):
        if request.url.scheme != "https":
            return JSONResponse(
                status_code=426, content={"error": {"code": "https_required"}}
            )
        identity = browser_identity(request, session_factory)
        if identity is None:
            if path.startswith("/gallery"):
                return RedirectResponse("/login", status_code=303)
            return JSONResponse(
                status_code=401, content={"error": {"code": "login_required"}}
            )
        request.state.browser_identity = identity
    result = await call_next(request)
    assert isinstance(result, Response)
    return result
