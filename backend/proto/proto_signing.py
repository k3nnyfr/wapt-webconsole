"""Signature prototype: sign actions with waptpython in the container and have a WAPT agent check them.

Standard library only, run by the system python3 of the image (not by waptpython), the way the backend will
call ``signer.py`` as a subprocess.

Steps:
  1. signer: certificate, key, passphrase (``signer.py info``)
  2. offline: sign an action, verify it as an agent does, check that a tampered copy is rejected
  3. server: login, list the connected hosts
  4. agent, read-only: signed ``host_tasks_status`` request to one connected host (the agent checks the signature
     before answering), then the same request tampered, which must be refused
  5. agent, with ``--trigger update``: signed ``trigger_host_update`` (refresh of the package index), then
     task polling
  6. with ``--build-host`` (instead of 4 and 5): host package of the target rebuilt from its control on the server,
     with ``--add-depends`` / ``--remove-depends`` applied as the WAPT console does, version incremented, signed and
     checked. Written to ``--output-dir``, never uploaded.

Secrets are read from files (Docker/podman secrets), never from the command line.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

WAPTPYTHON = "/opt/wapt/waptpython.sh"
SIGNER = "/app/signer/signer.py"


def read_secret(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def signer(request: dict) -> list[dict]:
    proc = subprocess.run([WAPTPYTHON, SIGNER], input=json.dumps(request), capture_output=True, text=True,
                          timeout=60)
    results = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode or not results:
        detail = results[-1].get("error") if results else proc.stderr.strip()[-500:]
        raise SystemExit(f"signer.py failed ({proc.returncode}): {detail}")
    return results


class Wapt:
    def __init__(self, url: str, verify: bool = True):
        self.url = url.rstrip("/")
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                                  urllib.request.HTTPSHandler(context=ctx))

    def call(self, method: str, path: str, body=None, params: str = "", timeout: int = 60) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}/{path}{'?' + params if params else ''}", data=data, method=method,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "wapt-webconsole-proto/0.0"})
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except ValueError:
                return {"success": False, "msg": f"HTTP {e.code}"}


def split(value) -> list[str]:
    if isinstance(value, list):
        return [v.strip() for v in value if v and v.strip()]
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def edit_requirements(depends: list[str], conflicts: list[str], add: list[str], remove: list[str]):
    """Same rules as ``Wapt.edit_host``: a package added to depends leaves conflicts, and vice versa."""
    depends = [d for d in depends if d not in remove] + [a for a in add if a not in depends]
    conflicts = [c for c in conflicts if c not in add]
    return depends, conflicts


def step(title: str) -> None:
    print(f"\n== {title}")


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if ok else 'KO'}] {label}{': ' + detail if detail else ''}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="https://wapt.example.org")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password-file", default="/run/secrets/wapt_password")
    ap.add_argument("--certificate", default="/run/secrets/signer.crt")
    ap.add_argument("--private-key", default="/run/secrets/signer.pem")
    ap.add_argument("--key-password-file", default="/run/secrets/key_password")
    ap.add_argument("--host", help="uuid or FQDN of the target host (default: first connected host)")
    ap.add_argument("--trigger", choices=["update"], help="also send a signed action that changes the host state")
    ap.add_argument("--offline", action="store_true", help="stop after the offline steps")
    ap.add_argument("--build-host", action="store_true", help="build and sign the host package (never uploaded)")
    ap.add_argument("--add-depends", default="", help="packages or groups added to the host package (csv)")
    ap.add_argument("--remove-depends", default="", help="packages or groups removed from the host package (csv)")
    ap.add_argument("--output-dir", default="/out", help="where the built host package is written")
    args = ap.parse_args()

    key = {"certificate": args.certificate, "private_key": args.private_key,
           "password": read_secret(args.key_password_file)}
    failures = 0

    step("1. Signer (waptpython)")
    info = signer({"op": "info", **key})[0]
    if not check("certificate and key", info.get("ok"), info.get("error", "")):
        return 1
    print(f"  CN={info['cn']} fingerprint={info['fingerprint'][:16]}… expires {info['not_after']} "
          f"code_signing={info['code_signing']}")

    step("2. Offline signature and verification")
    sample = {"action": "trigger_host_update", "uuid": "00000000-0000-0000-0000-000000000000",
              "notify_server": True, "notify_user": False, "force": False}
    t0 = time.monotonic()
    signed = signer({"op": "sign_actions", **key, "actions": [sample]})[0]
    failures += not check("signed", signed.get("ok"), f"{(time.monotonic() - t0) * 1000:.0f} ms, "
                          f"attributes {signed.get('action', {}).get('signed_attributes')}")
    tampered = dict(signed["action"], uuid="11111111-1111-1111-1111-111111111111")
    res = signer({"op": "verify_actions", "trusted_certs": [args.certificate], "actions": [signed["action"], tampered]})
    failures += not check("verified as an agent does", res[0].get("ok"), f"verified_by={res[0].get('verified_by')}")
    failures += not check("tampered copy rejected", not res[1].get("ok"), res[1].get("error", "")[:120])
    if args.offline:
        return 1 if failures else 0

    step("3. WAPT server")
    wapt = Wapt(args.server)
    login = wapt.call("POST", "api/v3/login", {"user": args.user, "password": read_secret(args.password_file)})
    if not check(f"login {args.user}@{args.server}", login.get("success"), login.get("msg", "")):
        return 1
    try:
        hosts = wapt.call("GET", "api/v3/hosts", params="columns=computer_fqdn,reachable,os_name,wapt_version"
                                                        "&limit=10000").get("result") or []
        connected = [h for h in hosts if h.get("reachable") == "OK"]
        check("hosts", True, f"{len(hosts)} registered, {len(connected)} connected")
        targets = [h for h in hosts if args.host in (h["uuid"], h.get("computer_fqdn"))] if args.host else connected
        if not targets:
            check("target host", False, "no connected host" if not args.host else f"{args.host} not found")
            return 1
        host = targets[0]
        print(f"  target: {host.get('computer_fqdn')} ({host['uuid']}), agent {host.get('wapt_version')}, "
              f"reachable={host.get('reachable')}")

        if args.build_host:
            failures += build_host(wapt, key, host, args)
            return 1 if failures else 0

        step("4. Agent, read-only: signed host_tasks_status")
        request = {"uuid": host["uuid"], "last_event_id": -1, "timeout": 2}
        status_req = signer({"op": "sign_actions", **key, "actions": [request]})[0]["action"]
        res = wapt.call("POST", "api/v3/host_tasks_status", status_req, timeout=30)
        failures += not check("accepted by the agent", res.get("success"), res.get("msg", ""))
        if res.get("success"):
            result = res.get("result") or {}
            print(f"  last_event_id={result.get('last_event_id')} running={bool(result.get('running'))} "
                  f"pending={len(result.get('pending') or [])} done={len(result.get('done') or [])}")
        res = wapt.call("POST", "api/v3/host_tasks_status", dict(status_req, timeout=3), timeout=30)
        failures += not check("tampered request refused", not res.get("success"), res.get("msg", "")[:160])

        if args.trigger == "update":
            step("5. Agent: signed trigger_host_update")
            action = {"action": "trigger_host_update", "uuid": host["uuid"], "notify_server": True,
                      "notify_user": False, "force": False}
            signed = signer({"op": "sign_actions", **key, "actions": [action]})[0]["action"]
            res = wapt.call("POST", "api/v3/trigger_host_action", [signed])
            failures += not check("relayed by the server", res.get("success"), res.get("msg", ""))
            for _ in range(10):
                time.sleep(3)
                poll = signer({"op": "sign_actions", **key, "actions": [request]})[0]["action"]
                st = (wapt.call("POST", "api/v3/host_tasks_status", poll, timeout=30).get("result") or {})
                running = st.get("running") or {}
                done = [t for t in st.get("done") or [] if "update" in (t.get("description") or "").lower()
                        or "Update" in (t.get("classname") or "")]
                print(f"  running={running.get('description') if running else '-'} "
                      f"pending={len(st.get('pending') or [])} last done={done[-1].get('summary') if done else '-'}")
                if not running and not st.get("pending"):
                    break
    finally:
        wapt.call("POST", "api/v3/logout")

    print(f"\n{'All checks passed' if not failures else f'{failures} check(s) failed'}")
    return 1 if failures else 0


def build_host(wapt: Wapt, key: dict, host: dict, args) -> int:
    step("6. Host package: build and sign (no upload)")
    rows = wapt.call("GET", "api/v3/packages", params=f"sections=host&q={host['uuid']}").get("result") or []
    stored = next((r for r in rows if r.get("package", "").lower() == host["uuid"].lower()), None)
    if stored is None:
        print("  no host package on the server: a new one is created")
        stored = {"package": host["uuid"], "version": "0", "section": "host", "description": host["computer_fqdn"]}
    # api/v3/packages overwrites ``name`` with the host FQDN (server.py: pe.name = computer_fqdn); the stored
    # control has it empty, so it must not be copied into the rebuilt package
    stored = {k: v for k, v in stored.items() if k != "name"}
    depends, conflicts = split(stored.get("depends")), split(stored.get("conflicts"))
    print(f"  current: version {stored.get('version')}, signed by {stored.get('signer')} on "
          f"{stored.get('signature_date')}")
    print(f"           depends={depends or '-'} conflicts={conflicts or '-'}")

    add, remove = split(args.add_depends), split(args.remove_depends)
    failures = 0
    for name in add:
        found = wapt.call("GET", "api/v3/packages", params=f"sections=base,group&q={name}").get("result") or []
        failures += not check(f"{name} in the repository", any(r.get("package") == name for r in found))
    depends, conflicts = edit_requirements(depends, conflicts, add, remove)
    control = dict(stored, depends=",".join(depends), conflicts=",".join(conflicts))

    res = signer({"op": "build_packages", **key, "output_dir": args.output_dir,
                  "jobs": [{"control": control, "inc": True}]})[0]
    if not check("built and signed", res.get("ok"), res.get("error", "")):
        print(res.get("trace", ""))
        return failures + 1
    built = res["control"]
    print(f"  {res['path']} ({res['size']} bytes), files {res['files']}")
    print(f"  new:     version {built.get('version')}, signed by {built.get('signer')} on "
          f"{built.get('signature_date')}, package_uuid {built.get('package_uuid')}")
    print(f"           depends={split(built.get('depends')) or '-'} conflicts={split(built.get('conflicts')) or '-'}")
    failures += not check("signature checked against the signer certificate", bool(res.get("verified_by")),
                          f"verified_by={res.get('verified_by')}")
    kept = [k for k in ("package", "section", "description", "maturity", "architecture", "priority")
            if str(stored.get(k) or "") != str(built.get(k) or "")]
    failures += not check("other attributes unchanged", not kept, ", ".join(kept))
    print("  not uploaded (api/v3/upload_hosts is never called by this prototype)")
    return failures


if __name__ == "__main__":
    sys.exit(main())
