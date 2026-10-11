"""Routes of the Tranquil IT store: catalogue, import plan, import jobs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import store
from .auth import User, require
from .jobs import Job, JobItem, Jobs
from .operations import record, session_id
from .wapt.client import WaptError

router = APIRouter(prefix="/api", tags=["store"])

PLATFORMS = {"windows": "windows", "macos": "macos", "darwin": "macos", "linux": "linux"}


async def context(request: Request, force: bool = False) -> tuple[store.StoreIndex, list[dict], set[str], str]:
    """Store index, repository versions, systems of the fleet, prefix of the repository."""
    settings = request.app.state.settings
    index: store.StoreIndex = request.app.state.store_index
    try:
        await index.load(request.app.state.wapt, force=force)
        repo = await request.app.state.wapt.call("GET", "api/v3/packages",
                                                 params={"sections": "base,group", "newest_only": "0"}) or []
        hosts, _ = await request.app.state.inventory.hosts()
        prefix = store.repo_prefix(repo, settings.store_prefix, settings.repo_prefix)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except (WaptError, RuntimeError, OSError) as e:
        raise HTTPException(502, f"store : {e}") from e
    fleet = {PLATFORMS[p] for h in hosts if (p := h["platform"].lower()) in PLATFORMS} or {"windows"}
    return index, repo, fleet, prefix


@router.get("/store")
async def catalogue(request: Request, user: Annotated[User, Depends(require("viewer"))], refresh: bool = False):
    index, repo, fleet, prefix = await context(request, force=refresh)
    return {"rows": store.catalogue(index, repo, fleet, prefix), "prefix": prefix, "fleet": sorted(fleet),
            "modified": index.modified, "trusted": bool(index.certificates)}


class ImportRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=200)
    with_dependencies: bool = True

    @field_validator("names")
    @classmethod
    def valid_names(cls, v: list[str]) -> list[str]:
        if not all(n and len(n) < 200 and all(c.isalnum() or c in "._+~-" for c in n) for n in v):
            raise ValueError("invalid package name")
        return list(dict.fromkeys(v))


@router.post("/store/plan")
async def plan(request: Request, body: ImportRequest, user: Annotated[User, Depends(require("admin"))]):
    index, repo, fleet, prefix = await context(request)
    return store.plan_import(index, repo, fleet, prefix, body.names, body.with_dependencies)


@router.post("/store/import")
async def start_import(request: Request, body: ImportRequest, user: Annotated[User, Depends(require("admin"))]):
    """Import in the background: each file downloaded, checked against the store certificate, renamed to the
    repository prefix, signed with the user's key, uploaded. Follow it with ``/api/jobs/{id}``."""
    index, repo, fleet, prefix = await context(request)
    if not index.certificates:
        raise HTTPException(503, "aucun certificat de confiance du store : vérifiez WWC_STORE_TRUSTED_FINGERPRINTS")
    sid = session_id(request)
    signer = request.app.state.signer
    if signer.expires_in(sid) <= 0:
        raise HTTPException(423, "clé de signature verrouillée")
    planned = store.plan_import(index, repo, fleet, prefix, body.names, body.with_dependencies)
    if not planned["items"]:
        raise HTTPException(422, "rien à importer : déjà à jour, absent du store ou refusé")
    items = [JobItem(i["target_name"], i["version"], i["target"], i["size"], i["reason"], i["filename"],
                     i["md5sum"]) for i in planned["items"]]
    settings = request.app.state.settings

    async def run(job: Job) -> str:
        message = await store.run_import(job, request.app.state.wapt, signer, sid, index, prefix,
                                         settings.data_dir / "tmp" / f"store-{job.id}")
        done = [i for i in job.items if i.status == "done"]
        failed = [i for i in job.items if i.status == "error"]
        await record(request, user, "store_import", targets=[{"uuid": i.name, "name": i.name} for i in done],
                     params={"packages": body.names}, ok=not failed,
                     detail=message + (f" ; échecs : {', '.join(f'{i.name} ({i.error})' for i in failed)}"
                                       if failed else ""))
        return message

    jobs: Jobs = request.app.state.jobs
    job = jobs.start(user.username, "store_import", items, run)
    return job.as_dict()


@router.get("/jobs")
async def recent_jobs(request: Request, user: Annotated[User, Depends(require("operator"))]):
    return [j.as_dict() for j in request.app.state.jobs.recent()]


@router.get("/jobs/{job_id}")
async def job(request: Request, job_id: str, user: Annotated[User, Depends(require("operator"))]):
    found = request.app.state.jobs.get(job_id)
    if found is None:
        raise HTTPException(404, "unknown job")
    return found.as_dict()
