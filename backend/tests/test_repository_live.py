import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from wapt_webconsole.config import Settings
from wapt_webconsole.live import LiveHub
from wapt_webconsole.main import create_app
from wapt_webconsole.wapt import repository

PNG = b"\x89PNG\r\n\x1a\nfake"
ICON = "66b1c6930bbc2bbeaf2f234bcce6726f7150599713d448a9ade6ce31d4b72afb"


def test_deployment_stats_dedup_and_states():
    rows = [
        {"package": "tsi-a", "host": "h1", "install_status": "OK", "last_audit_status": "OK"},
        {"package": "tsi-a", "host": "h1", "install_status": "NEED-UPGRADE"},          # reported twice
        {"package": "tsi-a", "host": "h2", "install_status": "NEED-INSTALL"},
        {"package": "tsi-a", "host": "h3", "install_status": "ERROR"},
        {"package": "tsi-a", "host": "h4", "install_status": "OK", "last_audit_status": "WARNING"},
    ]
    assert repository.deployment_stats(rows)["tsi-a"] == {"hosts": 4, "ok": 1, "pending": 1, "errors": 2}


class FakeWapt:
    url = "https://wapt.test"

    def __init__(self):
        self.hosts_rows = [{"uuid": "U1", "reachable": "OK"}, {"uuid": "U2", "reachable": "DISCONNECTED"}]

    async def hosts(self, columns, **filters):
        return self.hosts_rows

    async def call(self, method, path, params=None, json=None, **kwargs):
        if path == "api/v3/packages":
            return [{"package": "tsi-a", "version": "2-1", "section": "base", "signature_date": "2026-10-02",
                     "depends": "tsi-b", "icon_sha256sum": ICON, "size": "1024"},
                    {"package": "tsi-a", "version": "1-1", "section": "base", "signature_date": "2026-09-01"}]
        if path == "api/v3/hosts_for_package":
            assert "package" in json["columns"]
            return [{"package": "tsi-a", "host": "U1", "host_computer_fqdn": "pc1", "install_status": "OK"}]
        raise AssertionError(path)

    async def fetch(self, url):
        assert url == f"https://wapt.test/wapt/icons/{ICON}.png"
        return SimpleNamespace(status_code=200, content=PNG)

    async def close(self):
        pass


async def test_package_detail():
    d = await repository.package_detail(FakeWapt(), "tsi-a")
    assert [v["version"] for v in d["versions"]] == ["2-1", "1-1"]
    assert d["package"]["depends"] == ["tsi-b"] and d["package"]["size"] == 1024
    assert d["hosts"] == [{"uuid": "U1", "name": "pc1", "version": "", "install_status": "OK", "install_date": "",
                           "audit_status": ""}]
    assert await repository.package_detail(FakeWapt(), "tsi-unknown") is None


@pytest.fixture
def app(tmp_path):
    secret = tmp_path / "s"
    secret.write_text("x" * 40)
    app = create_app(Settings(session_secret_file=secret, public_url="http://testserver",
                              wapt_url="https://wapt.test"), wapt=FakeWapt())

    async def token(request):
        return {"userinfo": {"sub": "1", "preferred_username": "alex", "groups": ["wapt-viewers"]}}

    async def userinfo(token):
        return {}

    app.state.oauth = SimpleNamespace(create_client=lambda n: True,
                                      oidc=SimpleNamespace(authorize_access_token=token, userinfo=userinfo))
    return app


def test_package_routes_and_icons(app):
    with TestClient(app) as client:
        assert client.get(f"/api/icons/{ICON}.png").status_code == 401          # login required
        client.get("/auth/callback", follow_redirects=False)
        assert client.get("/api/packages").json()[0]["stats"]["ok"] == 1
        assert client.get("/api/packages?kind=other").status_code == 422
        assert client.get("/api/packages/tsi-a").json()["package"]["version"] == "2-1"
        assert client.get("/api/packages/..%2Fetc").status_code in (404, 422)
        resp = client.get(f"/api/icons/{ICON}.png")
        assert resp.content == PNG and "immutable" in resp.headers["cache-control"]
        assert client.get("/api/icons/not-a-hash.png").status_code == 422


def test_websocket_checks_origin_and_session(app):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect(
                "/api/ws", headers={"origin": "http://testserver"}) as ws:
            ws.receive_json()
        assert e.value.code == 4401                                              # no session
        client.get("/auth/callback", follow_redirects=False)
        with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect(
                "/api/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
        assert e.value.code == 4403
        with client.websocket_connect("/api/ws", headers={"origin": "http://testserver"}) as ws:
            snapshot = ws.receive_json()
            assert snapshot["type"] == "snapshot" and [h["uuid"] for h in snapshot["hosts"]] == ["U1", "U2"]


class FakeSocket:
    def __init__(self):
        self.sent, self.closed = [], None

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code, reason=""):
        self.closed = code


async def test_hub_sends_only_changes_and_drops_expired_sessions():
    from wapt_webconsole.wapt.hosts import Inventory
    wapt = FakeWapt()
    hub = LiveHub(Inventory(wapt, ttl=0), interval=0.01, session_max_age=3600)
    fresh, stale = FakeSocket(), FakeSocket()
    await hub.join(fresh, time.time())
    await hub.join(stale, time.time() - 7200)
    wapt.hosts_rows = [{"uuid": "U1", "reachable": "DISCONNECTED"}]             # U1 changed, U2 removed
    await asyncio.sleep(0.05)
    await hub.close()
    update = next(m for m in fresh.sent if m["type"] == "update" and m["changed"])
    assert [h["uuid"] for h in update["changed"]] == ["U1"] and update["changed"][0]["connected"] is False
    assert update["removed"] == ["U2"]
    assert stale.closed == 4401 and stale not in hub.clients
