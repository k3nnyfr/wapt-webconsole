"""Routes that act on the hosts: signing key unlock, remote actions, agent tasks, audit journal."""

from __future__ import annotations

import logging
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from . import actions
from .auth import User, require
from .journal import Journal
from .signing import KeyLocked, Signer, SigningError
from .wapt.client import WaptError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["operations"])

MAX_FAILED_UNLOCKS = 5              # wrong passphrases per session...
FAILED_UNLOCK_WINDOW = 600          # ...within this many seconds
TASK_LOG = 20_000


def session_id(request: Request) -> str:
    if "sid" not in request.session:                 # sessions opened before the signing feature
        request.session["sid"] = secrets.token_urlsafe(16)
    return request.session["sid"]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


async def record(request: Request, user: User, action: str, *, targets=None, params=None, ok=True, detail=""):
    journal: Journal = request.app.state.journal
    await journal.add(user=user.username, role=user.role, ip=client_ip(request), action=action, targets=targets,
                      params=params, ok=ok, detail=detail)


# --- signing key -------------------------------------------------------------------------------------------------

class Unlock(BaseModel):
    passphrase: str = Field(min_length=1, max_length=1024)


@router.get("/signing")
async def signing_status(request: Request, user: Annotated[User, Depends(require("viewer"))]):
    signer: Signer = request.app.state.signer
    remaining = signer.expires_in(session_id(request))
    return {"configured": signer.config.configured, "unlocked": remaining > 0, "expires_in": int(remaining),
            "ttl": int(signer.ttl), "identity": signer.identity}


@router.post("/signing/unlock")
async def signing_unlock(request: Request, body: Unlock, user: Annotated[User, Depends(require("operator"))]):
    signer: Signer = request.app.state.signer
    failures = [t for t in request.session.get("unlock_failures", []) if time.time() - t < FAILED_UNLOCK_WINDOW]
    if len(failures) >= MAX_FAILED_UNLOCKS:
        raise HTTPException(429, "trop d'essais : réessayez dans quelques minutes")
    try:
        await signer.unlock(session_id(request), body.passphrase)
    except SigningError as e:
        request.session["unlock_failures"] = [*failures, time.time()]
        await record(request, user, "unlock", ok=False, detail=str(e))
        raise HTTPException(403 if "passphrase" in str(e) else 503, str(e)) from e
    request.session.pop("unlock_failures", None)
    await record(request, user, "unlock")
    return {"unlocked": True, "expires_in": int(signer.ttl)}


@router.post("/signing/lock")
async def signing_lock(request: Request, user: Annotated[User, Depends(require("operator"))]):
    await request.app.state.signer.lock(session_id(request))
    await record(request, user, "lock")
    return {"unlocked": False}


# --- remote actions ----------------------------------------------------------------------------------------------

@router.post("/actions")
async def run_action(request: Request, body: actions.ActionRequest,
                     user: Annotated[User, Depends(require("operator"))]):
    try:
        kind = actions.check(body, user.role)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    hosts, _ = await request.app.state.inventory.hosts()
    try:
        plan = actions.plan(body, kind, hosts)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    params = {k: v for k, v in (("packages", body.packages), ("description", body.description),
                                ("force", body.force)) if v}
    try:
        signed = await request.app.state.signer.sign(session_id(request), plan.actions) if plan.actions else []
        message = await actions.send(request.app.state.wapt, plan, signed)
    except KeyLocked as e:
        raise HTTPException(423, "clé de signature verrouillée") from e
    except (SigningError, WaptError) as e:
        await record(request, user, body.action, targets=plan.reached + plan.skipped, params=params, ok=False,
                     detail=str(e))
        raise HTTPException(502, str(e)) from e
    await record(request, user, body.action, targets=plan.reached, params=params,
                 detail=message + (f" ; non joignables : {len(plan.skipped)}" if plan.skipped else ""))
    return {"action": body.action, "label": kind.label, "message": message,
            "reached": plan.reached, "skipped": plan.skipped}


@router.get("/actions")
async def action_catalog(user: Annotated[User, Depends(require("viewer"))]):
    return {name: {"label": a.label, "role": a.role, "packages": a.packages, "description": a.description,
                   "connected_only": a.connected_only} for name, a in actions.ACTIONS.items()}


# --- agent tasks -------------------------------------------------------------------------------------------------

def _task(t: dict | None) -> dict | None:
    if not t:
        return None
    logs = str(t.get("logs") or "")
    return {"id": t.get("id"), "description": t.get("description") or t.get("classname"),
            "summary": t.get("summary") or "", "progress": t.get("progress"), "runstatus": t.get("runstatus") or "",
            "created": t.get("create_date"), "started": t.get("start_date"), "finished": t.get("finish_date"),
            "created_by": t.get("created_by") or "", "logs": logs[-TASK_LOG:]}


@router.get("/hosts/{uuid}/tasks")
async def host_tasks(request: Request, uuid: Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,64}$")],
                     user: Annotated[User, Depends(require("operator"))]):
    """Tasks of a connected agent; the request is signed (the agent checks it), so the key must be unlocked."""
    try:
        query = (await request.app.state.signer.sign(session_id(request),
                                                     [{"uuid": uuid, "last_event_id": -1, "timeout": 1}]))[0]
        status = await request.app.state.wapt.call("POST", "api/v3/host_tasks_status", json=query, timeout=30) or {}
    except KeyLocked as e:
        raise HTTPException(423, "clé de signature verrouillée") from e
    except (SigningError, WaptError) as e:
        raise HTTPException(502, str(e)) from e
    return {"running": _task(status.get("running")),
            "pending": [_task(t) for t in status.get("pending") or []],
            "done": [_task(t) for t in (status.get("done") or [])[-15:]][::-1],
            "errors": [_task(t) for t in (status.get("errors") or [])[-15:]][::-1],
            "cancelled": [_task(t) for t in (status.get("cancelled") or [])[-5:]][::-1]}


# --- audit journal -----------------------------------------------------------------------------------------------

@router.get("/journal")
async def journal(request: Request, user: Annotated[User, Depends(require("operator"))], limit: int = 100,
                  before: int | None = None, username: str | None = None, host: str | None = None):
    return await request.app.state.journal.list(limit=limit, before=before, user=username, host=host)
