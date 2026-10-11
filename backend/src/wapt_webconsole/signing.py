"""Signature of the agent actions with the user's key, through ``signer.py`` run by ``waptpython``.

Each operator unlocks the key for their own session by typing its passphrase (``unlock``): the passphrase is checked
by WAPT itself, then forgotten by the backend. While at least one session holds an unexpired unlock, a single
``signer.py serve`` process keeps the decrypted key in its memory and signs on demand; when the last unlock expires
or is released, the process is ended and the key is gone from memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class SigningError(RuntimeError):
    pass


class KeyLocked(SigningError):
    """No unlock for this session: the user must type the passphrase."""


@dataclass
class SignerConfig:
    waptpython: str
    script: str
    certificate: str
    private_key: str

    @property
    def configured(self) -> bool:
        return bool(self.certificate and self.private_key) and Path(self.certificate).exists() \
            and Path(self.private_key).exists()


class Signer:
    def __init__(self, config: SignerConfig, ttl: float = 1800, timeout: float = 60):
        self.config = config
        self.ttl = ttl
        self.timeout = timeout
        self.unlocks: dict[str, float] = {}          # session id -> expiry (monotonic clock)
        self.identity: dict = {}                     # cn and fingerprint of the signer certificate
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0

    # --- unlock state per session ------------------------------------------------------------------------------

    def expires_in(self, session: str) -> float:
        remaining = self.unlocks.get(session, 0) - time.monotonic()
        return max(0.0, remaining)

    async def unlock(self, session: str, passphrase: str) -> None:
        if not self.config.configured:
            raise SigningError("no signing certificate and key configured (WWC_SIGNER_*)")
        async with self._lock:
            await self._expire()
            if self._proc is None:
                await self._start(passphrase)          # a wrong passphrase fails here
            else:
                await self._check(passphrase)          # the process is shared: check this user's passphrase too
            self.unlocks[session] = time.monotonic() + self.ttl
        log.info("Signing key unlocked for session %s… (%d active)", session[:6], len(self.unlocks))

    async def lock(self, session: str) -> None:
        async with self._lock:
            self.unlocks.pop(session, None)
            await self._expire()

    # --- signature -------------------------------------------------------------------------------------------

    async def sign(self, session: str, actions: list[dict]) -> list[dict]:
        """Signed copies of ``actions``; raises ``KeyLocked`` without a valid unlock for this session."""
        async with self._lock:
            await self._expire()
            if self.expires_in(session) <= 0 or self._proc is None:
                raise KeyLocked("signing key locked")
            self._next_id += 1
            request = {"id": self._next_id, "op": "sign_actions", "actions": actions}
            self._proc.stdin.write((json.dumps(request) + "\n").encode())
            await self._proc.stdin.drain()
            answer = await self._read_line()
        if answer.get("error"):
            raise SigningError(answer["error"])
        failed = [r for r in answer["results"] if not r.get("ok")]
        if failed:
            raise SigningError(f"signature refused: {failed[0].get('error')}")
        return [r["action"] for r in answer["results"]]

    async def close(self) -> None:
        async with self._lock:
            self.unlocks.clear()
            await self._stop()

    # --- signer process ------------------------------------------------------------------------------------------

    def _request(self, op: str, passphrase: str) -> bytes:
        return (json.dumps({"op": op, "certificate": self.config.certificate, "private_key": self.config.private_key,
                            "password": passphrase}) + "\n").encode()

    async def _start(self, passphrase: str) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self.config.waptpython, self.config.script, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self._proc.stdin.write(self._request("serve", passphrase))
        await self._proc.stdin.drain()
        ready = await self._read_line()
        if not ready.get("ready"):
            await self._stop()
            raise SigningError(_passphrase_error(ready))
        self.identity = {"cn": ready.get("cn"), "fingerprint": ready.get("fingerprint")}
        log.info("Signer process started (%s)", self.identity.get("cn"))

    async def _check(self, passphrase: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            self.config.waptpython, self.config.script, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(self._request("info", passphrase)), self.timeout)
        answer = json.loads(out.splitlines()[0]) if out.strip() else {}
        if not answer.get("ok"):
            raise SigningError(_passphrase_error(answer))

    async def _read_line(self) -> dict:
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), self.timeout)
        except TimeoutError as e:
            await self._stop()
            raise SigningError("the signer did not answer") from e
        if not line:
            await self._stop()
            raise SigningError("the signer stopped")
        return json.loads(line)

    async def _expire(self) -> None:
        now = time.monotonic()
        for session, expiry in list(self.unlocks.items()):
            if expiry <= now:
                del self.unlocks[session]
        if not self.unlocks and self._proc is not None:
            await self._stop()

    async def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        with contextlib.suppress(Exception):
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(), 5)
        if proc.returncode is None:
            proc.kill()
        log.info("Signer process stopped: key removed from memory")


def _passphrase_error(answer: dict) -> str:
    error = str(answer.get("error") or "unknown error")
    if any(k in error.lower() for k in ("password", "decrypt", "bad decrypt", "passphrase")):
        return "wrong passphrase"
    return error
