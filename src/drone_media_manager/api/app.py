"""FastAPI application factory with bounded request parsing."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from drone_media_manager.api.auth import auth_router, browser_gate
from drone_media_manager.api.gallery import gallery_router
from drone_media_manager.api.routes.catalog import catalog_router
from drone_media_manager.api.routes.health import health_router
from drone_media_manager.api.routes.ingests import ingest_router
from drone_media_manager.api.routes.jobs import job_router
from drone_media_manager.api.routes.sources import source_router
from drone_media_manager.api.routes.workers import worker_router
from drone_media_manager.config import ServerSettings
from drone_media_manager.jobs.recovery import recover_on_startup
from drone_media_manager.logging import configure_logging
from drone_media_manager.time import utc_now

MAX_REQUEST_BODY_BYTES = 1024 * 1024


class BoundedBodyMiddleware:
    """Read at most the configured body size before invoking route parsing."""

    def __init__(self, app: ASGIApp, limit: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.limit:
                await self._reject(send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"error": {"code": "request_body_too_large"}},
        )
        await response({"type": "http"}, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def create_app(settings: ServerSettings, sessions: sessionmaker[Session]) -> FastAPI:
    app = FastAPI()
    configure_logging()

    @app.on_event("startup")
    async def recover_expired_jobs() -> None:
        recover_on_startup(sessions, utc_now())

    @app.exception_handler(HTTPException)
    async def stable_http_error(_: Request, error: HTTPException) -> JSONResponse:
        detail = (
            error.detail
            if isinstance(error.detail, dict)
            else {"code": "request_error"}
        )
        return JSONResponse(status_code=error.status_code, content={"error": detail})

    @app.exception_handler(RequestValidationError)
    async def stable_validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = []
        for item in error.errors():
            errors.append(
                {
                    "type": item.get("type"),
                    "loc": list(item.get("loc", ())),
                    "msg": item.get("msg"),
                }
            )
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "details": errors}},
        )

    app.include_router(auth_router(sessions))
    app.include_router(worker_router(settings, sessions))
    app.include_router(job_router(sessions))
    app.include_router(source_router(sessions))
    app.include_router(ingest_router(settings, sessions))
    app.include_router(health_router(settings, sessions))
    app.include_router(catalog_router(settings, sessions))
    app.include_router(gallery_router(settings, sessions))
    @app.middleware("http")
    async def protect_browser_routes(request: Request, call_next: Any) -> Response:
        return await browser_gate(request, call_next, sessions)

    app.add_middleware(BoundedBodyMiddleware)
    return app
