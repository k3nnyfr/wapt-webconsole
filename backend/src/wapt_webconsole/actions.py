"""Remote actions on the agents: signed with the user's key, relayed by the WAPT server to the connected hosts.

The server relays an action only to hosts connected to it (websocket) and only if it is signed; the agent checks the
signature against the certificates it trusts. Wake-on-LAN is the exception: the server sends the magic packet itself,
nothing is signed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from .config import role_at_least
from .wapt.client import WaptClient

PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]{0,199}$")
UUID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@dataclass(frozen=True)
class ActionType:
    agent_action: str            # name of the action for the agent ("" for Wake-on-LAN)
    role: str                    # minimum role in the console
    label: str
    packages: bool = False       # requires a list of packages
    description: bool = False    # requires a new computer description
    connected_only: bool = True
    force: bool = False          # always forced: e.g. the agent skips audits not yet due unless forced


ACTIONS: dict[str, ActionType] = {
    "update": ActionType("trigger_host_update", "operator", "Mise à jour de l'index des paquets"),
    "upgrade": ActionType("trigger_host_upgrade", "operator", "Application des mises à jour"),
    "install": ActionType("trigger_install_packages", "operator", "Installation de paquets", packages=True),
    "inventory": ActionType("trigger_host_update_server_status", "operator", "Remontée de l'inventaire"),
    "audit": ActionType("trigger_host_audit", "operator", "Audit des paquets", force=True),
    "cancel": ActionType("trigger_cancel_all_tasks", "operator", "Annulation des tâches"),
    "wol": ActionType("", "operator", "Réveil (Wake-on-LAN)", connected_only=False),
    "remove": ActionType("trigger_remove_packages", "admin", "Désinstallation de paquets", packages=True),
    "forget": ActionType("trigger_forget_packages", "admin", "Oubli de paquets", packages=True),
    "description": ActionType("trigger_change_description", "admin", "Changement de description", description=True),
    "restart_agent": ActionType("trigger_waptservicerestart", "admin", "Redémarrage de l'agent WAPT"),
    "reboot": ActionType("trigger_host_reboot", "admin", "Redémarrage de la machine"),
    "shutdown": ActionType("trigger_host_shutdown", "admin", "Extinction de la machine"),
}


class ActionRequest(BaseModel):
    action: str
    hosts: list[str] = Field(min_length=1, max_length=1000)
    packages: list[str] = Field(default_factory=list, max_length=50)
    description: str | None = Field(default=None, max_length=250)
    force: bool = False

    @field_validator("action")
    @classmethod
    def known_action(cls, v: str) -> str:
        if v not in ACTIONS:
            raise ValueError(f"unknown action {v!r}")
        return v

    @field_validator("hosts")
    @classmethod
    def valid_hosts(cls, v: list[str]) -> list[str]:
        if not all(UUID_RE.fullmatch(u) for u in v):
            raise ValueError("invalid host uuid")
        return list(dict.fromkeys(v))

    @field_validator("packages")
    @classmethod
    def valid_packages(cls, v: list[str]) -> list[str]:
        if not all(PACKAGE_RE.fullmatch(p) for p in v):
            raise ValueError("invalid package name")
        return list(dict.fromkeys(v))


@dataclass
class Plan:
    """What an action request will do: hosts reached, hosts skipped (disconnected), agent actions to sign."""
    kind: ActionType
    reached: list[dict] = field(default_factory=list)       # {"uuid", "name"}
    skipped: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)


def check(request: ActionRequest, role: str) -> ActionType:
    kind = ACTIONS[request.action]
    if not role_at_least(role, kind.role):
        raise PermissionError(f"the {kind.role} role is required for this action")
    if kind.packages and not request.packages:
        raise ValueError("packages are required for this action")
    if kind.description and request.description is None:
        raise ValueError("a description is required for this action")
    return kind


def plan(request: ActionRequest, kind: ActionType, hosts: list[dict]) -> Plan:
    """Agent actions for the requested hosts known to the inventory, connected ones only (except Wake-on-LAN)."""
    by_uuid = {h["uuid"]: h for h in hosts}
    result = Plan(kind)
    for uuid in request.hosts:
        host = by_uuid.get(uuid)
        if host is None:
            raise LookupError(f"unknown host {uuid}")
        target = {"uuid": uuid, "name": host["name"]}
        if kind.connected_only and not host["connected"]:
            result.skipped.append(target)
            continue
        result.reached.append(target)
        if kind.agent_action:
            action = {"action": kind.agent_action, "uuid": uuid, "notify_server": True, "notify_user": False,
                      "force": request.force or kind.force}
            if kind.packages:
                action["packages"] = request.packages
            if kind.description:
                action["computer_description"] = request.description
            result.actions.append(action)
    return result


async def send(client: WaptClient, plan_: Plan, signed: list[dict]) -> str:
    """Relay the signed actions (or Wake-on-LAN); the server message, e.g. "Actions launched: 3"."""
    if not plan_.reached:
        return "aucune machine joignable"
    if not plan_.kind.agent_action:
        await client.call("POST", "api/v3/trigger_wakeonlan", json={"uuids": [t["uuid"] for t in plan_.reached]})
        return f"Wake-on-LAN envoyé à {len(plan_.reached)} machine(s)"
    payload = await client.call_raw("POST", "api/v3/trigger_host_action", json=signed)
    return payload.get("msg") or "envoyé"
