"""Routes that act on the hosts: signing key unlock, remote actions, agent tasks, audit journal."""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path as PathlibPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, UploadFile
from pydantic import BaseModel, Field, field_validator

from . import actions, management, repo_admin
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
    identity = request.app.state.signer.identity(session_id(request))
    if identity and action not in ("unlock", "lock"):
        params = {**(params or {}), "signer": identity.get("cn")}      # which certificate signed
    await journal.add(user=user.username, role=user.role, ip=client_ip(request), action=action, targets=targets,
                      params=params, ok=ok, detail=detail)


# --- signing key -------------------------------------------------------------------------------------------------

class Unlock(BaseModel):
    passphrase: str = Field(min_length=1, max_length=1024)
    # key brought by the user (encrypted PEM) and its certificate; kept in the signer process memory only
    key_pem: str = Field(default="", max_length=65536)
    certificate_pem: str = Field(default="", max_length=65536)


@router.get("/signing")
async def signing_status(request: Request, user: Annotated[User, Depends(require("viewer"))]):
    signer: Signer = request.app.state.signer
    sid = session_id(request)
    remaining = signer.expires_in(sid)
    return {"server_key": signer.config.configured, "unlocked": remaining > 0, "expires_in": int(remaining),
            "ttl": int(signer.ttl), "identity": signer.identity(sid)}


@router.post("/signing/unlock")
async def signing_unlock(request: Request, body: Unlock, user: Annotated[User, Depends(require("operator"))]):
    signer: Signer = request.app.state.signer
    failures = [t for t in request.session.get("unlock_failures", []) if time.time() - t < FAILED_UNLOCK_WINDOW]
    if len(failures) >= MAX_FAILED_UNLOCKS:
        raise HTTPException(429, "trop d'essais : réessayez dans quelques minutes")
    try:
        identity = await signer.unlock(session_id(request), body.passphrase, body.key_pem, body.certificate_pem)
    except SigningError as e:
        request.session["unlock_failures"] = [*failures, time.time()]
        await record(request, user, "unlock", ok=False, detail=str(e))
        status = 403 if str(e) == "wrong passphrase" else 503 if "signer" in str(e) else 422
        raise HTTPException(status, str(e)) from e
    request.session.pop("unlock_failures", None)
    source = "clé apportée" if body.key_pem else "clé du serveur"
    await record(request, user, "unlock", params={"signer": identity.get("cn")},
                 detail=f"{source} : {identity.get('cn')} ({str(identity.get('fingerprint'))[:16]}…)")
    return {"unlocked": True, "expires_in": int(signer.ttl), "identity": identity}


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


# --- assignments and groups (host and group packages) ------------------------------------------------------------

class AssignmentRequest(BaseModel):
    hosts: list[str] = Field(min_length=1, max_length=1000)
    add: list[str] = Field(default_factory=list, max_length=100)
    remove: list[str] = Field(default_factory=list, max_length=100)
    expected: dict[str, str | None] = Field(default_factory=dict)     # host uuid -> host package version previewed
    apply_now: bool = False

    @field_validator("hosts")
    @classmethod
    def valid_hosts(cls, v: list[str]) -> list[str]:
        if not all(actions.UUID_RE.fullmatch(u) for u in v):
            raise ValueError("invalid host uuid")
        return list(dict.fromkeys(v))

    @field_validator("add", "remove")
    @classmethod
    def valid_packages(cls, v: list[str]) -> list[str]:
        if not all(actions.PACKAGE_RE.fullmatch(p) for p in v):
            raise ValueError("invalid package name")
        return list(dict.fromkeys(v))


@router.post("/assignments/preview")
async def assignment_preview(request: Request, body: AssignmentRequest,
                             user: Annotated[User, Depends(require("admin"))]):
    """Host packages before and after adding or removing packages and groups; nothing is written."""
    hosts, _ = await request.app.state.inventory.hosts()
    try:
        changes, unknown = await management.plan_assignment(request.app.state.wapt, hosts, body.hosts, body.add,
                                                            body.remove)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except WaptError as e:
        raise HTTPException(502, str(e)) from e
    return {"changes": [c.as_dict() for c in changes], "unknown": unknown}


@router.post("/assignments")
async def assignment_apply(request: Request, body: AssignmentRequest,
                           user: Annotated[User, Depends(require("admin"))]):
    """Publish the host packages (signed with the user's key), then optionally upgrade the connected hosts."""
    hosts, _ = await request.app.state.inventory.hosts()
    params = {"add": body.add, "remove": body.remove, "apply_now": body.apply_now}
    try:
        result = await management.apply_assignment(request.app.state.wapt, request.app.state.signer,
                                                   session_id(request), hosts, body.hosts, body.add, body.remove,
                                                   body.expected)
    except KeyLocked as e:
        raise HTTPException(423, "clé de signature verrouillée") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except (SigningError, WaptError) as e:
        await record(request, user, "assign", targets=[{"uuid": u, "name": u} for u in body.hosts], params=params,
                     ok=False, detail=str(e))
        raise HTTPException(502, str(e)) from e
    targets = [{"uuid": p["uuid"], "name": p["name"]} for p in result["published"]]
    detail = f"publiés : {len(result['published'])}"
    if result["conflicts"]:
        detail += f" ; modifiés entre-temps : {', '.join(c['name'] for c in result['conflicts'])}"
    if result["failed"]:
        detail += f" ; échecs : {', '.join(f['name'] for f in result['failed'])}"
    result["upgrade"] = None
    connected = [p for p in result["published"] if p["connected"]]
    if body.apply_now and connected:
        upgrade = actions.ActionRequest(action="upgrade", hosts=[p["uuid"] for p in connected])
        plan = actions.plan(upgrade, actions.ACTIONS["upgrade"], hosts)
        try:
            signed = await request.app.state.signer.sign(session_id(request), plan.actions)
            result["upgrade"] = await actions.send(request.app.state.wapt, plan, signed)
            detail += f" ; mise à jour lancée : {result['upgrade']}"
        except (SigningError, WaptError) as e:
            result["upgrade"] = f"échec : {e}"
            detail += f" ; mise à jour non lancée : {e}"
    await record(request, user, "assign", targets=targets, params=params,
                 ok=not result["failed"] and not result["conflicts"], detail=detail)
    return result


class GroupRequest(BaseModel):
    name: str = Field(pattern=actions.PACKAGE_RE.pattern)
    description: str = Field(default="", max_length=500)
    depends: list[str] = Field(default_factory=list, max_length=200)
    conflicts: list[str] = Field(default_factory=list, max_length=200)
    expected_version: str | None = None

    @field_validator("depends", "conflicts")
    @classmethod
    def valid_packages(cls, v: list[str]) -> list[str]:
        if not all(actions.PACKAGE_RE.fullmatch(p) for p in v):
            raise ValueError("invalid package name")
        return list(dict.fromkeys(v))


async def _group_call(request: Request, user: User, action: str, name: str, params: dict, coro):
    try:
        result = await coro
    except KeyLocked as e:
        raise HTTPException(423, "clé de signature verrouillée") from e
    except management.Conflict as e:
        await record(request, user, action, targets=[{"uuid": name, "name": name}], params=params, ok=False,
                     detail=str(e))
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except (SigningError, WaptError) as e:
        await record(request, user, action, targets=[{"uuid": name, "name": name}], params=params, ok=False,
                     detail=str(e))
        raise HTTPException(502, str(e)) from e
    await record(request, user, action, targets=[{"uuid": name, "name": name}], params=params,
                 detail=f"version {result.get('version', '')}".strip() if action != "group_delete"
                 else f"{result['deleted_versions']} version(s) supprimée(s)")
    return result


@router.post("/groups")
async def group_create(request: Request, body: GroupRequest, user: Annotated[User, Depends(require("admin"))]):
    params = {"packages": body.depends, "description": body.description}
    return await _group_call(request, user, "group_create", body.name, params, management.save_group(
        request.app.state.wapt, request.app.state.signer, session_id(request), body.name,
        description=body.description, depends=body.depends, conflicts=body.conflicts, expected_version=None,
        create=True))


@router.put("/groups/{name}")
async def group_update(request: Request, name: Annotated[str, Path(pattern=actions.PACKAGE_RE.pattern)],
                       body: GroupRequest, user: Annotated[User, Depends(require("admin"))]):
    if body.name != name:
        raise HTTPException(422, "renaming a group is not supported")
    params = {"packages": body.depends, "description": body.description}
    return await _group_call(request, user, "group_update", name, params, management.save_group(
        request.app.state.wapt, request.app.state.signer, session_id(request), name,
        description=body.description, depends=body.depends, conflicts=body.conflicts,
        expected_version=body.expected_version, create=False))


@router.delete("/groups/{name}")
async def group_delete(request: Request, name: Annotated[str, Path(pattern=actions.PACKAGE_RE.pattern)],
                       user: Annotated[User, Depends(require("admin"))], expected_version: str | None = None):
    return await _group_call(request, user, "group_delete", name, {}, management.delete_group(
        request.app.state.wapt, name, expected_version))


# --- repository maintenance and inventory (v0.6) ------------------------------------------------------------------

PackageName = Annotated[str, Path(pattern=actions.PACKAGE_RE.pattern)]


async def _repo_call(request: Request, user: User, action: str, targets: list[dict], params: dict, coro, detail):
    try:
        result = await coro
    except repo_admin.Blocked as e:
        await record(request, user, action, targets=targets, params=params, ok=False, detail=str(e))
        raise HTTPException(409, {"message": str(e), **e.reasons}) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except WaptError as e:
        await record(request, user, action, targets=targets, params=params, ok=False, detail=str(e))
        raise HTTPException(502, str(e)) from e
    await record(request, user, action, targets=targets, params=params, detail=detail(result))
    return result


@router.get("/packages/{name}/usage")
async def package_usage(request: Request, name: PackageName, user: Annotated[User, Depends(require("admin"))]):
    try:
        return await repo_admin.usage(request.app.state.wapt, name)
    except WaptError as e:
        raise HTTPException(502, str(e)) from e


@router.delete("/packages/{name}")
async def package_delete(request: Request, name: PackageName, user: Annotated[User, Depends(require("admin"))],
                         version: str | None = None):
    """Delete every version of a package, or one version (``version``); refused while still needed."""
    return await _repo_call(request, user, "package_delete", [{"uuid": name, "name": name}],
                            {"version": version} if version else {},
                            repo_admin.delete_package(request.app.state.wapt, name, version),
                            lambda r: f"versions supprimées : {', '.join(r['versions'])}")


@router.get("/repository/cleanup")
async def cleanup_plan(request: Request, user: Annotated[User, Depends(require("admin"))], keep: int = 0):
    try:
        plan = await repo_admin.cleanup_plan(request.app.state.wapt, max(0, min(keep, 10)))
    except WaptError as e:
        raise HTTPException(502, str(e)) from e
    return [vars(c) for c in plan]


class CleanupRequest(BaseModel):
    package_uuids: list[str] = Field(min_length=1, max_length=5000)
    keep: int = Field(default=0, ge=0, le=10)


@router.post("/repository/cleanup")
async def cleanup_run(request: Request, body: CleanupRequest, user: Annotated[User, Depends(require("admin"))]):
    """Delete the chosen superseded versions; the plan is computed again, anything no longer in it is skipped."""
    async def run():
        deleted = await repo_admin.cleanup(request.app.state.wapt, body.package_uuids, body.keep)
        return {"deleted": [vars(c) for c in deleted], "skipped": len(body.package_uuids) - len(deleted)}

    return await _repo_call(request, user, "cleanup", [], {"keep": body.keep}, run(),
                            lambda r: f"{len(r['deleted'])} version(s) supprimée(s)"
                                      + (f", {r['skipped']} ignorée(s)" if r["skipped"] else ""))


@router.post("/packages/upload")
async def package_upload(request: Request, file: UploadFile, user: Annotated[User, Depends(require("admin"))]):
    """Upload a package already signed (e.g. built with the WAPT console or wapt-get); the WAPT server checks that
    its signer is trusted."""
    settings = request.app.state.settings
    if not (file.filename or "").endswith(".wapt"):
        raise HTTPException(422, "un fichier .wapt est attendu")
    limit = settings.max_upload_mb * 1024 * 1024
    tmp = settings.data_dir / "tmp" / f"upload-{secrets.token_hex(8)}.wapt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = 0
        with tmp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"paquet trop volumineux (limite {settings.max_upload_mb} Mo)")
                out.write(chunk)
        name = PathlibPath(file.filename).name
        return await _repo_call(request, user, "package_upload", [{"uuid": name, "name": name}],
                                {"size": size}, repo_admin.upload_signed(request.app.state.wapt, tmp, name),
                                lambda r: f"{r['package']} {r['version']} signé par {r['signer']}")
    finally:
        tmp.unlink(missing_ok=True)


class HostsDelete(BaseModel):
    hosts: list[str] = Field(min_length=1, max_length=1000)
    delete_packages: bool = False

    @field_validator("hosts")
    @classmethod
    def valid_hosts(cls, v: list[str]) -> list[str]:
        if not all(actions.UUID_RE.fullmatch(u) for u in v):
            raise ValueError("invalid host uuid")
        return list(dict.fromkeys(v))


@router.post("/hosts/delete")
async def hosts_delete(request: Request, body: HostsDelete, user: Annotated[User, Depends(require("admin"))]):
    """Remove hosts from the WAPT inventory (an agent still running registers again at its next update)."""
    hosts, _ = await request.app.state.inventory.hosts()
    names = {h["uuid"]: h["name"] for h in hosts}
    targets = [{"uuid": u, "name": names.get(u, u)} for u in body.hosts]
    result = await _repo_call(request, user, "hosts_delete", targets, {"delete_packages": body.delete_packages},
                              repo_admin.delete_hosts(request.app.state.wapt, body.hosts, body.delete_packages),
                              lambda r: f"{r['hosts']} machine(s) retirée(s), "
                                        f"{r['files']} paquet(s) machine supprimé(s)")
    await request.app.state.inventory.hosts(refresh=True)
    return result
