"""Stands for signer.py under waptpython in the tests: the passphrase "good" opens the key."""

import json
import os
import sys


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


req = json.loads(sys.stdin.readline())
if req.get("password") != "good":
    emit({"ok": False, "fatal": True, "error": "ValueError: Bad decrypt. Incorrect password?"})
    sys.exit(1)
if req["op"] == "info":
    emit({"ok": True, "cn": "test-signer"})
elif req["op"] == "serve":
    emit({"ok": True, "ready": True, "cn": "test-signer", "fingerprint": "ab" * 32})
    for line in sys.stdin:
        r = json.loads(line)
        if r["op"] == "import_package":
            with open(r["source"]) as f:
                control = json.load(f)
            if control.get("tampered") or not r.get("trusted_certs_pem"):
                emit({"id": r["id"], "results": [{"ok": False, "error": "EWaptCorruptedFiles: bad signature"}]})
                continue
            name = r["prefix"] + "-" + control["package"].split("-", 1)[1]
            path = os.path.join(r["output_dir"], f"{name}_{control['version']}.wapt")
            os.makedirs(r["output_dir"], exist_ok=True)
            with open(path, "w") as f:
                json.dump({**control, "package": name}, f)
            emit({"id": r["id"], "results": [{"ok": True, "package": name, "version": control["version"],
                                              "path": path, "verified_by": "Tranquil IT"}]})
            continue
        if r["op"] == "build_packages":
            results = []
            for job in r["jobs"]:
                control = job["control"]
                if control.get("description") == "FAIL":
                    results.append({"ok": False, "package": control["package"], "error": "build failed"})
                    continue
                version = str(int(str(control.get("version") or "0").split("-")[0]) + 1)
                path = os.path.join(r["output_dir"], f"{control['package']}_{version}.wapt")
                with open(path, "w") as f:
                    json.dump(control, f)
                results.append({"ok": True, "package": control["package"], "version": version, "path": path})
            emit({"id": r["id"], "results": results})
        else:
            emit({"id": r["id"], "results": [{"ok": True, "action": {**a, "signature": "sig", "signer": "ab" * 32}}
                                             for a in r["actions"]]})
