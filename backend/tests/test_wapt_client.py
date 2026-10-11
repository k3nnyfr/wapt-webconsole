import httpx2 as httpx
import pytest

from wapt_webconsole.wapt.client import WaptClient, WaptError


def make_client(handler) -> WaptClient:
    return WaptClient("https://wapt.test", "admin", "secret", transport=httpx.MockTransport(handler))


async def test_login_then_call():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.url.path)
        if request.url.path == "/api/v3/login":
            return httpx.Response(200, json={"success": True}, headers={"Set-Cookie": "session=abc; Path=/"})
        assert request.headers["cookie"] == "session=abc"
        return httpx.Response(200, json={"success": True, "result": [{"uuid": "u1", "reachable": "OK"}]})

    client = make_client(handler)
    assert await client.hosts(["uuid", "reachable"]) == [{"uuid": "u1", "reachable": "OK"}]
    assert await client.hosts(["uuid"])
    assert seen == ["/api/v3/login", "/api/v3/hosts", "/api/v3/hosts"]


async def test_relogin_once_on_401():
    calls = {"login": 0, "hosts": 0}

    def handler(request: httpx.Request):
        if request.url.path == "/api/v3/login":
            calls["login"] += 1
            return httpx.Response(200, json={"success": True})
        calls["hosts"] += 1
        if calls["hosts"] == 1:
            return httpx.Response(401, json={"success": False, "msg": "expired"})
        return httpx.Response(200, json={"success": True, "result": []})

    client = make_client(handler)
    assert await client.hosts(["uuid"]) == []
    assert calls == {"login": 2, "hosts": 2}


async def test_totp_account_is_refused_clearly():
    def handler(request: httpx.Request):
        return httpx.Response(401, text='{"success": false, "msg": "Missing TOTP code"}')

    with pytest.raises(WaptError, match="TOTP"):
        await make_client(handler).hosts(["uuid"])


async def test_success_false_raises():
    def handler(request: httpx.Request):
        if request.url.path == "/api/v3/login":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"success": False, "msg": "Parameter field is missing"})

    with pytest.raises(WaptError, match="Parameter field is missing"):
        await make_client(handler).call("GET", "api/v3/host_data")


async def test_non_json_answer():
    def handler(request: httpx.Request):
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    with pytest.raises(WaptError, match="non-JSON"):
        await make_client(handler).hosts(["uuid"])
