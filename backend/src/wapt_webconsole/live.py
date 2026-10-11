"""Live host status: the backend polls the WAPT inventory while browsers are connected and pushes the changes.

The WAPT server has no event stream for consoles (its socket.io serves the agents), so one polling loop runs in the
backend, whatever the number of viewers, and only while at least one WebSocket is open. Each browser receives a
snapshot on connection, then only the hosts whose values changed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from fastapi import WebSocket

from .wapt.client import WaptError
from .wapt.hosts import Inventory

log = logging.getLogger(__name__)


class LiveHub:
    def __init__(self, inventory: Inventory, interval: float = 10.0, session_max_age: int = 8 * 3600):
        self.inventory = inventory
        self.interval = interval
        self.session_max_age = session_max_age
        self.clients: dict[WebSocket, float] = {}          # socket -> login time of its user
        self._snapshot: dict[str, dict] = {}
        self._task: asyncio.Task | None = None

    async def join(self, ws: WebSocket, login_at: float) -> None:
        hosts, read_at = await self.inventory.hosts()
        await ws.send_json({"type": "snapshot", "hosts": hosts, "read_at": read_at})
        self.clients[ws] = login_at
        if self._task is None or self._task.done():
            self._snapshot = {h["uuid"]: h for h in hosts}
            self._task = asyncio.create_task(self._loop())

    def leave(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while self.clients:
            await asyncio.sleep(self.interval)
            try:
                hosts, read_at = await self.inventory.hosts(refresh=True)
            except WaptError as e:
                log.warning("Live inventory refresh failed: %s", e)
                continue
            current = {h["uuid"]: h for h in hosts}
            changed = [h for u, h in current.items() if self._snapshot.get(u) != h]
            removed = [u for u in self._snapshot if u not in current]
            self._snapshot = current
            await self._broadcast({"type": "update", "changed": changed, "removed": removed, "read_at": read_at})

    async def _broadcast(self, message: dict) -> None:
        now = time.time()
        for ws, login_at in list(self.clients.items()):
            if now - login_at > self.session_max_age:          # the session expired while the page stayed open
                self.leave(ws)
                with contextlib.suppress(Exception):
                    await ws.close(code=4401, reason="session expired")
                continue
            try:
                await ws.send_json(message)
            except Exception:
                self.leave(ws)
