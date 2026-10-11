import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from wapt_webconsole.auth import safe_next
from wapt_webconsole.config import Settings, role_at_least, role_for_groups
from wapt_webconsole.main import create_app

ROLE_GROUPS = {"viewer": ["wapt-viewers"], "operator": ["wapt-operators"], "admin": ["wapt-admins"]}


class FakeWapt:
    url = "https://wapt.test"

    async def hosts(self, columns, **filters):
        return [{"uuid": "u1", "reachable": "OK"}, {"uuid": "u2", "reachable": "DISCONNECTED"}]

    async def close(self):
        pass


class FakeOidc:
    """Stands for the Authlib client: the callback receives these claims."""

    def __init__(self, claims):
        self.claims = claims

    async def authorize_access_token(self, request):
        return {"userinfo": self.claims}

    async def userinfo(self, token):
        return {}


@pytest.fixture
def settings(tmp_path):
    secret = tmp_path / "session"
    secret.write_text("x" * 40)
    return Settings(session_secret_file=secret, public_url="http://testserver", data_dir=secret.parent)


def client_for(settings, claims=None) -> TestClient:
    app = create_app(settings, wapt=FakeWapt())
    if claims is not None:
        app.state.oauth = SimpleNamespace(oidc=FakeOidc(claims), create_client=lambda name: True)
    return TestClient(app)


def login(client: TestClient) -> str:
    resp = client.get("/auth/callback", follow_redirects=False)
    assert resp.status_code == 303, resp.text
    return client.get("/api/me").json()["csrf"]


def test_roles():
    assert role_for_groups(["users"], ROLE_GROUPS) is None
    assert role_for_groups(["wapt-viewers"], ROLE_GROUPS) == "viewer"
    assert role_for_groups(["wapt-viewers", "wapt-admins"], ROLE_GROUPS) == "admin"
    assert role_at_least("admin", "operator") and not role_at_least("viewer", "operator")
    assert not role_at_least(None, "viewer")


@pytest.mark.parametrize("target,expected", [
    ("/hosts?q=1", "/hosts?q=1"), (None, "/"), ("https://evil.example", "/"), ("//evil.example", "/"),
    ("/\\evil.example", "/"),
])
def test_safe_next(target, expected):
    assert safe_next(target) == expected


def test_health_is_public(settings):
    assert client_for(settings).get("/api/health").json()["status"] == "ok"


def test_api_requires_login(settings):
    client = client_for(settings)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/hosts").status_code == 401


def test_login_and_csrf(settings):
    with client_for(settings, {"sub": "1", "preferred_username": "alex", "groups": ["wapt-admins"]}) as client:
        csrf = login(client)
        me = client.get("/api/me").json()
        assert me["user"]["username"] == "alex" and me["user"]["role"] == "admin"
        assert client.get("/api/wapt/status").json() == {"url": "https://wapt.test", "hosts": 2, "connected": 1}
        assert client.post("/auth/logout").status_code == 403                      # no CSRF token
        assert client.post("/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
        assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).json() == {"ok": True}
        assert client.get("/api/me").status_code == 401


def test_user_without_role_is_refused(settings):
    client = client_for(settings, {"sub": "2", "preferred_username": "bob", "groups": ["users"]})
    resp = client.get("/auth/callback", follow_redirects=False)
    assert resp.headers["location"] == "/?auth_error=forbidden"
    assert client.get("/api/me").status_code == 401


def test_session_absolute_lifetime(settings, monkeypatch):
    client = client_for(settings, {"sub": "1", "preferred_username": "alex", "groups": ["wapt-viewers"]})
    login(client)
    later = time.time() + settings.session_max_age + 1
    monkeypatch.setattr("wapt_webconsole.auth.time.time", lambda: later)
    assert client.get("/api/me").status_code == 401


def test_short_session_secret_is_rejected(tmp_path):
    secret = tmp_path / "session"
    secret.write_text("short")
    with pytest.raises(ValueError, match="32 characters"):
        create_app(Settings(session_secret_file=secret), wapt=FakeWapt())
