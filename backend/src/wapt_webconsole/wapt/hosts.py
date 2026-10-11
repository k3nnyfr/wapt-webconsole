"""Host inventory: WAPT ``api/v3/hosts`` rows flattened into the columns shown by the console.

The WAPT columns ``host_info``, ``host_metrics`` and ``last_update_status`` are JSON documents; only the few values
the console displays are extracted, so the browser receives small flat records. The inventory is cached for a few
seconds: every open page polls it, the WAPT server is queried once per period whatever the number of viewers.
"""

from __future__ import annotations

import ast
import asyncio
import ipaddress
import time
from typing import Any

from .client import WaptClient

RAW_COLUMNS = [
    "computer_fqdn", "computer_name", "description", "dnsdomain", "main_ip", "connected_ips", "mac_addresses",
    "connected_users", "last_logged_on_user", "os_name", "os_version", "os_architecture", "platform",
    "manufacturer", "productname", "serialnr", "reachable", "host_status", "audit_status", "last_seen_on",
    "wapt_version", "last_update_status", "host_info", "host_metrics",
    "remote_reboot_allowed", "remote_shutdown_allowed",
]


def clean(value: Any) -> str:
    """Single-line text: some agents report names with embedded line breaks."""
    return " ".join(str(value).split()) if value not in (None, "") else ""


def user_name(value: Any) -> str:
    """Last logged on user: a string, but macOS agents report a list, sometimes serialized as its Python repr."""
    if isinstance(value, str) and value.startswith("["):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            pass
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if v), "")
    return clean(value)


def host_name(value: Any) -> str:
    """FQDN as reported by the agent, without the line breaks some agents insert."""
    return clean(value).replace(" ", "")


def ipv4s(values: list | None) -> list[str]:
    """IPv4 addresses that identify the host: no loopback, no link-local (169.254/16)."""
    result = []
    for v in values or []:
        try:
            ip = ipaddress.ip_address(v)
        except (TypeError, ValueError):
            continue
        if ip.version == 4 and not ip.is_loopback and not ip.is_link_local:
            result.append(str(ip))
    return result


def flatten(row: dict) -> dict:
    info = row.get("host_info") or {}
    metrics = row.get("host_metrics") or {}
    update = row.get("last_update_status") or {}
    name = host_name(row.get("computer_fqdn")) or clean(row.get("computer_name")) or row["uuid"]
    memory = metrics.get("physical_memory")
    return {
        "uuid": row["uuid"],
        "name": name,
        "computer_name": clean(row.get("computer_name")),
        "description": clean(row.get("description")),
        "dnsdomain": clean(row.get("dnsdomain")),
        "main_ip": clean(row.get("main_ip")),
        "ips": ipv4s(row.get("connected_ips")),
        "mac": next((m for m in row.get("mac_addresses") or [] if m), ""),
        "last_user": user_name(row.get("last_logged_on_user")),
        "users": [clean(u) for u in row.get("connected_users") or [] if u],
        "os_name": clean(row.get("os_name")),
        "os_version": clean(row.get("os_version")),
        "os_release": clean(info.get("windows_version_prettyname") or info.get("os_release_name")),
        "os_architecture": clean(row.get("os_architecture")),
        "platform": clean(row.get("platform")),
        "manufacturer": clean(row.get("manufacturer")),
        "model": clean(row.get("productname")),
        "serial": clean(row.get("serialnr")),
        "cpu": clean(info.get("cpu_name")),
        "memory_gb": round(memory / 1024**3, 1) if isinstance(memory, (int, float)) else None,
        "last_boot": metrics.get("last_bootup_time") or "",
        "connected": row.get("reachable") == "OK",
        "status": clean(row.get("host_status")),
        "audit_status": clean(row.get("audit_status")),
        "pending": len(update.get("upgrades") or []),
        "errors": len(update.get("errors") or []),
        "last_seen": row.get("last_seen_on") or "",
        "wapt_version": clean(row.get("wapt_version")),
        "reboot_allowed": bool(row.get("remote_reboot_allowed")),
        "shutdown_allowed": bool(row.get("remote_shutdown_allowed")),
    }


class Inventory:
    """Flattened hosts, refreshed from the WAPT server at most every ``ttl`` seconds."""

    def __init__(self, client: WaptClient, ttl: float = 15.0):
        self.client = client
        self.ttl = ttl
        self._hosts: list[dict] = []
        self._loaded_at = 0.0
        self._read_at = 0.0
        self._lock = asyncio.Lock()

    async def hosts(self, refresh: bool = False) -> tuple[list[dict], float]:
        """Hosts and the time they were read from the server."""
        async with self._lock:
            if refresh or time.monotonic() - self._loaded_at > self.ttl:
                rows = await self.client.hosts(RAW_COLUMNS)
                self._hosts = [flatten(r) for r in rows if r.get("uuid")]
                self._loaded_at = time.monotonic()
                self._read_at = time.time()
            return self._hosts, self._read_at
