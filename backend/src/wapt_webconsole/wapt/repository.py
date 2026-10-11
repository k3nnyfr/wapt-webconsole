"""Private repository: packages and group packages, with their deployment on the hosts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .client import WaptClient
from .hosts import clean, host_name

SECTIONS = {"package": "base", "group": "group"}


def _csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if v]
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def summary(p: dict) -> dict:
    size = p.get("size")
    return {
        "package": p.get("package"),
        "name": clean(p.get("name")),
        "version": p.get("version") or "",
        "section": p.get("section") or "",
        "description": clean(p.get("description_fr") or p.get("description")),
        "categories": _csv(p.get("categories")),
        "editor": clean(p.get("editor")),
        "target_os": p.get("target_os") or "",
        "architecture": p.get("architecture") or "",
        "maturity": p.get("maturity") or "",
        "locale": p.get("locale") or "",
        "depends": _csv(p.get("depends")),
        "conflicts": _csv(p.get("conflicts")),
        "signer": p.get("signer") or "",
        "signature_date": p.get("signature_date") or "",
        "size": int(size) if str(size or "").isdigit() else None,
        "filename": p.get("filename") or "",
        "icon": p.get("icon_sha256sum") or "",
        "homepage": p.get("homepage") or "",
        "licence": clean(p.get("licence")),
    }


def deployment_stats(rows: list[dict]) -> dict[str, dict]:
    """Per package: hosts where it is installed, pending (to install or upgrade) or in error."""
    stats: dict[str, dict] = defaultdict(lambda: {"hosts": 0, "ok": 0, "pending": 0, "errors": 0})
    seen: set[tuple[str, str]] = set()
    for r in rows:
        package, host = r.get("package"), r.get("host")
        if not package or not host or (package, host) in seen:      # WAPT may report a package twice per host
            continue
        seen.add((package, host))
        s = stats[package]
        s["hosts"] += 1
        status = r.get("install_status") or ""
        if status == "OK" and r.get("last_audit_status") in (None, "", "OK"):
            s["ok"] += 1
        elif status.startswith("NEED-") or status == "RUNNING":
            s["pending"] += 1
        else:
            s["errors"] += 1
    return stats


async def packages(client: WaptClient, kind: str) -> list[dict]:
    """Newest version of each package (``kind`` package or group), with its deployment statistics."""
    rows = await client.call("GET", "api/v3/packages", params={"sections": SECTIONS[kind], "newest_only": "1"}) or []
    result = [summary(p) for p in rows if p.get("package")]
    names = sorted({p["package"] for p in result})
    stats = deployment_stats(await _hosts_for(client, names)) if names else {}
    for p in result:
        p["stats"] = stats.get(p["package"], {"hosts": 0, "ok": 0, "pending": 0, "errors": 0})
    return sorted(result, key=lambda p: (p["name"] or p["package"]).lower())


async def package_detail(client: WaptClient, name: str) -> dict | None:
    rows = await client.call("GET", "api/v3/packages",
                             params={"sections": "base,group", "newest_only": "0", "q": name}) or []
    versions = [summary(p) for p in rows if p.get("package") == name]
    if not versions:
        return None
    versions.sort(key=lambda p: p["signature_date"], reverse=True)
    hosts = []
    seen = set()
    for r in await _hosts_for(client, [name]):
        if r.get("host") in seen:
            continue
        seen.add(r.get("host"))
        hosts.append({
            "uuid": r.get("host"),
            "name": host_name(r.get("host_computer_fqdn")) or clean(r.get("host_description")),
            "version": r.get("version") or "",
            "install_status": r.get("install_status") or "",
            "install_date": r.get("install_date") or "",
            "audit_status": r.get("last_audit_status") or "",
        })
    hosts.sort(key=lambda h: (h["install_status"] == "OK", h["name"].lower()))
    return {"package": versions[0], "versions": versions, "hosts": hosts}


HOSTS_FOR_COLUMNS = ["package", "version", "install_status", "install_date", "last_audit_status", "host",
                     "host_computer_fqdn", "host_description"]


async def _hosts_for(client: WaptClient, packages: list[str]) -> list[dict]:
    return await client.call("POST", "api/v3/hosts_for_package",
                             json={"package": packages, "columns": HOSTS_FOR_COLUMNS, "limit": 100000}) or []
