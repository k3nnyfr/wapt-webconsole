import asyncio
import base64
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from wapt_webconsole import store
from wapt_webconsole.config import Settings
from wapt_webconsole.main import create_app

FAKE_SIGNER = str(Path(__file__).parent / "data" / "fake_signer.py")


def pem(payload: bytes) -> str:
    return "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(payload).decode() + "\n-----END CERTIFICATE-----\n"


TRUSTED = pem(b"tranquil it certificate")
UNTRUSTED = pem(b"test certificate")
TRUSTED_FP = hashlib.sha256(b"tranquil it certificate").hexdigest()


def md5_of(package: str, version: str) -> str:
    return hashlib.md5(json.dumps({"package": package, "version": version}).encode()).hexdigest()


def block(package, version, target_os="windows", arch="x64", locale="all", depends="", licence="", name=""):
    return (f"package : {package}\nversion : {version}\narchitecture : {arch}\nsection : base\nname : {name}\n"
            f"description : {package} description\n  second line\nmaturity : PROD\nlocale : {locale}\n"
            f"target_os : {target_os}\ndepends : {depends}\nlicence : {licence}\n"
            f"filename : {package}_{version}.wapt\n"
            f"size : 12\nmd5sum : {md5_of(package, version)}\n")


INDEX_BLOCKS = [
    block("tis-firefox", "131.0-12", name="Firefox", depends="tis-vcredist"),
    block("tis-firefox", "130.0-9"),
    block("tis-vcredist", "14.51-31", arch="all"),
    block("tis-gimp", "3.2.0-3", arch="all"),                     # left behind by the x64 entry below
    block("tis-gimp", "3.2.6-3"),
    block("tis-gimp", "3.2.6-5", target_os="darwin", arch="arm"),
    block("tis-tool", "1.0-1", target_os="debian(>=10),ubuntu(>=20)"),   # linux only: not for this fleet
    block("tis-pro", "2-1", licence="proprietary,wapt_enterprise"),
    block("tis-waptupgrade", "2.7-0"),
    block("tis-7zip", "26.4-44"),
]


def index_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Packages", "\n\n".join(INDEX_BLOCKS))
        z.writestr(f"ssl/{TRUSTED_FP}.crt", TRUSTED)
        z.writestr(f"ssl/{TRUSTED_FP[:-1]}0.crt", UNTRUSTED)        # named like a trusted one: content decides
    return buf.getvalue()


REPO = [{"package": "tsi-7zip", "version": "26.3-44", "section": "base", "target_os": "windows",
         "architecture": "x64", "locale": "all"},
        {"package": "tsi-firefox", "version": "131.0-12", "section": "base", "target_os": "windows",
         "architecture": "x64", "locale": "all"},
        {"package": "grp-base", "version": "3", "section": "group"}]


class FakeWapt:
    url = "https://wapt.test"

    def __init__(self):
        self.uploads = []
        self.index_requests = []

    async def hosts(self, columns, **filters):
        return [{"uuid": "U1", "computer_fqdn": "pc1", "reachable": "OK", "platform": "Windows"},
                {"uuid": "U2", "computer_fqdn": "mac1", "reachable": "OK", "platform": "macOS"}]

    async def call(self, method, path, params=None, **kwargs):
        assert path == "api/v3/packages"
        return REPO

    async def fetch(self, url, headers=None, **kwargs):
        self.index_requests.append(headers or {})
        if headers and headers.get("If-None-Match") == "v1":
            return SimpleNamespace(status_code=304, headers={}, content=b"")
        return SimpleNamespace(status_code=200, headers={"etag": "v1"}, content=index_zip())

    async def download(self, url, target, size=None, md5="", on_progress=None):
        name, version = Path(url).name.removesuffix(".wapt").split("_")
        target.write_text(json.dumps({"package": name, "version": version}))
        if on_progress:
            on_progress(size or 1)

    async def call_raw(self, method, path, files=None, **kwargs):
        self.uploads.append((path, json.loads(files[0][1][1])["package"]))
        return {"success": True, "result": {}}

    async def close(self):
        pass


@pytest.fixture
def index(tmp_path):
    idx = store.StoreIndex("https://store.test/wapt", tmp_path / "cache", [TRUSTED_FP])
    asyncio.run(idx.load(FakeWapt()))
    return idx


def test_parse_and_trust(index):
    assert len(index.entries) == len(INDEX_BLOCKS)
    assert index.entries[0]["description"] == "tis-firefox description\nsecond line"   # continuation line
    assert index.certificates == [TRUSTED]                     # only the configured fingerprint, by content


async def test_index_cache_is_conditional(tmp_path):
    wapt = FakeWapt()
    idx = store.StoreIndex("https://store.test/wapt", tmp_path, [TRUSTED_FP])
    await idx.load(wapt)
    await idx.load(wapt, force=True)
    assert wapt.index_requests[-1] == {"If-None-Match": "v1"} and len(idx.entries) == len(INDEX_BLOCKS)


def test_families_and_filters():
    assert store.families("debian(>=10),ubuntu(>=20)") == {"linux"}
    assert store.families("darwin") == {"macos"} and store.families("") == {"all"}
    assert store.wanted({"target_os": "all", "architecture": "all", "maturity": "PROD", "locale": ""}, {"windows"})
    assert not store.wanted({"target_os": "windows", "architecture": "x86", "maturity": "PROD", "locale": "all"},
                            {"windows"})


def test_catalogue(index):
    rows = {r["name"]: r for r in store.catalogue(index, REPO, {"windows", "macos"}, "tsi")}
    assert "tool" not in rows and "waptupgrade" not in rows               # linux only; tied to the server
    assert rows["7zip"]["state"] == "update" and rows["firefox"]["state"] == "ok"
    assert rows["gimp"]["state"] == "absent"
    assert sorted(t["version"] for t in rows["gimp"]["targets"]) == ["3.2.6-3", "3.2.6-5"]   # 3.2.0 "all" dropped
    assert rows["pro"]["restricted"] is True
    assert rows["firefox"]["description"] == "tis-firefox description\nsecond line"


def test_plan(index):
    plan = store.plan_import(index, REPO, {"windows", "macos"}, "tsi", ["gimp", "firefox", "pro", "waptupgrade",
                                                                       "nope", "7zip"])
    assert sorted((i["target_name"], i["version"]) for i in plan["items"]) == [
        ("tsi-7zip", "26.4-44"), ("tsi-gimp", "3.2.6-3"), ("tsi-gimp", "3.2.6-5"),
        ("tsi-vcredist", "14.51-31")]          # firefox up to date, but its dependency is missing from the repo
    assert plan["refused"] == ["pro", "waptupgrade"] and plan["missing"] == ["nope"]
    deps = store.plan_import(index, [r for r in REPO if r["package"] != "tsi-firefox"], {"windows"}, "tsi",
                             ["firefox"])
    assert [(i["target_name"], i["reason"]) for i in deps["items"]] == [("tsi-vcredist", "dependency"),
                                                                       ("tsi-firefox", "requested")]
    assert store.repo_prefix(REPO, "tis") == "tsi"
    with pytest.raises(ValueError):
        store.repo_prefix([], "tis")


@pytest.fixture
def client(tmp_path):
    secret = tmp_path / "session"
    secret.write_text("x" * 40)
    wapt = FakeWapt()
    app = create_app(Settings(session_secret_file=secret, public_url="http://testserver", data_dir=tmp_path,
                              store_trusted_fingerprints=[TRUSTED_FP], waptpython=sys.executable,
                              signer_script=FAKE_SIGNER), wapt=wapt)

    async def token(request):
        return {"userinfo": {"sub": "1", "preferred_username": "alex", "groups": ["wapt-admins"]}}

    async def userinfo(token):
        return {}

    app.state.oauth = SimpleNamespace(create_client=lambda n: True,
                                      oidc=SimpleNamespace(authorize_access_token=token, userinfo=userinfo))
    with TestClient(app) as c:
        c.get("/auth/callback", follow_redirects=False)
        c.headers["X-CSRF-Token"] = c.get("/api/me").json()["csrf"]
        c.wapt = wapt
        yield c


KEY_PEM = ("-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-256-CBC,00\n\nxx\n"
           "-----END RSA PRIVATE KEY-----\n")


def test_store_routes_and_import_job(client):
    cat = client.get("/api/store").json()
    assert cat["prefix"] == "tsi" and cat["fleet"] == ["macos", "windows"] and cat["trusted"] is True
    plan = client.post("/api/store/plan", json={"names": ["gimp"]}).json()
    assert len(plan["items"]) == 2
    assert client.post("/api/store/import", json={"names": ["gimp"]}).status_code == 423        # key locked
    assert client.post("/api/signing/unlock", json={"passphrase": "good", "key_pem": KEY_PEM,
                                                    "certificate_pem": TRUSTED}).status_code == 200
    up_to_date = {"names": ["firefox"], "with_dependencies": False}      # with them, tis-vcredist is missing
    assert client.post("/api/store/import", json=up_to_date).status_code == 422
    job = client.post("/api/store/import", json={"names": ["gimp", "7zip"]}).json()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert sorted((i["name"], i["status"], i["imported_version"]) for i in job["items"]) == [
        ("tsi-7zip", "done", "26.4-44"), ("tsi-gimp", "done", "3.2.6-3"), ("tsi-gimp", "done", "3.2.6-5")]
    assert sorted(client.wapt.uploads) == [("api/v3/upload_packages", "tsi-7zip")] + [
        ("api/v3/upload_packages", "tsi-gimp")] * 2
    entry = client.get("/api/journal").json()[0]
    assert entry["action"] == "store_import" and entry["ok"] is True and "3 paquet(s) importé(s)" in entry["detail"]
    assert client.get("/api/jobs").json()[0]["id"] == job["id"]
    assert not list((Path(client.app.state.settings.data_dir) / "tmp").rglob("*.wapt"))     # files cleaned
