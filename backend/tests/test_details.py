from types import SimpleNamespace

from fastapi.testclient import TestClient

from wapt_webconsole.config import Settings
from wapt_webconsole.main import create_app
from wapt_webconsole.wapt import details

U = "1B4E28BA-2FA1-11D2-883F-0016D3CCA427"

HOST_ROW = {
    "uuid": U, "computer_fqdn": "pc-01.example.lan", "reachable": "OK", "gateways": ["10.0.0.1", None],
    "host_info": {"bios_infos": {"bios_vendor": "LENOVO", "bios_version": "N1WET67W (1.46 )",
                                 "bios_date": "05/25/2022"},
                  "installation_date": "2023-05-02"},
    "host_metrics": {"local_drives": {"C": {"Name": "C:", "Size": 255456624640, "FreeSpace": 45289005056,
                                            "FileSystem": "NTFS", "FreePercent": 17}}},
}
PACKAGES = [
    {"package": "tsi-firefox", "install_status": "OK", "section": "base", "install_output": "ok"},
    {"package": "tsi-obs-studio", "install_status": "NEED-UPGRADE", "section": "base", "install_output": "x" * 60_000},
    {"package": U, "install_status": "NEED-INSTALL", "section": "host"},
]
SOFTWARES = [{"name": "Zoom", "system_component": "0"}, {"name": "7-Zip", "system_component": "1"}, {"name": None}]


class FakeWapt:
    url = "https://wapt.test"

    async def hosts(self, columns, **filters):
        return [HOST_ROW] if filters.get("uuid") == U else []

    async def call(self, method, path, params=None, **kwargs):
        if path == "api/v3/packages":
            return [{"package": U.lower(), "version": "7", "depends": "tsi-a,grp-base", "conflicts": "",
                     "signer": "wapt.example.org"}]
        return {"installed_packages": PACKAGES, "installed_softwares": SOFTWARES}[params["field"]]

    async def close(self):
        pass


async def test_host_detail():
    d = await details.host_detail(FakeWapt(), U)
    assert d["host"]["name"] == "pc-01.example.lan"
    assert d["hardware"]["bios_vendor"] == "LENOVO" and d["hardware"]["gateways"] == ["10.0.0.1"]
    assert d["hardware"]["bios_date"] == "2022-05-25"                       # SMBIOS MM/DD/YYYY to RFC 3339
    assert d["hardware"]["drives"] == [{"name": "C:", "filesystem": "NTFS", "size_gb": 237.9, "free_gb": 42.2,
                                        "free_percent": 17}]
    assert d["host_package"]["depends"] == ["tsi-a", "grp-base"] and d["host_package"]["conflicts"] == []
    assert await details.host_detail(FakeWapt(), "unknown") is None


async def test_packages_problems_first_and_logs_truncated():
    pkgs = await details.host_packages(FakeWapt(), U)
    assert [p["package"] for p in pkgs] == [U, "tsi-obs-studio", "tsi-firefox"]   # host package, then pending, then OK
    assert pkgs[1]["install_output"].endswith("(tronqué)") and len(pkgs[1]["install_output"]) < 51_000


async def test_softwares():
    softs = await details.host_softwares(FakeWapt(), U)
    assert [(s["name"], s["system_component"]) for s in softs] == [("7-Zip", True), ("Zoom", False)]


def test_routes_validate_uuid(tmp_path):
    secret = tmp_path / "s"
    secret.write_text("x" * 40)
    app = create_app(Settings(session_secret_file=secret, public_url="http://testserver", data_dir=tmp_path),
                     wapt=FakeWapt())
    app.state.oauth = SimpleNamespace(create_client=lambda n: True, oidc=SimpleNamespace(
        authorize_access_token=_token, userinfo=_none))
    with TestClient(app) as client:
        client.get("/auth/callback", follow_redirects=False)
        assert client.get(f"/api/hosts/{U}").json()["host"]["uuid"] == U
        assert client.get("/api/hosts/unknown-host").status_code == 404
        assert client.get("/api/hosts/bad%20uuid;drop").status_code == 422
        assert len(client.get(f"/api/hosts/{U}/packages").json()) == 3
        assert len(client.get(f"/api/hosts/{U}/softwares").json()) == 2


async def _token(request):
    return {"userinfo": {"sub": "1", "preferred_username": "alex", "groups": ["wapt-viewers"]}}


async def _none(token):
    return {}
