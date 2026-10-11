"""Repository maintenance: delete packages, clean superseded versions, upload signed packages, remove hosts.

Deleting is refused while something still needs the package: another repository package or group depending on it,
or a host package. An old version can go unless a requirement pins it (``tsi-foo(=1.2-3)``). Cleaning keeps the
newest version of each package per target (OS, architecture, locale, maturity), plus ``keep`` previous ones.
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .management import base_name, csv
from .wapt.client import WaptClient, WaptError
from .wapt.hosts import host_name

PIN_RE = re.compile(r"^\s*([^\s(]+)\s*\(\s*=\s*([^)\s]+)\s*\)\s*$")


class Blocked(Exception):
    """The package is still needed: ``reasons`` tells by what."""

    def __init__(self, message: str, reasons: dict):
        super().__init__(message)
        self.reasons = reasons


def version_key(version: str) -> tuple:
    """Order of WAPT versions ``1.10.2-3``: numeric parts compared as numbers, the build after the dash last."""
    upstream, _, build = str(version).partition("-")

    def parts(text: str) -> tuple:
        return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"[.+~_]", text) if p)

    return parts(upstream), parts(build)


async def all_versions(client: WaptClient) -> list[dict]:
    return await client.call("GET", "api/v3/packages",
                             params={"sections": "base,group", "newest_only": "0"}) or []


async def host_packages(client: WaptClient) -> list[dict]:
    return await client.call("GET", "api/v3/packages", params={"sections": "host"}) or []


def _pins(rows: list[dict]) -> set[tuple[str, str]]:
    """(package, version) pinned by an exact requirement somewhere."""
    pins = set()
    for r in rows:
        for req in csv(r.get("depends")) + csv(r.get("conflicts")):
            m = PIN_RE.match(req)
            if m:
                pins.add((m.group(1), m.group(2)))
    return pins


async def usage(client: WaptClient, name: str) -> dict:
    """What still needs ``name``: repository packages or groups depending on it, hosts whose package needs it."""
    repo = await all_versions(client)
    newest = {}
    for r in repo:
        if r.get("package") and (r["package"] not in newest
                                 or version_key(r["version"]) > version_key(newest[r["package"]]["version"])):
            newest[r["package"]] = r
    dependents = sorted(p for p, r in newest.items()
                        if p != name and name in {base_name(d) for d in csv(r.get("depends"))})
    hosts = sorted(host_name(r.get("name") or r.get("package")) for r in await host_packages(client)
                   if name in {base_name(d) for d in csv(r.get("depends"))})
    return {"dependents": dependents, "hosts": hosts}


async def delete_package(client: WaptClient, name: str, version: str | None) -> dict:
    """Delete every version of ``name`` (``version`` None) or one version."""
    repo = [r for r in await all_versions(client) if r.get("package") == name]
    if not repo:
        raise LookupError(f"unknown package {name}")
    if version is None:
        used = await usage(client, name)
        if used["dependents"] or used["hosts"]:
            raise Blocked(f"{name} est encore utilisé", used)
        targets = repo
    else:
        targets = [r for r in repo if str(r.get("version")) == version]
        if not targets:
            raise LookupError(f"unknown version {name} {version}")
        pinned = (name, version) in _pins(await all_versions(client) + await host_packages(client))
        if pinned:
            raise Blocked(f"{name}={version} est exigé explicitement", {"pinned": [f"{name}(={version})"]})
        if len(targets) == len(repo):
            used = await usage(client, name)          # last remaining version: same checks as a full delete
            if used["dependents"] or used["hosts"]:
                raise Blocked(f"{name} est encore utilisé", used)
    uuids = [r["package_uuid"] for r in targets if r.get("package_uuid")]
    await client.call("POST", "api/v3/packages_delete_by_uuid", json={"package_uuids": uuids})
    return {"package": name, "versions": sorted({str(r.get("version")) for r in targets}, key=version_key),
            "size": sum(int(r["size"]) for r in targets if str(r.get("size") or "").isdigit())}


# --- cleanup -------------------------------------------------------------------------------------------------------

@dataclass
class Candidate:
    package: str
    version: str
    target: str               # "windows · x64 · all · PROD"
    newest: str               # version kept for this target
    size: int
    package_uuid: str
    filename: str


async def cleanup_plan(client: WaptClient, keep: int = 0) -> list[Candidate]:
    """Versions no host can get any more: superseded for their target, not pinned by any requirement."""
    repo = await all_versions(client)
    pins = _pins(repo + await host_packages(client))
    targets: dict[tuple, list[dict]] = defaultdict(list)
    for r in repo:
        if r.get("package") and r.get("package_uuid"):
            key = (r["package"], r.get("target_os") or "", r.get("architecture") or "", r.get("locale") or "",
                   r.get("maturity") or "")
            targets[key].append(r)
    plan = []
    for key, rows in targets.items():
        rows.sort(key=lambda r: version_key(r["version"]), reverse=True)
        for r in rows[1 + keep:]:
            if (r["package"], str(r["version"])) in pins:
                continue
            plan.append(Candidate(r["package"], str(r["version"]), " · ".join(k for k in key[1:] if k),
                                  str(rows[0]["version"]), int(r["size"]) if str(r.get("size") or "").isdigit() else 0,
                                  r["package_uuid"], r.get("filename") or ""))
    return sorted(plan, key=lambda c: (c.package, version_key(c.version)))


async def cleanup(client: WaptClient, package_uuids: list[str], keep: int = 0) -> list[Candidate]:
    """Delete the chosen versions, only if they are still in the cleanup plan (computed again now)."""
    plan = {c.package_uuid: c for c in await cleanup_plan(client, keep)}
    chosen = [plan[u] for u in package_uuids if u in plan]
    if chosen:
        await client.call("POST", "api/v3/packages_delete_by_uuid",
                          json={"package_uuids": [c.package_uuid for c in chosen]})
    return chosen


# --- upload of a signed package ------------------------------------------------------------------------------------

def inspect_package(path: Path) -> dict:
    """Control attributes of a ``.wapt`` file; refuses what the repository upload must not receive."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            control = z.read("WAPT/control").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError("ce n'est pas un paquet WAPT (WAPT/control absent)") from e
    attrs: dict[str, Any] = {}
    for line in control.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith(" "):
            attrs[key.strip()] = value.strip()
    if not attrs.get("package") or not attrs.get("version"):
        raise ValueError("control incomplet : package ou version manquant")
    if attrs.get("section") == "host":
        raise ValueError("paquet machine : à modifier par l'affectation, pas par envoi")
    if "WAPT/signature.sha256" not in names or not attrs.get("signature"):
        raise ValueError("paquet non signé : signez-le avant l'envoi")
    return {k: attrs.get(k, "") for k in ("package", "version", "section", "name", "description", "architecture",
                                          "target_os", "maturity", "locale", "signer", "signature_date")}


async def upload_signed(client: WaptClient, path: Path, filename: str) -> dict:
    info = inspect_package(path)
    with path.open("rb") as f:
        payload = await client.call_raw("POST", "api/v3/upload_packages",
                                        files=[("file0", (filename, f, "application/octet-stream"))], timeout=3600)
    result = payload.get("result")
    if isinstance(result, dict) and result.get("errors"):
        raise WaptError(f"upload_packages: {result['errors']}")
    return info


# --- hosts ---------------------------------------------------------------------------------------------------------

async def delete_hosts(client: WaptClient, uuids: list[str], delete_packages: bool) -> dict:
    body = {"uuids": uuids, "delete_packages": delete_packages, "delete_inventory": True}
    result = await client.call("POST", "api/v3/hosts_delete", json=body) or {}
    return {"hosts": len(result.get("records") or []) or len(uuids), "files": len(result.get("files") or [])}
