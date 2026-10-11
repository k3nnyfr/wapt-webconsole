"""FastAPI application: authentication, WAPT client and API routes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response, WebSocket, WebSocketDisconnect
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, auth, operations, store_api
from .auth import User, require
from .config import Settings, role_at_least
from .jobs import Jobs
from .journal import Journal
from .live import LiveHub
from .signing import Signer, SignerConfig
from .store import StoreIndex
from .wapt import details, repository
from .wapt.client import WaptClient, WaptError
from .wapt.hosts import Inventory

log = logging.getLogger(__name__)

# WAPT host uuids: SMBIOS uuids, or generated ones; letters, digits and dashes only
HostUuid = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,64}$")]
PackageName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+~-]{0,199}$")]
IconHash = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
ICON_CACHE_SIZE = 500


def create_app(settings: Settings | None = None, wapt: WaptClient | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.wapt = wapt or WaptClient(settings.wapt_url, settings.wapt_user, settings.wapt_password,
                                            verify=settings.wapt_verify_tls, timeout=settings.wapt_timeout)
        app.state.inventory = Inventory(app.state.wapt)
        app.state.live = LiveHub(app.state.inventory, settings.live_interval, settings.session_max_age)
        app.state.icons = {}
        app.state.journal = Journal(settings.data_dir / "journal.sqlite", settings.journal_retention_days)
        app.state.signer = Signer(SignerConfig(
            waptpython=settings.waptpython, script=settings.signer_script,
            certificate=str(settings.signer_certificate_file or ""), private_key=str(settings.signer_key_file or "")),
            ttl=settings.signer_unlock_minutes * 60)
        app.state.store_index = StoreIndex(settings.store_url.rstrip("/"), settings.data_dir / "cache" / "store",
                                           settings.store_trusted_fingerprints)
        app.state.jobs = Jobs()
        try:
            yield
        finally:
            await app.state.jobs.close()
            await app.state.signer.close()
            await app.state.live.close()
            await app.state.wapt.close()

    app = FastAPI(title="wapt-webconsole", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.oauth = auth.make_oauth(settings)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, session_cookie="wwc_session",
                       max_age=settings.session_max_age, same_site="lax", https_only=settings.https)
    app.include_router(auth.router)
    app.include_router(operations.router)
    app.include_router(store_api.router)

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

    @app.get("/api/packages", tags=["repository"])
    async def packages(request: Request, user: Annotated[User, Depends(require("viewer"))], kind: str = "package"):
        """Newest version of each repository package (``kind=package``) or group (``kind=group``)."""
        if kind not in repository.SECTIONS:
            raise HTTPException(422, "kind must be package or group")
        return await wapt_call(repository.packages(request.app.state.wapt, kind))

    @app.get("/api/packages/{name}", tags=["repository"])
    async def package(request: Request, name: PackageName, user: Annotated[User, Depends(require("viewer"))]):
        """Versions of a package or group and the hosts where it is installed."""
        detail = await wapt_call(repository.package_detail(request.app.state.wapt, name))
        if detail is None:
            raise HTTPException(404, "unknown package")
        return detail

    @app.get("/api/icons/{sha256}.png", tags=["repository"])
    async def icon(request: Request, sha256: IconHash, user: Annotated[User, Depends(require("viewer"))],
                   source: str = "repo"):
        """Package icon from the repository (or the store), by content hash: cacheable forever."""
        cache: dict[str, bytes] = request.app.state.icons
        if sha256 not in cache:
            base = settings.store_url.rstrip("/") if source == "store" else settings.repo_url
            try:
                resp = await request.app.state.wapt.fetch(f"{base}/icons/{sha256}.png")
            except Exception as e:
                raise HTTPException(502, "repository unreachable") from e
            if resp.status_code != 200 or not resp.content.startswith(b"\x89PNG"):
                raise HTTPException(404, "no icon")
            if len(cache) >= ICON_CACHE_SIZE:
                cache.pop(next(iter(cache)))
            cache[sha256] = resp.content
        return Response(cache[sha256], media_type="image/png",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.websocket("/api/ws")
    async def live(ws: WebSocket):
        """Live host status: a snapshot, then the changed hosts (see ``live.LiveHub``)."""
        public = urlsplit(settings.public_url)
        origin = urlsplit(ws.headers.get("origin", ""))
        if (origin.scheme, origin.netloc) != (public.scheme, public.netloc):   # cross-site WebSocket hijacking
            await ws.close(code=4403)
            return
        data = ws.session.get("user")
        user = User(**data) if data else None
        if user is None or not role_at_least(user.role, "viewer"):
            await ws.close(code=4401)
            return
        await ws.accept()
        hub: LiveHub = ws.app.state.live
        try:
            await hub.join(ws, user.login_at)
            while True:
                await ws.receive_text()          # nothing expected from the browser; keeps the connection open
        except (WebSocketDisconnect, WaptError):
            pass
        finally:
            hub.leave(ws)

    return app


def app() -> FastAPI:
    """Factory for ``uvicorn --factory wapt_webconsole.main:app``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
