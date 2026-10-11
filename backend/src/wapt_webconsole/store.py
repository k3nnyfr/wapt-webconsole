"""Tranquil IT store: catalogue, available updates, import plan.

The store index (``<store>/Packages``) is a zip holding the control blocks of every package and some certificates
(``ssl/<sha256>.crt``). Only the certificates whose fingerprint is configured are trusted to check the packages: the
index also ships others (a "CN=test" one at the time of writing).

A store package ``tis-foo`` is imported as ``<prefix>-foo``: original signature checked, renamed with its
dependencies, signed with the user's key (``signer.py import_package``), uploaded to the repository.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
import shutil
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .management import base_name, csv, upload
from .repo_admin import version_key
from .signing import KeyLocked, Signer
from .wapt.client import WaptClient

log = logging.getLogger(__name__)

INDEX_TTL = 6 * 3600
RESTRICTED = ("wapt_enterprise", "wapt_entreprise")
FIELDS = ("package", "version", "architecture", "section", "name", "description", "description_fr", "maturity",
          "locale", "target_os", "depends", "conflicts", "licence", "editor", "categories", "homepage",
          "icon_sha256sum", "signature_date", "filename", "size", "md5sum", "signer_fingerprint", "min_os_version")
FAMILIES = {"windows": "windows", "darwin": "macos", "macos": "macos", "mac": "macos", "linux": "linux",
            "debian": "linux", "debian_based": "linux", "ubuntu": "linux", "redhat_based": "linux", "all": "all"}
ARCHITECTURES = {"windows": {"x64", "all", ""}, "macos": {"arm", "arm64", "x64", "all", ""},
                 "linux": {"x64", "all", ""}}
LOCALES = {"all", "", "fr", "en"}
# Tied to the version of the WAPT server: never taken from the store
EXCLUDED = {"waptupgrade", "waptsetup", "waptagent", "waptserver"}


def parse_index(text: str) -> list[dict]:
    """Control blocks separated by blank lines; continuation lines (leading space) are appended."""
    entries = []
    for block in text.split("\n\n"):
        entry: dict[str, str] = {}
        key = None
        for line in block.splitlines():
            if line[:1].isspace() and key:
                entry[key] += "\n" + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                entry[key] = value.strip()
        if entry.get("package"):
            entries.append({k: entry.get(k, "") for k in FIELDS})
    return entries


def pem_fingerprint(pem: str) -> str:
    body = "".join(line for line in pem.strip().splitlines() if line and not line.startswith("-----"))
    return hashlib.sha256(base64.b64decode(body)).hexdigest()


def families(target_os: str) -> set[str]:
    """``debian(>=10),ubuntu(>=20)`` -> {"linux"}; ``all`` -> {"all"}."""
    return {FAMILIES.get(re.split(r"[(<>=\s]", t.strip())[0], "other") for t in target_os.split(",") if t.strip()} \
        or {"all"}


def wanted(entry: dict, fleet: set[str]) -> bool:
    """Entry useful for the fleet's systems (``fleet``: windows, macos, linux), production, a common locale."""
    if entry.get("maturity") not in ("PROD", "") or entry.get("locale") not in LOCALES:
        return False
    fams = families(entry.get("target_os", ""))
    targets = fleet if "all" in fams else fams & fleet
    archs = {a.strip() for a in entry.get("architecture", "").split(",")}
    return any(archs & ARCHITECTURES[f] for f in targets)


def restricted(entry: dict) -> bool:
    return any(token in entry.get("licence", "").lower() for token in RESTRICTED)


def suffix(name: str) -> str:
    """``tis-firefox`` -> ``firefox``."""
    return name.split("-", 1)[1] if "-" in name else name


def target_of(entry: dict) -> tuple[str, str, str]:
    return entry.get("target_os", ""), entry.get("architecture", ""), entry.get("locale", "")


@dataclass
class StoreIndex:
    url: str
    cache_dir: Path
    trusted_fingerprints: list[str]
    entries: list[dict] = field(default_factory=list)
    certificates: list[str] = field(default_factory=list)          # trusted PEM certificates found in the index
    loaded_at: float = 0.0
    modified: str = ""

    async def load(self, client: WaptClient, force: bool = False) -> None:
        if self.entries and not force and time.time() - self.loaded_at < INDEX_TTL:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path, meta_path = self.cache_dir / "Packages", self.cache_dir / "Packages.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() and path.exists() else {}
        headers = {k: v for k, v in (("If-None-Match", meta.get("etag")),
                                     ("If-Modified-Since", meta.get("last_modified"))) if v}
        try:
            resp = await client.fetch(f"{self.url}/Packages", headers=headers, timeout=300)
            if resp.status_code == 200:
                path.write_bytes(resp.content)
                meta = {"etag": resp.headers.get("etag"), "last_modified": resp.headers.get("last-modified")}
                meta_path.write_text(json.dumps(meta))
            elif resp.status_code != 304:
                raise RuntimeError(f"store index: HTTP {resp.status_code}")
        except Exception:
            if not path.exists():
                raise
            log.warning("Store index unreachable, using the cached copy", exc_info=True)
        self.entries, self.certificates = await asyncio.to_thread(self._read, path)
        self.loaded_at = time.time()
        self.modified = meta.get("last_modified") or ""
        log.info("Store index: %d entries, %d trusted certificate(s)", len(self.entries), len(self.certificates))

    def _read(self, path: Path) -> tuple[list[dict], list[str]]:
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as z:
            entries = parse_index(z.read("Packages").decode("utf-8", errors="replace"))
            certs = []
            for name in z.namelist():
                if name.startswith("ssl/") and name.endswith(".crt"):
                    pem = z.read(name).decode("ascii", errors="replace")
                    if pem_fingerprint(pem) in self.trusted_fingerprints:   # the file name alone is not trusted
                        certs.append(pem)
        return entries, certs


# --- catalogue and status against the repository ----------------------------------------------------------------

def newest_by_target(entries: list[dict]) -> dict[tuple, dict]:
    newest: dict[tuple, dict] = {}
    for e in entries:
        key = (e["package"], *target_of(e))
        if key not in newest or version_key(e["version"]) > version_key(newest[key]["version"]):
            newest[key] = e
    return newest


def drop_superseded(newest: dict[tuple, dict]) -> dict[tuple, dict]:
    """An "all architectures" entry left behind by a newer entry for a precise architecture of the same system and
    locale (gimp 3.2.0 "all" next to 3.2.6 "x64") is not offered any more."""
    best: dict[tuple, str] = {}
    for (package, target_os, arch, locale), e in newest.items():
        if arch not in ("all", ""):
            key = (package, target_os, locale)
            if key not in best or version_key(e["version"]) > version_key(best[key]):
                best[key] = e["version"]
    return {k: e for k, e in newest.items()
            if not (k[2] in ("all", "") and (k[0], k[1], k[3]) in best
                    and version_key(best[(k[0], k[1], k[3])]) > version_key(e["version"]))}


def store_targets(index: StoreIndex, fleet: set[str]) -> dict[tuple, dict]:
    """Newest store entry per package and target, useful to the fleet."""
    return drop_superseded(newest_by_target([
        e for e in index.entries
        if e.get("section", "base") == "base" and suffix(e["package"]) not in EXCLUDED and wanted(e, fleet)]))


def repo_prefix(repo: list[dict], store_prefix: str, configured: str = "") -> str:
    if configured:
        return configured
    counts = Counter(r["package"].split("-", 1)[0] for r in repo
                     if r.get("section") in ("base", None, "") and "-" in r.get("package", ""))
    counts.pop(store_prefix, None)
    if not counts:
        raise ValueError("préfixe du dépôt inconnu : renseignez WWC_REPO_PREFIX")
    return counts.most_common(1)[0][0]


def catalogue(index: StoreIndex, repo: list[dict], fleet: set[str], prefix: str) -> list[dict]:
    """One row per store package useful to the fleet, with its targets and its state in the repository."""
    store = store_targets(index, fleet)
    repo_newest = newest_by_target([r for r in repo if r.get("package", "").startswith(prefix + "-")])
    rows: dict[str, dict] = {}
    for (name, *target), e in store.items():
        row = rows.setdefault(suffix(name), {
            "name": suffix(name), "store_package": name, "title": e.get("name") or "", "targets": [],
            "description": e.get("description_fr") or e.get("description") or "", "editor": e.get("editor") or "",
            "categories": csv(e.get("categories")), "licence": e.get("licence") or "", "restricted": restricted(e),
            "icon": e.get("icon_sha256sum") or "", "homepage": e.get("homepage") or "", "version": e["version"],
            "signature_date": e.get("signature_date") or ""})
        mine = repo_newest.get((f"{prefix}-{suffix(name)}", *target))
        state = "absent" if mine is None else "update" if version_key(e["version"]) > version_key(mine["version"]) \
            else "ok"
        row["targets"].append({"target": " · ".join(t for t in target if t), "version": e["version"],
                               "repo_version": mine["version"] if mine else None, "state": state,
                               "size": int(e["size"]) if str(e.get("size")).isdigit() else 0})
        if version_key(e["version"]) > version_key(row["version"]):
            row["version"] = e["version"]
    in_repo = {suffix(r["package"]) for r in repo if r.get("package", "").startswith(prefix + "-")}
    for row in rows.values():
        states = {t["state"] for t in row["targets"]}
        row["state"] = ("update" if "update" in states else "ok" if row["name"] in in_repo else "absent")
        row["size"] = sum(t["size"] for t in row["targets"])
    return sorted(rows.values(), key=lambda r: (r["title"] or r["name"]).lower())


@dataclass
class PlanItem:
    store_package: str
    target_name: str              # name once imported, with our prefix
    version: str
    target: str
    filename: str
    size: int
    md5sum: str
    reason: str                   # requested / dependency
    repo_version: str | None


def plan_import(index: StoreIndex, repo: list[dict], fleet: set[str], prefix: str, names: list[str],
                with_dependencies: bool = True) -> dict:
    """Store files to import for ``names`` (suffixes: ``firefox``), dependencies first; up-to-date targets skipped."""
    store = store_targets(index, fleet)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for e in store.values():
        by_name[suffix(e["package"])].append(e)
    repo_newest = newest_by_target([r for r in repo if r.get("package", "").startswith(prefix + "-")])
    in_repo = {suffix(r["package"]) for r in repo if r.get("package", "").startswith(prefix + "-")}
    items: list[PlanItem] = []
    refused, missing, seen = [], [], set()

    def visit(name: str, reason: str) -> None:
        if name in seen:
            return
        seen.add(name)
        if name in EXCLUDED:
            refused.append(name)
            return
        entries = by_name.get(name)
        if not entries:
            missing.append(name)
            return
        if any(restricted(e) for e in entries):
            refused.append(name)
            return
        if with_dependencies:
            for e in entries:
                for dep in csv(e.get("depends")):
                    dep_name = suffix(base_name(dep))
                    if dep_name not in in_repo:
                        visit(dep_name, "dependency")
        for e in sorted(entries, key=lambda e: target_of(e)):
            mine = repo_newest.get((f"{prefix}-{name}", *target_of(e)))
            if mine is not None and version_key(mine["version"]) >= version_key(e["version"]):
                continue
            items.append(PlanItem(e["package"], f"{prefix}-{name}", e["version"],
                                  " · ".join(t for t in target_of(e) if t), e["filename"],
                                  int(e["size"]) if str(e.get("size")).isdigit() else 0, e.get("md5sum") or "",
                                  reason, mine["version"] if mine else None))

    for name in names:
        visit(name, "requested")
    return {"items": [vars(i) for i in items], "refused": refused, "missing": missing,
            "size": sum(i.size for i in items), "prefix": prefix}


# --- import job ----------------------------------------------------------------------------------------------------

async def run_import(job, client: WaptClient, signer: Signer, session: str, index: StoreIndex, prefix: str,
                     workdir: Path) -> str:
    """Download, check, rename, sign and upload each planned file; an error stops only its own item."""
    workdir.mkdir(parents=True, exist_ok=True)
    imported = 0
    for item in job.items:
        source = workdir / Path(item.filename).name
        out = workdir / "signed"
        try:
            item.status = "downloading"

            def progress(done: int, item=item) -> None:
                item.progress = done / item.size if item.size else 0.0

            await client.download(f"{index.url}/{item.filename}", source, item.size or None, item.md5sum, progress)
            item.status, item.progress = "signing", 1.0
            result = await signer.import_package(session, str(source), str(out), prefix, index.certificates)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "import failed")
            item.status = "uploading"
            await upload(client, "api/v3/upload_packages", [Path(result["path"])])
            item.status, item.imported_version = "done", result.get("version") or ""
            imported += 1
        except KeyLocked:
            for rest in job.items:
                if rest.status not in ("done", "error"):
                    rest.status, rest.error = "error", "clé de signature verrouillée"
            break
        except Exception as e:
            item.status, item.error = "error", str(e)
        finally:
            source.unlink(missing_ok=True)
            shutil.rmtree(out, ignore_errors=True)
    return f"{imported} paquet(s) importé(s) sur {len(job.items)}"
