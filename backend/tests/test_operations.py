import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from wapt_webconsole import actions
from wapt_webconsole.config import Settings
from wapt_webconsole.main import create_app
from wapt_webconsole.signing import KeyLocked, Signer, SignerConfig, SigningError

FAKE_SIGNER = str(Path(__file__).parent / "data" / "fake_signer.py")


def signer_config(tmp_path) -> SignerConfig:
    cert, key = tmp_path / "signer.crt", tmp_path / "signer.pem"
    cert.write_text("cert")
    key.write_text("key")
    return SignerConfig(waptpython=sys.executable, script=FAKE_SIGNER, certificate=str(cert), private_key=str(key))


# --- signer lifecycle --------------------------------------------------------------------------------------------

KEY_PEM = ("-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-256-CBC,00\n\nxx\n"
           "-----END RSA PRIVATE KEY-----\n")
CERT_PEM = "-----BEGIN CERTIFICATE-----\nxx\n-----END CERTIFICATE-----\n"


async def test_signer_sessions_have_their_own_process(tmp_path):
    signer = Signer(signer_config(tmp_path), ttl=60)
    with pytest.raises(KeyLocked):
        await signer.sign("s1", [{"action": "x"}])
    with pytest.raises(SigningError, match="wrong passphrase"):
        await signer.unlock("s1", "bad")
    assert (await signer.unlock("s1", "good"))["cn"] == "test-signer"           # key stored on the server
    assert signer.identity("s1")["cn"] == "test-signer" and signer.expires_in("s1") > 0
    assert (await signer.sign("s1", [{"action": "x", "uuid": "U1"}]))[0]["signature"] == "sig"
    with pytest.raises(KeyLocked):
        await signer.sign("s2", [{"action": "x"}])                              # another session did not unlock
    await signer.unlock("s2", "good", KEY_PEM, CERT_PEM)                        # key brought by the user
    assert signer.sessions["s1"].proc is not signer.sessions["s2"].proc
    await signer.lock("s1")
    assert "s1" not in signer.sessions and signer.identity("s1") == {}
    assert (await signer.sign("s2", [{"action": "x"}]))[0]["signature"] == "sig"
    await signer.close()
    assert signer.sessions == {}                                                # keys gone from memory


async def test_brought_key_checks(tmp_path):
    signer = Signer(SignerConfig(waptpython=sys.executable, script=FAKE_SIGNER), ttl=60)   # no key on the server
    assert not signer.config.configured
    with pytest.raises(SigningError, match="choisissez"):
        await signer.unlock("s1", "good")
    with pytest.raises(SigningError, match="passphrase"):
        await signer.unlock("s1", "good", KEY_PEM.replace("Proc-Type: 4,ENCRYPTED\n", ""), CERT_PEM)
    with pytest.raises(SigningError, match="certificat"):
        await signer.unlock("s1", "good", KEY_PEM, "")
    with pytest.raises(SigningError, match="volumineux"):
        await signer.unlock("s1", "good", KEY_PEM + "x" * 70_000, CERT_PEM)
    await signer.unlock("s1", "good", KEY_PEM, CERT_PEM)
    await signer.close()


async def test_signer_expiry(tmp_path):
    signer = Signer(signer_config(tmp_path), ttl=0.05)
    await signer.unlock("s1", "good")
    time.sleep(0.1)
    with pytest.raises(KeyLocked):
        await signer.sign("s1", [{"action": "x"}])
    assert signer.sessions == {}
    await signer.close()


# --- planning --------------------------------------------------------------------------------------------------

HOSTS = [{"uuid": "U1", "name": "pc1", "connected": True}, {"uuid": "U2", "name": "pc2", "connected": False}]


def test_plan_and_roles():
    req = actions.ActionRequest(action="install", hosts=["U1", "U2", "U1"], packages=["tsi-firefox"])
    kind = actions.check(req, "operator")
    p = actions.plan(req, kind, HOSTS)
    assert [t["name"] for t in p.reached] == ["pc1"] and [t["name"] for t in p.skipped] == ["pc2"]
    assert p.actions == [{"action": "trigger_install_packages", "uuid": "U1", "notify_server": True,
                          "notify_user": False, "force": False, "packages": ["tsi-firefox"]}]
    with pytest.raises(PermissionError):
        actions.check(actions.ActionRequest(action="remove", hosts=["U1"], packages=["tsi-a"]), "operator")
    with pytest.raises(ValueError, match="packages"):
        actions.check(actions.ActionRequest(action="install", hosts=["U1"]), "admin")
    with pytest.raises(LookupError):
        actions.plan(actions.ActionRequest(action="update", hosts=["U9"]), actions.ACTIONS["update"], HOSTS)
    wol = actions.plan(actions.ActionRequest(action="wol", hosts=["U2"]), actions.ACTIONS["wol"], HOSTS)
    assert [t["uuid"] for t in wol.reached] == ["U2"] and wol.actions == []      # disconnected hosts: the point of WoL
    audit = actions.plan(actions.ActionRequest(action="audit", hosts=["U1"]), actions.ACTIONS["audit"], HOSTS)
    assert audit.actions[0]["force"] is True              # agents skip the audits not yet due unless forced
    with pytest.raises(ValueError):
        actions.ActionRequest(action="install", hosts=["U1"], packages=["bad name;"])
    with pytest.raises(ValueError):
        actions.ActionRequest(action="nope", hosts=["U1"])


# --- API -----------------------------------------------------------------------------------------------------------

class FakeWapt:
    url = "https://wapt.test"

    def __init__(self):
        self.sent = []

    async def hosts(self, columns, **filters):
        return [{"uuid": "U1", "computer_fqdn": "pc1", "reachable": "OK"},
                {"uuid": "U2", "computer_fqdn": "pc2", "reachable": "DISCONNECTED"}]

    async def call_raw(self, method, path, json=None, **kwargs):
        self.sent.append((path, json))
        return {"success": True, "msg": f"Actions launched: {len(json)}", "result": []}

    async def call(self, method, path, json=None, **kwargs):
        self.sent.append((path, json))
        if path == "api/v3/host_tasks_status":
            return {"running": {"id": 3, "description": "Upgrade", "progress": 50, "logs": "l" * 30_000},
                    "pending": [], "done": [{"id": i} for i in range(20)], "errors": []}
        return None

    async def close(self):
        pass


def make_client(tmp_path, role_group: str, wapt: FakeWapt) -> TestClient:
    secret = tmp_path / "session"
    secret.write_text("x" * 40)
    cfg = signer_config(tmp_path)
    settings = Settings(session_secret_file=secret, public_url="http://testserver", data_dir=tmp_path,
                        signer_certificate_file=Path(cfg.certificate), signer_key_file=Path(cfg.private_key),
                        waptpython=sys.executable, signer_script=FAKE_SIGNER)
    app = create_app(settings, wapt=wapt)

    async def token(request):
        return {"userinfo": {"sub": "1", "preferred_username": "alex", "groups": [role_group]}}

    async def userinfo(token):
        return {}

    app.state.oauth = SimpleNamespace(create_client=lambda n: True,
                                      oidc=SimpleNamespace(authorize_access_token=token, userinfo=userinfo))
    client = TestClient(app)
    client.__enter__()
    client.get("/auth/callback", follow_redirects=False)
    client.headers["X-CSRF-Token"] = client.get("/api/me").json()["csrf"]
    return client


def test_action_flow(tmp_path):
    wapt = FakeWapt()
    client = make_client(tmp_path, "wapt-operators", wapt)
    try:
        assert client.get("/api/signing").json()["server_key"] is True
        upgrade = {"action": "upgrade", "hosts": ["U1", "U2"]}
        assert client.post("/api/actions", json=upgrade).status_code == 423                  # key locked
        assert client.post("/api/signing/unlock", json={"passphrase": "bad"}).status_code == 403
        assert client.post("/api/signing/unlock", json={"passphrase": "good"}).json()["unlocked"] is True
        result = client.post("/api/actions", json=upgrade).json()
        assert result["message"] == "Actions launched: 1"
        assert [t["name"] for t in result["skipped"]] == ["pc2"]
        path, payload = wapt.sent[-1]
        assert path == "api/v3/trigger_host_action" and payload[0]["signature"] == "sig"
        assert client.post("/api/actions", json={"action": "remove", "hosts": ["U1"],
                                                 "packages": ["tsi-a"]}).status_code == 403   # admin only
        assert client.post("/api/actions", json={"action": "wol", "hosts": ["U2"]}).status_code == 200
        assert wapt.sent[-1] == ("api/v3/trigger_wakeonlan", {"uuids": ["U2"]})
        tasks = client.get("/api/hosts/U1/tasks").json()
        assert tasks["running"]["progress"] == 50 and len(tasks["running"]["logs"]) == 20_000
        assert len(tasks["done"]) == 15 and tasks["done"][0]["id"] == 19                    # newest first
        journal = client.get("/api/journal").json()
        assert [e["action"] for e in journal] == ["wol", "upgrade", "unlock", "unlock"]
        assert journal[1]["targets"] == [{"uuid": "U1", "name": "pc1"}] and journal[3]["ok"] is False
        assert journal[1]["params"]["signer"] == "test-signer"                 # which certificate signed
        assert "clé du serveur : test-signer" in journal[2]["detail"]
        brought = client.post("/api/signing/unlock", json={"passphrase": "good", "key_pem": "not a key",
                                                           "certificate_pem": "x"})
        assert brought.status_code == 422
        assert client.post("/api/signing/unlock", json={"passphrase": "good", "key_pem": KEY_PEM,
                                                        "certificate_pem": CERT_PEM}).status_code == 200
        assert client.post("/api/signing/lock").json() == {"unlocked": False}
        assert client.post("/api/actions", json=upgrade).status_code == 423
    finally:
        client.__exit__(None, None, None)


def test_viewer_cannot_act_and_unlock_is_rate_limited(tmp_path):
    client = make_client(tmp_path, "wapt-viewers", FakeWapt())
    try:
        assert client.post("/api/actions", json={"action": "update", "hosts": ["U1"]}).status_code == 403
        assert client.post("/api/signing/unlock", json={"passphrase": "good"}).status_code == 403
        assert client.get("/api/journal").status_code == 403
    finally:
        client.__exit__(None, None, None)
    (tmp_path / "op").mkdir()
    client = make_client(tmp_path / "op", "wapt-operators", FakeWapt())
    try:
        codes = [client.post("/api/signing/unlock", json={"passphrase": "bad"}).status_code for _ in range(6)]
        assert codes == [403] * 5 + [429]
    finally:
        client.__exit__(None, None, None)
