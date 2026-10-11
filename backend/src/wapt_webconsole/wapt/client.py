"""Long-lived client for the WAPT server REST API (``api/v3``).

One session per backend, authenticated with the WAPT service account (``admin`` on Discovery). The session
cookie is renewed transparently: on a 401 the client logs in again once and replays the request.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2 as httpx

from .. import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"wapt-webconsole/{__version__}"


class WaptError(RuntimeError):
    """The WAPT server refused the request or answered ``success: false``."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class WaptClient:
    def __init__(self, url: str, user: str, password: str, *, verify: bool = True, timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = url.rstrip("/")
        self.user = user
        self._password = password
        self._http = httpx.AsyncClient(base_url=self.url, verify=verify, timeout=timeout, transport=transport,
                                       headers={"User-Agent": USER_AGENT})
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    async def close(self) -> None:
        if self._logged_in:
            try:
                await self._http.post("api/v3/logout")
            except httpx.HTTPError:
                pass
        await self._http.aclose()

    async def login(self) -> None:
        resp = await self._http.post("api/v3/login", json={"user": self.user, "password": self._password})
        if resp.status_code == 401 and "Missing TOTP" in resp.text:
            raise WaptError(f"the WAPT account {self.user!r} requires a TOTP code: use an account without MFA", 401)
        payload = _json(resp)
        if resp.status_code != 200 or not payload.get("success"):
            raise WaptError(f"login failed for {self.user!r} (HTTP {resp.status_code})", resp.status_code)
        self._logged_in = True
        log.info("Logged in to %s as %s", self.url, self.user)

    async def _ensure_login(self, stale: bool = False) -> None:
        async with self._login_lock:
            if stale or not self._logged_in:
                self._logged_in = False
                await self.login()

    async def call(self, method: str, path: str, **kwargs) -> Any:
        """``result`` of an API call; raises ``WaptError`` unless the answer is HTTP 200 with ``success: true``."""
        return (await self.call_raw(method, path, **kwargs)).get("result")

    async def call_raw(self, method: str, path: str, **kwargs) -> dict:
        """Whole answer (``result``, ``msg``...) of an API call, with the same checks as ``call``."""
        await self._ensure_login()
        resp = await self._http.request(method, path, **kwargs)
        if resp.status_code == 401:
            await self._ensure_login(stale=True)
            resp = await self._http.request(method, path, **kwargs)
        payload = _json(resp)
        if resp.status_code != 200 or not payload.get("success", False):
            raise WaptError(f"{path}: {payload.get('msg') or f'HTTP {resp.status_code}'}", resp.status_code)
        return payload

    async def fetch(self, url: str, **kwargs) -> httpx.Response:
        """Unauthenticated GET of a public file (repository icons, store index), with the client TLS settings."""
        return await self._http.get(url, **kwargs)

    async def download(self, url: str, target: Path, size: int | None = None, md5: str = "",
                       on_progress: Callable[[int], None] | None = None) -> None:
        """Stream a public file to ``target``; its size and MD5 are checked when given."""
        digest = hashlib.md5(usedforsecurity=False)
        done = 0
        async with self._http.stream("GET", url, timeout=httpx.Timeout(60, read=300)) as resp:
            if resp.status_code != 200:
                raise WaptError(f"{url}: HTTP {resp.status_code}", resp.status_code)
            with target.open("wb") as out:
                async for chunk in resp.aiter_bytes(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done)
        if size and done != size:
            raise WaptError(f"{url}: {done} bytes received, {size} expected")
        if md5 and digest.hexdigest() != md5.lower():
            raise WaptError(f"{url}: MD5 mismatch")

    # --- read-only API ---------------------------------------------------------------------------------------

    async def ping(self) -> dict:
        resp = await self._http.get("api/v3/ping")
        return _json(resp).get("result") or {}

    async def hosts(self, columns: list[str], **filters) -> list[dict]:
        params = {"columns": ",".join(columns), "limit": 100000, **filters}
        return await self.call("GET", "api/v3/hosts", params=params) or []


def _json(resp: httpx.Response) -> dict:
    try:
        payload = resp.json()
    except ValueError as e:
        raise WaptError(f"{resp.request.url.path}: HTTP {resp.status_code}, non-JSON answer", resp.status_code) from e
    if not isinstance(payload, dict):
        raise WaptError(f"{resp.request.url.path}: unexpected answer", resp.status_code)
    return payload
