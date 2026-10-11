import asyncio
import json
import json as jsonlib  # FakeWapt.call_raw has a parameter named json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from wapt_webconsole import management
from wapt_webconsole.config import Settings
from wapt_webconsole.main import create_app

FAKE_SIGNER = str(Path(__file__).parent / "data" / "fake_signer.py")


def test_edit_requirements():
    deps, conf = management.edit_requirements(["tsi-a", "tsi-b(>=2)", "grp-x"], ["tsi-c", "tsi-d"],
                                              add=["tsi-c", "tsi-a", "tsi-e"], remove=["tsi-b"])
    assert deps == ["tsi-a", "grp-x", "tsi-c", "tsi-e"]          # constrained tsi-b removed, tsi-a not duplicated
    assert conf == ["tsi-d"]                                        # an added package leaves the conflicts


class FakeWapt:
    """Repository: tsi-a, tsi-b, grp-x; host U1 has a host package (version 3), U2 has none."""
    url = "https://wapt.test"

    def __init__(self):
        self.uploads: list[tuple[str, list[dict]]] = []
        self.deleted = []
        self.calls = []
        self.host_version = "3"
        self.group_users = []

    async def hosts(self, columns, **filters):
        return [{"uuid": "U1", "computer_fqdn": "pc1", "reachable": "OK"},
                {"uuid": "U2", "computer_fqdn": "pc2", "reachable": "DISCONNECTED"}]

    async def call(self, method, path, params=None, json=None, **kwargs):
        self.calls.append(path)
        if path == "api/v3/packages":
            if params["sections"] == "host" and "dependencies" in params:
                return [{"package": "U1", "name": n, "depends": params["dependencies"]} for n in self.group_users]
            if params["sections"] == "host":
                return [{"package": "U1", "name": "pc1.example.lan", "version": self.host_version,
                         "section": "host", "depends": "tsi-a,grp-x", "conflicts": "tsi-b", "description": "pc1"}]
            if params["sections"] == "group":
                return [{"package": "grp-x", "version": "4", "section": "group", "depends": "tsi-a",
                         "package_uuid": "pu-4", "signature_date": "2026-10-02"},
                        {"package": "grp-x", "version": "3", "section": "group", "package_uuid": "pu-3",
                         "signature_date": "2026-09-01"}]
            return [{"package": "tsi-a", "section": "base"}, {"package": "tsi-b", "section": "base"},
                    {"package": "grp-x", "section": "group"}]
        if path == "api/v3/packages_delete_by_uuid":
            self.deleted.extend(json["package_uuids"])
            return {}
        raise AssertionError(path)

    async def call_raw(self, method, path, files=None, json=None, **kwargs):
        if files is not None:
            self.uploads.append((path, [jsonlib.loads(f[1][1]) for f in files]))
            return {"success": True, "result": {"files": [f[1][0] for f in files]}}
        self.calls.append(path)
        return {"success": True, "msg": f"Actions launched: {len(json)}"}

    async def close(self):
        pass


def make_client(tmp_path, wapt, group="wapt-admins") -> TestClient:
    secret = tmp_path / "session"
    secret.write_text("x" * 40)
    cert, key = tmp_path / "c.crt", tmp_path / "k.pem"
    cert.write_text("c")
    key.write_text("k")
    app = create_app(Settings(session_secret_file=secret, public_url="http://testserver", data_dir=tmp_path,
                              signer_certificate_file=cert, signer_key_file=key, waptpython=sys.executable,
                              signer_script=FAKE_SIGNER), wapt=wapt)

    async def token(request):
        return {"userinfo": {"sub": "1", "preferred_username": "alex", "groups": [group]}}

    async def userinfo(token):
        return {}

    app.state.oauth = SimpleNamespace(create_client=lambda n: True,
                                      oidc=SimpleNamespace(authorize_access_token=token, userinfo=userinfo))
    client = TestClient(app)
    client.__enter__()
    client.get("/auth/callback", follow_redirects=False)
    client.headers["X-CSRF-Token"] = client.get("/api/me").json()["csrf"]
    return client


@pytest.fixture
def wapt():
    return FakeWapt()


@pytest.fixture
def client(tmp_path, wapt):
    c = make_client(tmp_path, wapt)
    yield c
    c.__exit__(None, None, None)


def test_preview(client):
    body = {"hosts": ["U1", "U2"], "add": ["tsi-b", "tsi-zz"], "remove": ["grp-x"]}
    preview = client.post("/api/assignments/preview", json=body).json()
    assert preview["unknown"] == ["tsi-zz"]
    u1, u2 = preview["changes"]
    assert (u1["version"], u1["new_depends"], u1["new_conflicts"]) == ("3", ["tsi-a", "tsi-b", "tsi-zz"], [])
    assert (u2["version"], u2["depends"], u2["new_depends"]) == (None, [], ["tsi-b", "tsi-zz"])


def test_apply_publishes_skips_conflicts_and_upgrades(client, wapt):
    assert client.post("/api/assignments", json={"hosts": ["U1"], "add": ["tsi-b"]}).status_code == 423   # locked
    assert client.post("/api/signing/unlock", json={"passphrase": "good"}).status_code == 200
    assert client.post("/api/assignments", json={"hosts": ["U1"], "add": ["tsi-zz"]}).status_code == 422  # unknown
    result = client.post("/api/assignments", json={
        "hosts": ["U1", "U2"], "add": ["tsi-b"], "expected": {"U1": "3", "U2": None}, "apply_now": True}).json()
    assert [(p["name"], p["previous"], p["version"]) for p in result["published"]] == [("pc1", "3", "4"),
                                                                                      ("pc2", None, "1")]
    path, controls = wapt.uploads[-1]
    assert path == "api/v3/upload_hosts"
    assert controls[0]["depends"] == "tsi-a,grp-x,tsi-b" and controls[0]["conflicts"] == ""
    assert "name" not in controls[0]                                   # API name (FQDN) never written back
    assert controls[1] == {"package": "U2", "version": "0", "section": "host", "description": "pc2",
                           "depends": "tsi-b", "conflicts": ""}
    assert result["upgrade"] == "Actions launched: 1"                  # only the connected host

    wapt.host_version = "9"                                            # changed meanwhile in the WAPT console
    result = client.post("/api/assignments", json={"hosts": ["U1"], "add": ["tsi-b"], "expected": {"U1": "3"}}).json()
    assert result["published"] == [] and result["conflicts"][0]["found"] == "9"
    result = client.post("/api/assignments", json={"hosts": ["U1"], "add": ["tsi-a"], "expected": {"U1": "9"}}).json()
    assert result["unchanged"] == [{"uuid": "U1", "name": "pc1"}] and result["published"] == []
    journal = client.get("/api/journal").json()
    assert [(e["action"], e["ok"]) for e in journal[:3]] == [("assign", True), ("assign", False), ("assign", True)]


def test_groups(client, wapt):
    assert client.post("/api/signing/unlock", json={"passphrase": "good"}).status_code == 200
    created = client.post("/api/groups", json={"name": "grp-new", "description": "Nouveau", "depends": ["tsi-a"]})
    assert created.json() == {"package": "grp-new", "version": "1", "previous": None}
    assert wapt.uploads[-1][0] == "api/v3/upload_packages"
    assert wapt.uploads[-1][1][0]["section"] == "group" and wapt.uploads[-1][1][0]["depends"] == "tsi-a"
    assert client.post("/api/groups", json={"name": "grp-x"}).status_code == 409                # exists
    assert client.post("/api/groups", json={"name": "grp-y", "depends": ["tsi-zz"]}).status_code == 422
    assert client.put("/api/groups/grp-x", json={"name": "grp-x", "depends": ["tsi-b"],
                                                 "expected_version": "3"}).status_code == 409   # stale
    updated = client.put("/api/groups/grp-x", json={"name": "grp-x", "description": "d", "depends": ["tsi-b"],
                                                    "expected_version": "4"}).json()
    assert updated == {"package": "grp-x", "version": "5", "previous": "4"}
    wapt.group_users = ["pc1.example.lan"]
    refused = client.delete("/api/groups/grp-x")
    assert refused.status_code == 409 and "pc1.example.lan" in refused.json()["detail"]
    wapt.group_users = []
    assert client.delete("/api/groups/grp-x?expected_version=4").json()["deleted_versions"] == 2
    assert wapt.deleted == ["pu-4", "pu-3"]


def test_operator_cannot_manage(tmp_path, wapt):
    c = make_client(tmp_path, wapt, group="wapt-operators")
    try:
        assert c.post("/api/assignments/preview", json={"hosts": ["U1"], "add": ["tsi-a"]}).status_code == 403
        assert c.post("/api/groups", json={"name": "grp-new"}).status_code == 403
        assert c.delete("/api/groups/grp-x").status_code == 403
    finally:
        c.__exit__(None, None, None)


def test_upload_batches(tmp_path):
    paths = []
    for i in range(45):
        p = tmp_path / f"p{i}.wapt"
        p.write_text(json.dumps({"package": f"p{i}"}))
        paths.append(p)
    wapt = FakeWapt()
    asyncio.run(management.upload(wapt, "api/v3/upload_hosts", paths))
    assert [len(files) for _, files in wapt.uploads] == [20, 20, 5]
