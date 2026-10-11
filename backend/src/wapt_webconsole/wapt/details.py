"""Host detail: summary and hardware, WAPT packages with their logs, installed software, host package."""

from __future__ import annotations

from typing import Any

from .client import WaptClient
from .hosts import RAW_COLUMNS, clean, flatten

DETAIL_COLUMNS = RAW_COLUMNS + ["gateways", "networks", "registration_auth_user", "computer_ad_ou"]
MAX_LOG = 50_000          # characters kept from an install or audit output


def _drives(metrics: dict) -> list[dict]:
    drives = []
    for d in (metrics.get("local_drives") or {}).values():
        if not isinstance(d, dict):
            continue
        size, free = d.get("Size"), d.get("FreeSpace")
        drives.append({"name": clean(d.get("Name") or d.get("Caption")), "filesystem": clean(d.get("FileSystem")),
                       "size_gb": round(size / 1024**3, 1) if isinstance(size, (int, float)) else None,
                       "free_gb": round(free / 1024**3, 1) if isinstance(free, (int, float)) else None,
                       "free_percent": d.get("FreePercent")})
    return sorted(drives, key=lambda d: d["name"])


def hardware(row: dict) -> dict:
    info = row.get("host_info") or {}
    metrics = row.get("host_metrics") or {}
    bios = info.get("bios_infos") or {}
    return {
        "bios_vendor": clean(bios.get("bios_vendor")),
        "bios_version": clean(bios.get("bios_version")),
        "bios_date": clean(bios.get("bios_date")),
        "os_installed_on": clean(info.get("installation_date")),
        "drives": _drives(metrics),
        "gateways": [g for g in row.get("gateways") or [] if g],
        "networks": [n for n in row.get("networks") or [] if n],
    }


async def host_detail(client: WaptClient, uuid: str) -> dict | None:
    rows = await client.hosts(DETAIL_COLUMNS, uuid=uuid)
    row = next((r for r in rows if r.get("uuid") == uuid), None)
    if row is None:
        return None
    packages = await client.call("GET", "api/v3/packages", params={"sections": "host", "q": uuid}) or []
    stored = next((p for p in packages if str(p.get("package", "")).lower() == uuid.lower()), None)
    return {
        "host": flatten(row),
        "hardware": hardware(row),
        "host_package": None if stored is None else {
            "version": stored.get("version"),
            "depends": _csv(stored.get("depends")),
            "conflicts": _csv(stored.get("conflicts")),
            "signer": stored.get("signer"),
            "signature_date": stored.get("signature_date"),
        },
    }


async def host_packages(client: WaptClient, uuid: str) -> list[dict]:
    rows = await client.call("GET", "api/v3/host_data", params={"uuid": uuid, "field": "installed_packages"}) or []
    return sorted(
        ({
            "package": r.get("package"),
            "name": clean(r.get("name")),
            "version": r.get("version"),
            "section": r.get("section") or "",
            "maturity": r.get("maturity") or "",
            "description": clean(r.get("description")),
            "install_status": r.get("install_status") or "",
            "install_date": r.get("install_date") or "",
            "install_output": _log(r.get("install_output")),
            "explicit_by": r.get("explicit_by") or "",
            "audit_status": r.get("last_audit_status") or "",
            "audit_on": r.get("last_audit_on") or "",
            "audit_output": _log(r.get("last_audit_output")),
        } for r in rows if r.get("package")),
        key=lambda p: (p["install_status"] == "OK", p["section"] != "host", p["package"]),
    )


async def host_softwares(client: WaptClient, uuid: str) -> list[dict]:
    rows = await client.call("GET", "api/v3/host_data", params={"uuid": uuid, "field": "installed_softwares"}) or []
    return sorted(
        ({
            "name": clean(r.get("name")),
            "version": clean(r.get("version")),
            "publisher": clean(r.get("publisher")),
            "install_date": clean(r.get("install_date")),
            "system_component": str(r.get("system_component")) in ("1", "True", "true"),
            "key": r.get("key") or "",
        } for r in rows if r.get("name")),
        key=lambda s: s["name"].lower(),
    )


def _csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if v]
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def _log(value: Any) -> str:
    text = str(value or "")
    return text if len(text) <= MAX_LOG else text[:MAX_LOG] + "\n[…] (tronqué)"
