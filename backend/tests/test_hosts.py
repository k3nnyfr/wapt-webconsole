from wapt_webconsole.wapt.hosts import Inventory, flatten, ipv4s

ROW = {
    "uuid": "U1",
    "computer_fqdn": "macbook-pro\n.local",
    "computer_name": "macbook-pro",
    "connected_ips": ["172.16.1.210", "169.254.83.107", "127.0.0.1", "fe80::1", "garbage"],
    "mac_addresses": [None, "f8:34:41:c0:0a:76"],
    "connected_users": ["jdoe"],
    "last_logged_on_user": "EXAMPLE\\jdoe",
    "reachable": "OK",
    "host_status": "TO-UPGRADE",
    "host_info": {"windows_version_prettyname": "23H2", "cpu_name": "4 x Intel i5"},
    "host_metrics": {"physical_memory": 8173510656, "last_bootup_time": "2026-10-11T08:30:33+00:00"},
    "last_update_status": {"upgrades": ["a", "b"], "errors": []},
}


def test_flatten():
    h = flatten(ROW)
    assert h["name"] == "macbook-pro.local"            # line break reported by the agent removed
    assert h["ips"] == ["172.16.1.210"]
    assert h["mac"] == "f8:34:41:c0:0a:76"
    assert h["last_user"] == "EXAMPLE\\jdoe" and h["users"] == ["jdoe"]
    assert h["connected"] is True and h["status"] == "TO-UPGRADE"
    assert h["os_release"] == "23H2" and h["cpu"] == "4 x Intel i5" and h["memory_gb"] == 7.6
    assert h["pending"] == 2 and h["errors"] == 0


def test_flatten_minimal_row():
    h = flatten({"uuid": "U2"})
    assert h["name"] == "U2" and h["connected"] is False and h["memory_gb"] is None and h["ips"] == []


def test_ipv4s():
    assert ipv4s(None) == [] and ipv4s(["10.0.0.1", "::1"]) == ["10.0.0.1"]


class CountingClient:
    def __init__(self):
        self.calls = 0

    async def hosts(self, columns, **filters):
        self.calls += 1
        return [ROW, {"no": "uuid"}]


async def test_inventory_cache():
    client = CountingClient()
    inventory = Inventory(client, ttl=60)
    hosts, read_at = await inventory.hosts()
    assert [h["uuid"] for h in hosts] == ["U1"] and read_at > 0
    await inventory.hosts()
    assert client.calls == 1
    await inventory.hosts(refresh=True)
    assert client.calls == 2
