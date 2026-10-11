"""FastAPI application: authentication, WAPT client and API routes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, auth
from .auth import User, require
from .config import Settings
from .wapt import details
from .wapt.client import WaptClient, WaptError
from .wapt.hosts import Inventory

log = logging.getLogger(__name__)

# WAPT host uuids: SMBIOS uuids, or generated ones; letters, digits and dashes only
HostUuid = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,64}$")]


def create_app(settings: Settings | None = None, wapt: WaptClient | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.wapt = wapt or WaptClient(settings.wapt_url, settings.wapt_user, settings.wapt_password,
                                            verify=settings.wapt_verify_tls, timeout=settings.wapt_timeout)
        app.state.inventory = Inventory(app.state.wapt)
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
    async def hosts(request: Request, user: Annotated[User, Depends(require("viewer"))], refresh: bool = False):
        """Flattened inventory (see ``wapt.hosts.flatten``), cached a few seconds."""
        try:
            hosts, read_at = await request.app.state.inventory.hosts(refresh=refresh)
        except WaptError as e:
            raise HTTPException(502, f"WAPT server: {e}") from e
        return {"hosts": hosts, "read_at": read_at, "server": request.app.state.wapt.url}

    async def wapt_call(coro):
        try:
            return await coro
        except WaptError as e:
            raise HTTPException(502, f"WAPT server: {e}") from e

    @app.get("/api/hosts/{uuid}", tags=["hosts"])
    async def host(request: Request, uuid: HostUuid, user: Annotated[User, Depends(require("viewer"))]):
        """Summary, hardware and host package of one host."""
        detail = await wapt_call(details.host_detail(request.app.state.wapt, uuid))
        if detail is None:
            raise HTTPException(404, "unknown host")
        return detail

    @app.get("/api/hosts/{uuid}/packages", tags=["hosts"])
    async def host_packages(request: Request, uuid: HostUuid, user: Annotated[User, Depends(require("viewer"))]):
        """WAPT packages of the host: status, install and audit logs."""
        return await wapt_call(details.host_packages(request.app.state.wapt, uuid))

    @app.get("/api/hosts/{uuid}/softwares", tags=["hosts"])
    async def host_softwares(request: Request, uuid: HostUuid, user: Annotated[User, Depends(require("viewer"))]):
        """Software installed on the host, inside or outside WAPT."""
        return await wapt_call(details.host_softwares(request.app.state.wapt, uuid))

    return app


def app() -> FastAPI:
    """Factory for ``uvicorn --factory wapt_webconsole.main:app``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
