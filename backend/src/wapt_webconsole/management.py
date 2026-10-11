"""Host and group packages: assign packages and groups to hosts, create, edit and delete groups.

A host package (section ``host``, named after the host uuid) lists in ``depends`` what the host must have; a group
package (section ``group``) is a named list of packages. Changing them means building a new version from the
control attributes, signing it with the user's key and uploading it (``upload_hosts`` / ``upload_packages``), as the
WAPT console does. Before uploading, the version on the server is read again: if someone changed the package since
the preview (WAPT console, another user), that package is left alone and reported as a conflict.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .signing import Signer, SigningError
from .wapt.client import WaptClient, WaptError
from .wapt.hosts import host_name

UPLOAD_BATCH = 20


class Conflict(Exception):
    """The package changed on the server since it was read."""


def csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v.strip() for v in value if v and v.strip()]
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def base_name(requirement: str) -> str:
    """Package name of a requirement such as ``tsi-foo(=1.2-3)``."""
    return requirement.split("(")[0].strip()


def edit_requirements(depends: list[str], conflicts: list[str], add: list[str], remove: list[str]):
    """Rules of ``Wapt.edit_host``: an added package leaves the conflicts; removal also matches constrained
    requirements (``tsi-foo(>=2)`` is removed by ``tsi-foo``)."""
    removed = {base_name(r) for r in remove}
    depends = [d for d in depends if base_name(d) not in removed]
    depends += [a for a in add if a not in {base_name(d) for d in depends}]
    conflicts = [c for c in conflicts if base_name(c) not in set(add)]
    return depends, conflicts


async def upload(client: WaptClient, endpoint: str, paths: list[Path]) -> None:
    for i in range(0, len(paths), UPLOAD_BATCH):
        batch = paths[i:i + UPLOAD_BATCH]
        files = [(f"file{n}", (p.name, p.read_bytes(), "application/octet-stream")) for n, p in enumerate(batch)]
        payload = await client.call_raw("POST", endpoint, files=files, timeout=600)
        result = payload.get("result")
        if isinstance(result, dict) and result.get("errors"):
            raise WaptError(f"{endpoint}: {result['errors']}")


async def repository_names(client: WaptClient) -> dict[str, str]:
    """Newest packages and groups of the repository: name -> section."""
    rows = await client.call("GET", "api/v3/packages", params={"sections": "base,group", "newest_only": "1"}) or []
    return {r["package"]: r.get("section") or "base" for r in rows if r.get("package")}


# --- host packages ----------------------------------------------------------------------------------------------

@dataclass
class HostChange:
    uuid: str
    name: str
    connected: bool
    version: str | None                  # current version on the server, None: no host package yet
    depends: list[str]
    conflicts: list[str]
    new_depends: list[str] = field(default_factory=list)
    new_conflicts: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (self.depends, self.conflicts) != (self.new_depends, self.new_conflicts)

    def as_dict(self) -> dict:
        return {**asdict(self), "changed": self.changed}


async def stored_host_packages(client: WaptClient) -> dict[str, dict]:
    """Host packages on the server, by host uuid (upper case). ``name`` is dropped: the API replaces it with the
    host FQDN while the stored control has it empty."""
    rows = await client.call("GET", "api/v3/packages", params={"sections": "host"}) or []
    return {str(r["package"]).upper(): {k: v for k, v in r.items() if k != "name"} for r in rows if r.get("package")}


async def plan_assignment(client: WaptClient, hosts: list[dict], uuids: list[str], add: list[str],
                          remove: list[str]) -> tuple[list[HostChange], list[str]]:
    """Changes per host, and the added names absent from the repository."""
    names = await repository_names(client)
    unknown = [a for a in add if a not in names]
    stored = await stored_host_packages(client)
    by_uuid = {h["uuid"]: h for h in hosts}
    changes = []
    for uuid in uuids:
        host = by_uuid.get(uuid)
        if host is None:
            raise LookupError(f"unknown host {uuid}")
        pkg = stored.get(uuid.upper())
        depends, conflicts = csv(pkg.get("depends")) if pkg else [], csv(pkg.get("conflicts")) if pkg else []
        change = HostChange(uuid, host["name"], host["connected"], str(pkg["version"]) if pkg else None,
                            depends, conflicts)
        change.new_depends, change.new_conflicts = edit_requirements(depends, conflicts, add, remove)
        changes.append(change)
    return changes, unknown


async def apply_assignment(client: WaptClient, signer: Signer, session: str, hosts: list[dict], uuids: list[str],
                           add: list[str], remove: list[str], expected: dict[str, str | None]) -> dict:
    """Build, sign and upload the changed host packages; hosts changed since the preview are skipped."""
    changes, unknown = await plan_assignment(client, hosts, uuids, add, remove)
    if unknown:
        raise ValueError(f"absent du dépôt : {', '.join(unknown)}")
    stored = await stored_host_packages(client)          # read again just before writing
    jobs, conflicts, unchanged = [], [], []
    for c in changes:
        if c.uuid in expected and expected[c.uuid] != c.version:
            conflicts.append({"uuid": c.uuid, "name": c.name, "expected": expected[c.uuid], "found": c.version})
            continue
        if not c.changed:
            unchanged.append({"uuid": c.uuid, "name": c.name})
            continue
        control = dict(stored.get(c.uuid.upper()) or {"package": c.uuid, "version": "0", "section": "host",
                                                        "description": c.name})
        control.update(depends=",".join(c.new_depends), conflicts=",".join(c.new_conflicts))
        jobs.append((c, {"control": control, "inc": True}))
    published, failed = [], []
    if jobs:
        workdir = Path(tempfile.mkdtemp(prefix="wwc-hosts-"))
        try:
            results = await signer.build(session, [j for _, j in jobs], str(workdir))
            ok_paths = []
            for (c, _), r in zip(jobs, results, strict=True):
                if r.get("ok"):
                    ok_paths.append(Path(r["path"]))
                    published.append({"uuid": c.uuid, "name": c.name, "connected": c.connected,
                                      "version": r.get("version"), "previous": c.version})
                else:
                    failed.append({"uuid": c.uuid, "name": c.name, "error": r.get("error")})
            if ok_paths:
                await upload(client, "api/v3/upload_hosts", ok_paths)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    return {"published": published, "unchanged": unchanged, "conflicts": conflicts, "failed": failed}


# --- group packages ---------------------------------------------------------------------------------------------

async def group_versions(client: WaptClient, name: str) -> list[dict]:
    rows = await client.call("GET", "api/v3/packages",
                             params={"sections": "group", "newest_only": "0", "q": name}) or []
    return sorted((r for r in rows if r.get("package") == name), key=lambda r: r.get("signature_date") or "",
                  reverse=True)


async def hosts_using(client: WaptClient, name: str) -> list[str]:
    """Hosts whose host package depends on ``name``."""
    rows = await client.call("GET", "api/v3/packages", params={"sections": "host", "dependencies": name}) or []
    return sorted(host_name(r.get("name") or r.get("package")) for r in rows
                  if name in {base_name(d) for d in csv(r.get("depends"))})


async def save_group(client: WaptClient, signer: Signer, session: str, name: str, *, description: str,
                     depends: list[str], conflicts: list[str], expected_version: str | None, create: bool) -> dict:
    names = await repository_names(client)
    unknown = [p for p in depends + conflicts if p not in names and p != name]
    if unknown:
        raise ValueError(f"absent du dépôt : {', '.join(unknown)}")
    if name in depends:
        raise ValueError("un groupe ne peut pas dépendre de lui-même")
    versions = await group_versions(client, name)
    if create:
        if versions or name in names:
            raise Conflict(f"{name} existe déjà dans le dépôt")
        control = {"package": name, "version": "0", "section": "group"}
    else:
        if not versions:
            raise LookupError(f"unknown group {name}")
        if expected_version is not None and str(versions[0].get("version")) != expected_version:
            raise Conflict(f"{name} a été modifié entre-temps (version {versions[0].get('version')})")
        control = dict(versions[0])
    control.update(description=description, depends=",".join(depends), conflicts=",".join(conflicts))
    workdir = Path(tempfile.mkdtemp(prefix="wwc-groups-"))
    try:
        [result] = await signer.build(session, [{"control": control, "inc": True}], str(workdir))
        if not result.get("ok"):
            raise SigningError(result.get("error") or "build failed")
        await upload(client, "api/v3/upload_packages", [Path(result["path"])])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"package": name, "version": result.get("version"), "previous": None if create else control.get("version")}


async def delete_group(client: WaptClient, name: str, expected_version: str | None) -> dict:
    versions = await group_versions(client, name)
    if not versions:
        raise LookupError(f"unknown group {name}")
    if expected_version is not None and str(versions[0].get("version")) != expected_version:
        raise Conflict(f"{name} a été modifié entre-temps (version {versions[0].get('version')})")
    users = await hosts_using(client, name)
    if users:
        raise Conflict(f"{name} est encore affecté à {len(users)} machine(s) : {', '.join(users[:10])}")
    uuids = [v["package_uuid"] for v in versions if v.get("package_uuid")]
    await client.call("POST", "api/v3/packages_delete_by_uuid", json={"package_uuids": uuids})
    return {"package": name, "deleted_versions": len(uuids)}
