import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from wapt_webconsole import repo_admin
from wapt_webconsole.config import Settings
from wapt_webconsole.main import create_app


def test_version_key():
    assert repo_admin.version_key("1.10.2-3") > repo_admin.version_key("1.9-1")
    assert repo_admin.version_key("131.0-12") > repo_admin.version_key("131.0-9")
    assert repo_admin.version_key("2") > repo_admin.version_key("1")


REPO = [
    {"package": "tsi-a", "version": "2-1", "target_os": "windows", "architecture": "x64", "maturity": "PROD",
     "package_uuid": "a2", "size": "100"},
    {"package": "tsi-a", "version": "1-3", "target_os": "windows", "architecture": "x64", "maturity": "PROD",
     "package_uuid": "a1", "size": "90"},
    {"package": "tsi-a", "version": "1-2", "target_os": "windows", "architecture": "x64", "maturity": "PROD",
     "package_uuid": "a0", "size": "80"},
    {"package": "tsi-a", "version": "1-9", "target_os": "windows", "architecture": "x86", "maturity": "PROD",
     "package_uuid": "a86", "size": "70"},                            # another target: its newest, kept
    {"package": "tsi-b", "version": "5-1", "package_uuid": "b5", "depends": "tsi-a(=1-2)"},
    {"package": "tsi-b", "version": "4-1", "package_uuid": "b4"},
    {"package": "grp-x", "version": "3", "section": "group", "package_uuid": "g3", "depends": "tsi-b"},
]
HOST_PACKAGES = [{"package": "U1", "name": "pc1\n.example.lan", "depends": "grp-x,tsi-c"}]


class FakeWapt:
    url = "https://wapt.test"

    def __init__(self):
        self.deleted = []
        self.uploaded = []
        self.hosts_deleted = None

    async def hosts(self, columns, **filters):
        return [{"uuid": "U1", "computer_fqdn": "pc1", "reachable": "OK"}]

    async def call(self, method, path, params=None, json=None, **kwargs):
        if path == "api/v3/packages":
            return HOST_PACKAGES if params["sections"] == "host" else REPO
        if path == "api/v3/packages_delete_by_uuid":
            self.deleted.extend(json["package_uuids"])
            return {}
        if path == "api/v3/hosts_delete":
            self.hosts_deleted = json
            return {"records": [{"uuid": u} for u in json["uuids"]], "files": ["x"] if json["delete_packages"] else []}
        raise AssertionError(path)

    async def call_raw(self, method, path, files=None, **kwargs):
        self.uploaded.append((path, files[0][1][0], files[0][1][1].read()))
        return {"success": True, "result": {"files": [files[0][1][0]]}}

    async def close(self):
        pass


async def test_cleanup_plan_keeps_newest_per_target_and_pins():
    plan = await repo_admin.cleanup_plan(FakeWapt())
    assert [(c.package, c.version, c.newest) for c in plan] == [("tsi-a", "1-3", "2-1"), ("tsi-b", "4-1", "5-1")]
    assert [c.version for c in await repo_admin.cleanup_plan(FakeWapt(), keep=1)] == []    # 1-2 pinned, 1-3 kept


async def test_usage_and_delete_rules():
    wapt = FakeWapt()
    assert await repo_admin.usage(wapt, "tsi-b") == {"dependents": ["grp-x"], "hosts": []}
    assert await repo_admin.usage(wapt, "grp-x") == {"dependents": [], "hosts": ["pc1.example.lan"]}
    with pytest.raises(repo_admin.Blocked) as e:
        await repo_admin.delete_package(wapt, "tsi-b", None)
    assert e.value.reasons["dependents"] == ["grp-x"]
    with pytest.raises(repo_admin.Blocked, match="exigé"):
        await repo_admin.delete_package(wapt, "tsi-a", "1-2")                 # pinned by tsi-b
    assert (await repo_admin.delete_package(wapt, "tsi-a", "1-3"))["versions"] == ["1-3"]
    assert wapt.deleted == ["a1"]
    with pytest.raises(LookupError):
        await repo_admin.delete_package(wapt, "tsi-zz", None)


def wapt_file(control: str, signed: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("WAPT/control", control)
        if signed:
            z.writestr("WAPT/signature.sha256", "sig")
    return buf.getvalue()


SIGNED = "package : tsi-new\nversion : 1.0-1\nsection : base\nsigner : wapt.test\nsignature : abc\n"


def test_inspect_package(tmp_path):
    p = tmp_path / "x.wapt"
    p.write_bytes(wapt_file(SIGNED))
    assert repo_admin.inspect_package(p)["package"] == "tsi-new"
    for content, error in [(wapt_file(SIGNED.replace("base", "host")), "machine"),
                           (wapt_file(SIGNED, signed=False), "non signé"), (b"not a zip", "pas un paquet")]:
        p.write_bytes(content)
        with pytest.raises(ValueError, match=error):
            repo_admin.inspect_package(p)


@pytest.fixture
def client(tmp_path):
    secret = tmp_path / "session"
    secret.write_text("x" * 40)
    wapt = FakeWapt()
    app = create_app(Settings(session_secret_file=secret, public_url="http://testserver", data_dir=tmp_path,
                              max_upload_mb=1), wapt=wapt)

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


def test_routes(client, tmp_path):
    blocked = client.delete("/api/packages/tsi-b")
    assert blocked.status_code == 409 and blocked.json()["detail"]["dependents"] == ["grp-x"]
    assert client.get("/api/repository/cleanup").json()[0]["version"] == "1-3"
    run = client.post("/api/repository/cleanup", json={"package_uuids": ["a1", "not-in-plan"]}).json()
    assert [d["package_uuid"] for d in run["deleted"]] == ["a1"] and run["skipped"] == 1

    upload = client.post("/api/packages/upload", files={"file": ("tsi-new.wapt", wapt_file(SIGNED))})
    assert upload.json()["version"] == "1.0-1"
    assert client.wapt.uploaded[-1][:2] == ("api/v3/upload_packages", "tsi-new.wapt")
    assert client.post("/api/packages/upload", files={"file": ("x.zip", b"x")}).status_code == 422
    big = client.post("/api/packages/upload", files={"file": ("big.wapt", b"0" * (2 * 1024 * 1024))})
    assert big.status_code == 413
    assert not list((tmp_path / "tmp").glob("*"))                     # staged files removed

    deleted = client.post("/api/hosts/delete", json={"hosts": ["U1"], "delete_packages": True}).json()
    assert deleted == {"hosts": 1, "files": 1}
    assert client.wapt.hosts_deleted == {"uuids": ["U1"], "delete_packages": True, "delete_inventory": True}
    actions = [e["action"] for e in client.get("/api/journal").json()]
    assert actions == ["hosts_delete", "package_upload", "cleanup", "package_delete"]
