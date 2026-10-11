"""Demo server for the documentation screenshots: the built frontend with a fake API and fictional data.

    python3 scripts/demo_server.py [--port 8090]      # then open http://localhost:8090

No WAPT server, no login: every answer is made up (example.org names and addresses). With ``?shot=<name>`` the page
also replays the interactions of a screenshot (right click, dialog...), see ``SHOTS``.
"""

from __future__ import annotations

import argparse
import http.server
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
NOW = time.time()


def iso(hours_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - hours_ago * 3600))


def host(i, name, os_name, release, connected, status, user, ip, pending=0, errors=0, audit="OK", memory=16.0,
         maker="LENOVO", model="ThinkPad T14", platform="Windows"):
    return {"uuid": f"demo-{i:04d}", "name": name, "computer_name": name.split(".")[0], "description": "",
            "dnsdomain": "example.org", "main_ip": ip, "ips": [ip], "mac": f"02:00:5e:10:00:{i:02x}",
            "last_user": user, "users": [user.split("\\")[-1]] if connected else [], "os_name": os_name,
            "os_version": "10.0.26100", "os_release": release, "os_architecture": "x64", "platform": platform,
            "manufacturer": maker, "model": model, "serial": f"DEMO{i:04d}", "cpu": "8 x Intel(R) Core(TM) i5",
            "memory_gb": memory, "last_boot": iso(20 + i), "connected": connected, "status": status,
            "audit_status": audit, "pending": pending, "errors": errors, "last_seen": iso(i * 0.7),
            "wapt_version": "2.7.0.19598", "reboot_allowed": True, "shutdown_allowed": True}


HOSTS = [
    host(1, "accueil-01.example.org", "Windows 11 Pro", "24H2", True, "OK", "EXAMPLE\\accueil", "192.0.2.21"),
    host(2, "compta-01.example.org", "Windows 11 Pro", "25H2", True, "TO-UPGRADE", "EXAMPLE\\jmartin", "192.0.2.32",
         pending=3),
    host(3, "compta-02.example.org", "Windows 10 Pro", "22H2", False, "ERROR", "EXAMPLE\\sdurand", "192.0.2.33",
         errors=1, audit="ERROR"),
    host(4, "direction.example.org", "Windows 11 Enterprise", "25H2", True, "OK", "EXAMPLE\\pdg", "192.0.2.110",
         memory=32.0, maker="Dell Inc.", model="Latitude 7450"),
    host(5, "design-mac.example.org", "macOS 15.4", "sequoia", False, "OK", "lea", "192.0.2.140", maker="Apple",
         model="MacBookPro18,1", platform="macOS"),
    host(6, "print-srv.example.org", "Windows Server 2022", "21H2", True, "OK", "EXAMPLE\\admin", "192.0.2.5",
         memory=8.0, maker="HP", model="ProLiant DL20"),
    host(7, "atelier-01.example.org", "Windows 11 Pro", "24H2", True, "TO-UPGRADE", "EXAMPLE\\atelier",
         "192.0.2.77", pending=7, audit="WARNING"),
    host(8, "rh-01.example.org", "Windows 11 Pro", "25H2", True, "OK", "EXAMPLE\\cbernard", "192.0.2.41"),
]


def package(name, title, version, section="base", stats=(3, 0, 0), depends=(), days=3, size=52_000_000):
    return {"package": name, "name": title, "version": version, "section": section,
            "description": f"{title or name} pour Windows", "categories": [], "editor": (title or name).split()[0],
            "target_os": "windows", "architecture": "x64", "maturity": "PROD", "locale": "all",
            "depends": list(depends), "conflicts": [], "signer": "wapt.example.org", "signature_date": iso(days * 24),
            "size": size, "filename": f"{name}_{version}.wapt", "icon": "", "homepage": "https://example.org",
            "licence": "Freeware", "stats": {"hosts": sum(stats), "ok": stats[0], "pending": stats[1],
                                             "errors": stats[2]}}


PACKAGES = [
    package("demo-firefox", "Mozilla Firefox", "131.0-12", stats=(6, 1, 0), days=8),
    package("demo-7zip", "7-Zip", "24.08-5", stats=(7, 0, 0), days=2),
    package("demo-obs-studio", "OBS Studio", "32.2.2.0-31", stats=(1, 1, 0), days=5),
    package("demo-vlc", "VLC media player", "3.0.21-8", stats=(5, 0, 1), days=3),
    package("demo-libreoffice", "LibreOffice", "25.8.1-3", stats=(3, 2, 0), days=4),
    package("demo-putty", "PuTTY", "0.83-2", stats=(0, 0, 0), days=10),
    package("demo-keepass", "KeePassXC", "2.7.10-4", stats=(4, 0, 0), days=6),
]
GROUPS = [
    package("grp-base", "", "18", "group", (6, 2, 0), ["demo-firefox", "demo-7zip", "demo-vlc"]),
    package("grp-compta", "", "3", "group", (2, 0, 0), ["demo-libreoffice"]),
]

HOST_PACKAGES = [
    {"package": "demo-obs-studio", "name": "OBS Studio", "version": "32.2.2.0-31", "section": "base", "maturity": "PROD",
     "description": "", "install_status": "NEED-UPGRADE", "install_date": "", "install_output": "Downloading…",
     "explicit_by": "admin", "audit_status": "", "audit_on": "", "audit_output": ""},
    {"package": "demo-firefox", "name": "Mozilla Firefox", "version": "131.0-12", "section": "base",
     "maturity": "PROD", "description": "", "install_status": "OK", "install_date": iso(30),
     "install_output": "Installation terminée", "explicit_by": "admin", "audit_status": "OK", "audit_on": iso(2),
     "audit_output": "OK"},
    {"package": "grp-base", "name": "", "version": "18", "section": "group", "maturity": "", "description": "",
     "install_status": "OK", "install_date": iso(50), "install_output": "", "explicit_by": "admin",
     "audit_status": "OK", "audit_on": iso(2), "audit_output": ""},
]

TASKS = {
    "running": {"id": 41, "description": "Mise à jour de demo-obs-studio (=32.2.2.0-31)", "summary": "Installation…",
                "progress": 60, "runstatus": "RUNNING", "created": iso(0.1), "started": iso(0.05), "finished": None,
                "created_by": "wapt.example.org", "logs": "Téléchargement terminé\nInstallation…"},
    "pending": [{"id": 42, "description": "Nettoyage du cache", "summary": "", "progress": None, "runstatus": "",
                 "created": iso(0.1), "started": None, "finished": None, "created_by": "wapt.example.org", "logs": ""}],
    "done": [{"id": 40, "description": "Mise à jour de l'index des paquets", "summary": "52 paquets dans le dépôt",
              "progress": 100, "runstatus": "DONE", "created": iso(0.2), "started": iso(0.2), "finished": iso(0.15),
              "created_by": "wapt.example.org", "logs": "52 paquets dans le dépôt"}],
    "errors": [], "cancelled": [],
}


def journal_entry(i, hours, user, role, action, targets, ok=True, detail="", **params):
    return {"id": i, "at": NOW - hours * 3600, "user": user, "role": role, "ip": "198.51.100.7", "action": action,
            "targets": [{"uuid": t, "name": t} for t in targets], "params": params, "ok": ok, "detail": detail}


JOURNAL = [
    journal_entry(7, 0.05, "jdoe", "admin", "assign", ["compta-01.example.org"], detail="publiés : 1",
                  add=["demo-vlc"], signer="wapt.example.org"),
    journal_entry(6, 0.2, "jdoe", "admin", "install", ["compta-01.example.org"], detail="Actions launched: 1",
                  packages=["demo-firefox"], signer="wapt.example.org"),
    journal_entry(5, 0.4, "msmith", "operator", "upgrade", [h["name"] for h in HOSTS[:5]],
                  detail="Actions launched: 4 ; non joignables : 1", signer="wapt.example.org"),
    journal_entry(4, 0.5, "msmith", "operator", "unlock", [], detail="clé apportée : wapt.example.org (3f2a…)"),
    journal_entry(3, 1.2, "jdoe", "admin", "cleanup", [], detail="3 version(s) supprimée(s)"),
    journal_entry(2, 1.3, "guest", "operator", "unlock", [], ok=False, detail="wrong passphrase"),
    journal_entry(1, 1.4, "jdoe", "admin", "group_update", ["grp-base"], detail="version 18",
                  packages=["demo-firefox", "demo-7zip", "demo-vlc"]),
]

CLEANUP = [
    {"package": "demo-bleachbit", "version": "5.0.2-1", "target": "windows · all · PROD", "newest": "6.0.2-1",
     "size": 16_400_000, "package_uuid": "c1", "filename": ""},
    {"package": "demo-firefox", "version": "130.0-9", "target": "windows · x64 · all · PROD", "newest": "131.0-12",
     "size": 61_000_000, "package_uuid": "c2", "filename": ""},
    {"package": "demo-vcredist", "version": "14.44-29", "target": "windows · all · PROD", "newest": "14.51-31",
     "size": 51_300_000, "package_uuid": "c3", "filename": ""},
]


def store_row(name, title, version, state, repo_version=None, categories=("Utilitaires",), restricted=False,
              size=48_000_000):
    targets = [{"target": "windows · x64 · all", "version": version, "repo_version": repo_version, "state": state,
                "size": size}]
    return {"name": name, "store_package": f"tis-{name}", "title": title, "version": version, "state": state,
            "description": f"{title} : description du store", "editor": title.split()[0],
            "categories": list(categories), "licence": "proprietary_free" + (",wapt_enterprise" if restricted else ""),
            "restricted": restricted, "icon": "", "homepage": "https://example.org", "signature_date": iso(30),
            "targets": targets, "size": size}


STORE = [
    store_row("7zip", "7-Zip", "26.4-44", "update", "26.3-44"),
    store_row("blender", "Blender", "4.5.3-12", "absent", categories=("Graphisme", "3D")),
    store_row("firefox", "Mozilla Firefox", "132.0-3", "update", "131.0-12", ("Internet",)),
    store_row("gimp", "GIMP", "3.2.6-3", "absent", categories=("Graphisme",)),
    store_row("inkscape", "Inkscape", "1.4.2-6", "absent", categories=("Graphisme",)),
    store_row("keepassxc", "KeePassXC", "2.7.10-4", "ok", "2.7.10-4", ("Sécurité",)),
    store_row("notepadplusplus", "Notepad++", "8.8.6-21", "absent", categories=("Développement",)),
    store_row("vlc", "VLC media player", "3.0.21-8", "ok", "3.0.21-8", ("Multimédia",)),
    store_row("zoom", "Zoom Workplace", "6.6.2-1", "absent", categories=("Communication",), restricted=True),
]


def store_plan(names: list[str]) -> dict:
    items = []
    for name in names:
        row = next((r for r in STORE if r["name"] == name), None)
        if row and not row["restricted"]:
            if name == "inkscape":
                items.append({"store_package": "tis-vcredist", "target_name": "demo-vcredist", "version": "14.51-31",
                              "target": "windows · all", "filename": "tis-vcredist.wapt", "size": 25_600_000,
                              "reason": "dependency", "repo_version": None})
            items.append({"store_package": row["store_package"], "target_name": f"demo-{name}",
                          "version": row["version"], "target": "windows · x64 · all",
                          "filename": f"tis-{name}.wapt", "size": row["size"], "reason": "requested",
                          "repo_version": row["targets"][0]["repo_version"]})
    return {"items": items, "refused": [], "missing": [], "size": sum(i["size"] for i in items), "prefix": "demo"}


def detail(h: dict) -> dict:
    return {"host": h, "hardware": {"bios_vendor": h["manufacturer"], "bios_version": "1.46", "bios_date": "2024-05-25",
                                    "os_installed_on": "2024-03-02T09:12:00+00:00",
                                    "drives": [{"name": "C:", "filesystem": "NTFS", "size_gb": 237.9, "free_gb": 42.2,
                                                "free_percent": 17},
                                               {"name": "D:", "filesystem": "NTFS", "size_gb": 931.5, "free_gb": 610.0,
                                                "free_percent": 65}],
                                    "gateways": ["192.0.2.1"], "networks": []},
            "host_package": {"version": "7", "depends": ["grp-base", "demo-obs-studio", "demo-keepass"],
                             "conflicts": [], "signer": "wapt.example.org", "signature_date": iso(26)}}


def api(path: str, query: dict, locked: bool):
    if path == "/api/me":
        return {"user": {"username": "jdoe", "name": "Jane Doe", "email": "", "role": "admin", "groups": []},
                "csrf": "demo", "wapt_url": "https://wapt.example.org"}
    if path == "/api/signing":
        return {"server_key": False, "unlocked": not locked, "expires_in": 0 if locked else 1500, "ttl": 1800,
                "identity": {} if locked else {"cn": "wapt.example.org"}}
    if path == "/api/hosts":
        return {"hosts": HOSTS, "read_at": NOW, "server": "https://wapt.example.org"}
    if path.startswith("/api/hosts/"):
        parts = path.split("/")
        h = next((x for x in HOSTS if x["uuid"] == parts[3]), HOSTS[1])
        if len(parts) == 4:
            return detail(h)
        return {"packages": HOST_PACKAGES, "tasks": TASKS, "softwares": [
            {"name": "7-Zip 24.08 (x64)", "version": "24.08", "publisher": "Igor Pavlov", "install_date": "2026-09-01",
             "system_component": False, "key": "7zip"}]}[parts[4]]
    if path == "/api/packages":
        return GROUPS if query.get("kind") == ["group"] else PACKAGES
    if path.startswith("/api/packages/"):
        name = path.split("/")[3]
        if path.endswith("/usage"):
            return {"dependents": [], "hosts": []}
        item = next((x for x in PACKAGES + GROUPS if x["package"] == name), PACKAGES[0])
        return {"package": item, "versions": [item], "hosts": [
            {"uuid": h["uuid"], "name": h["name"], "version": item["version"], "install_status": s,
             "install_date": iso(30), "audit_status": "OK"}
            for h, s in zip(HOSTS[:4], ["NEED-UPGRADE", "OK", "OK", "OK"], strict=False)]}
    if path == "/api/store":
        return {"rows": STORE, "prefix": "demo", "fleet": ["macos", "windows"], "modified": "Sun, 11 Oct 2026 14:02:15 GMT",
                "trusted": True}
    if path == "/api/jobs":
        return []
    if path == "/api/repository/cleanup":
        return CLEANUP
    if path == "/api/journal":
        return JOURNAL
    return None


def preview(body: dict) -> dict:
    changes = []
    for uuid in body.get("hosts", []):
        h = next((x for x in HOSTS if x["uuid"] == uuid), HOSTS[0])
        before = ["grp-base", "demo-obs-studio"]
        after = [d for d in before if d not in body.get("remove", [])] + body.get("add", [])
        changes.append({"uuid": uuid, "name": h["name"], "connected": h["connected"], "version": "7", "depends": before,
                        "conflicts": [], "new_depends": after, "new_conflicts": [], "changed": after != before})
    return {"changes": changes, "unknown": []}


# Interactions replayed for a screenshot (``?shot=``): small helpers, then steps run one after another
HELPERS = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const byText = (selector, text) => [...document.querySelectorAll(selector)].find((e) => e.textContent.includes(text));
const lastByText = (selector, text) => [...document.querySelectorAll(selector)].filter((e) => e.textContent.includes(text)).pop();
const press = (el) => { ['mousedown', 'mouseup', 'click'].forEach((t) => el.dispatchEvent(new MouseEvent(t, { bubbles: true }))); };
const contextMenu = (el) => { const r = el.getBoundingClientRect();
  el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: r.left + r.width / 3, clientY: r.top + r.height / 2 })); };
const label = (text) => [...document.querySelectorAll('label')].find((l) => l.textContent.trim() === text);
const pick = async (name, option) => { const input = document.getElementById(label(name).htmlFor);
  input.focus(); press(input); await sleep(400); press(byText('[role=option]', option)); await sleep(300);
  input.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await sleep(300); };
"""
SHOTS = {
    "hosts-selection": "await sleep(1500); document.querySelectorAll('tbody tr input[type=checkbox]').forEach((c, i) => "
                       "{ if (i === 1 || i === 3) c.click(); });",
    "hosts-menu": "await sleep(1500); contextMenu(document.querySelectorAll('tbody tr')[1]);",
    "host-tasks": "await sleep(1800); press(byText('[role=tab]', 'Tâches'));",
    "assign": "await sleep(1800); press(byText('[role=tab]', 'Paquet machine')); await sleep(500); "
              "press(byText('button', 'Modifier les paquets')); await sleep(800); "
              "await pick('Ajouter', 'VLC'); await pick('Retirer', 'demo-obs-studio'); "
              "press(lastByText('button', 'Aperçu')); await sleep(1000);",
    "cleanup": "await sleep(1500); press(byText('button', 'Nettoyer'));",
    "unlock": "await sleep(1500); press(document.querySelector('[aria-label=\"Déverrouiller la clé\"]'));",
    "store-plan": "await sleep(1500); press(byText('[role=tab]', 'Catalogue')); await sleep(600); "
                  "document.querySelectorAll('tbody tr input[type=checkbox]').forEach((c, i) => { if (i === 1 || i === 2) c.click(); }); "
                  "await sleep(300); press(lastByText('button', 'Importer')); await sleep(1200);",
    "phone-menu": "await sleep(1500); contextMenu(document.querySelectorAll('.mantine-Card-root')[5]);",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        locked = "demo_locked=1" in (self.headers.get("Cookie") or "")
        if url.path == "/frames":          # phone size: pages in iframes, their media queries follow the width
            frames = "".join(f'<iframe src="{src}" style="border:1px solid #adb5bd;border-radius:16px;width:'
                             f'{query["w"][0]}px;height:{query["h"][0]}px;background:#fff"></iframe>'
                             for src in query["src"])
            body = (f'<html><body style="margin:0;padding:20px;display:flex;gap:24px;background:#e9ecef">{frames}'
                    "</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path.startswith("/api/"):         # /api/ws included: no live channel in the demo, polling instead
            data = api(url.path, query, locked)
            return self._json(data) if data is not None else self._json({"detail": "not found"}, 404)
        if (DIST / url.path.lstrip("/")).is_file() and url.path != "/":
            return super().do_GET()
        html = (DIST / "index.html").read_text()
        shot = query.get("shot", [""])[0]
        cookie = "document.cookie = 'demo_locked=" + ("1" if shot == "unlock" else "0") + "; path=/';"
        script = f"<script>{cookie}</script>"
        if shot in SHOTS:
            script += f"<script>{HELPERS}(async () => {{ {SHOTS[shot]} }})();</script>"
        body = html.replace("<head>", "<head>" + script, 1).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if url.path == "/api/assignments/preview":
            return self._json(preview(body))
        if url.path == "/api/store/plan":
            return self._json(store_plan(body.get("names", [])))
        return self._json({"detail": "read-only demo"}, 403)

    def log_message(self, *args):
        pass


def serve(port: int) -> http.server.ThreadingHTTPServer:
    return http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    if not (DIST / "index.html").exists():
        raise SystemExit("frontend/dist is missing: run `npm run build` in frontend/ first")
    print(f"Demo on http://localhost:{args.port}")
    serve(args.port).serve_forever()
