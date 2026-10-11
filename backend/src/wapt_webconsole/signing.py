"""Signature of the agent actions and packages, through ``signer.py`` run by ``waptpython``.

Each operator unlocks signing for their own session. The key is either brought by the user (encrypted PEM file
chosen in the browser, with its certificate) or, when the installation provides one, the server's key file; in both
cases the passphrase is typed by the user, checked by WAPT itself, then forgotten by the backend.

Each unlocked session gets its own ``signer.py serve`` process holding its decrypted key in memory only: nothing
brought by the user is written to disk. When the unlock expires or is released, the process is ended and the key is
gone from memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MAX_PEM = 64 * 1024


class SigningError(RuntimeError):
    pass


class KeyLocked(SigningError):
    """No unlock for this session: the user must bring the key or type the passphrase."""


@dataclass
class SignerConfig:
    waptpython: str
    script: str
    certificate: str = ""            # optional key stored on the server (file paths)
    private_key: str = ""

    @property
    def configured(self) -> bool:
        """A key is stored on the server: users may unlock it with the passphrase only."""
        return bool(self.certificate and self.private_key) and Path(self.certificate).exists() \
            and Path(self.private_key).exists()


@dataclass
class _Session:
    proc: asyncio.subprocess.Process
    expiry: float                                  # monotonic clock
    identity: dict = field(default_factory=dict)   # cn and fingerprint of the certificate
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def check_pem(key_pem: str, certificate_pem: str) -> None:
    if len(key_pem) > MAX_PEM or len(certificate_pem) > MAX_PEM:
        raise SigningError("fichier trop volumineux")
    if "PRIVATE KEY-----" not in key_pem:
        raise SigningError("aucune clé privée PEM dans le fichier")
    if "ENCRYPTED" not in key_pem:
        raise SigningError("la clé privée doit être protégée par une passphrase")
    if "BEGIN CERTIFICATE-----" not in certificate_pem:
        raise SigningError("aucun certificat PEM : joindre le .crt de la clé")


class Signer:
    def __init__(self, config: SignerConfig, ttl: float = 1800, timeout: float = 60):
        self.config = config
        self.ttl = ttl
        self.timeout = timeout
        self.sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()
        self._next_id = 0

    # --- unlock state per session ------------------------------------------------------------------------------

    def expires_in(self, session: str) -> float:
        s = self.sessions.get(session)
        return max(0.0, s.expiry - time.monotonic()) if s else 0.0

    def identity(self, session: str) -> dict:
        s = self.sessions.get(session)
        return s.identity if s and self.expires_in(session) > 0 else {}

    async def unlock(self, session: str, passphrase: str, key_pem: str = "", certificate_pem: str = "") -> dict:
        """Start the signer of this session; returns the certificate identity (cn, fingerprint)."""
        if key_pem:
            check_pem(key_pem, certificate_pem)
            material = {"private_key_pem": key_pem, "certificate_pem": certificate_pem}
        elif self.config.configured:
            material = {"private_key": self.config.private_key, "certificate": self.config.certificate}
        else:
            raise SigningError("choisissez le fichier de votre clé privée et son certificat")
        async with self._lock:
            await self._expire()
            await self._stop(session)
            proc = await asyncio.create_subprocess_exec(
                self.config.waptpython, self.config.script, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            proc.stdin.write((json.dumps({"op": "serve", "password": passphrase, **material}) + "\n").encode())
            await proc.stdin.drain()
            ready = await self._read(proc)
            if not ready.get("ready"):
                await _end(proc)
                raise SigningError(_passphrase_error(ready))
            identity = {"cn": ready.get("cn"), "fingerprint": ready.get("fingerprint")}
            self.sessions[session] = _Session(proc, time.monotonic() + self.ttl, identity)
        log.info("Signing unlocked for session %s… with %s (%d active)", session[:6], identity["cn"],
                 len(self.sessions))
        return identity

    async def lock(self, session: str) -> None:
        async with self._lock:
            await self._stop(session)
            await self._expire()

    # --- signature -------------------------------------------------------------------------------------------

    async def sign(self, session: str, actions: list[dict]) -> list[dict]:
        """Signed copies of ``actions``; raises ``KeyLocked`` without a valid unlock for this session."""
        results = await self._call(session, {"op": "sign_actions", "actions": actions})
        failed = [r for r in results if not r.get("ok")]
        if failed:
            raise SigningError(f"signature refused: {failed[0].get('error')}")
        return [r["action"] for r in results]

    async def build(self, session: str, jobs: list[dict], output_dir: str) -> list[dict]:
        """Host or group packages built from their control attributes and signed, written to ``output_dir``:
        one result per job, ``{"ok": true, "path": ..., "version": ...}`` or ``{"ok": false, "error": ...}``."""
        return await self._call(session, {"op": "build_packages", "jobs": jobs, "output_dir": output_dir})

    async def import_package(self, session: str, source: str, output_dir: str, prefix: str,
                             trusted_certs_pem: list[str], timeout: float = 1800) -> dict:
        """Store package checked against ``trusted_certs_pem``, renamed to ``prefix`` and signed with the session key.
        Large packages take minutes to check, hence the long timeout."""
        [result] = await self._call(session, {"op": "import_package", "source": source, "output_dir": output_dir,
                                              "prefix": prefix, "trusted_certs_pem": trusted_certs_pem,
                                              "verify": "full"}, timeout=timeout)
        return result

    async def close(self) -> None:
        async with self._lock:
            for session in list(self.sessions):
                await self._stop(session)

    # --- signer processes -------------------------------------------------------------------------------------

    async def _call(self, session: str, request: dict, timeout: float | None = None) -> list[dict]:
        async with self._lock:
            await self._expire()
            s = self.sessions.get(session)
            if s is None:
                raise KeyLocked("signing key locked")
            self._next_id += 1
            request = {"id": self._next_id, **request}
        async with s.lock:                               # one request at a time per signer process
            s.proc.stdin.write((json.dumps(request) + "\n").encode())
            await s.proc.stdin.drain()
            try:
                answer = await self._read(s.proc, timeout)
            except SigningError:
                async with self._lock:
                    await self._stop(session)
                raise
        if answer.get("error"):
            raise SigningError(answer["error"])
        return answer["results"]

    async def _read(self, proc: asyncio.subprocess.Process, timeout: float | None = None) -> dict:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout or self.timeout)
        except TimeoutError as e:
            raise SigningError("the signer did not answer") from e
        if not line:
            raise SigningError("the signer stopped")
        return json.loads(line)

    async def _expire(self) -> None:
        now = time.monotonic()
        for session, s in list(self.sessions.items()):
            if s.expiry <= now:
                await self._stop(session)

    async def _stop(self, session: str) -> None:
        s = self.sessions.pop(session, None)
        if s is not None:
            await _end(s.proc)
            log.info("Signer of session %s… stopped: key removed from memory", session[:6])


async def _end(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(Exception):
        proc.stdin.close()
        await asyncio.wait_for(proc.wait(), 5)
    if proc.returncode is None:
        proc.kill()


def _passphrase_error(answer: dict) -> str:
    error = str(answer.get("error") or "unknown error")
    lowered = error.lower()
    if any(k in lowered for k in ("password", "decrypt", "passphrase")):
        return "wrong passphrase"
    if "does not match" in lowered:
        return "la clé ne correspond pas au certificat"
    return error
