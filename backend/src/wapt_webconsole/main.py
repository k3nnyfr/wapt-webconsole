"""FastAPI application: authentication, WAPT client and API routes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, auth
from .auth import User, require
from .config import Settings
from .wapt.client import WaptClient, WaptError

log = logging.getLogger(__name__)

HOST_COLUMNS = ["uuid", "computer_fqdn", "computer_name", "description", "os_name", "os_version", "reachable",
                "host_status", "last_seen_on", "wapt_version", "connected_users"]


def create_app(settings: Settings | None = None, wapt: WaptClient | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.wapt = wapt or WaptClient(settings.wapt_url, settings.wapt_user, settings.wapt_password,
                                            verify=settings.wapt_verify_tls, timeout=settings.wapt_timeout)
        try:
            yield
        finally:
            await app.state.wapt.close()

    app = FastAPI(title="wapt-webconsole", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.oauth = auth.make_oauth(settings)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, session_cookie="wwc_session",
                       max_age=settings.session_max_age, same_site="lax", https_only=settings.https)
    app.include_router(auth.router)

    @app.get("/api/health", tags=["system"])
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/me", tags=["system"])
    async def me(request: Request, user: Annotated[User, Depends(require("viewer"))]):
        return {"user": user, "csrf": request.session.get("csrf"), "wapt_url": settings.wapt_url}

    @app.get("/api/wapt/status", tags=["system"])
    async def wapt_status(request: Request, user: Annotated[User, Depends(require("viewer"))]):
        client: WaptClient = request.app.state.wapt
        try:
            hosts = await client.hosts(["uuid", "reachable"])
        except WaptError as e:
            raise HTTPException(502, f"WAPT server: {e}") from e
        return {"url": client.url, "hosts": len(hosts), "connected": sum(h.get("reachable") == "OK" for h in hosts)}

    @app.get("/api/hosts", tags=["hosts"])
    async def hosts(request: Request, user: Annotated[User, Depends(require("viewer"))]):
        try:
            return await request.app.state.wapt.hosts(HOST_COLUMNS)
        except WaptError as e:
            raise HTTPException(502, f"WAPT server: {e}") from e

    return app


def app() -> FastAPI:
    """Factory for ``uvicorn --factory wapt_webconsole.main:app``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
