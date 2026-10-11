"""Stands for signer.py under waptpython in the tests: the passphrase "good" opens the key."""

import json
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
        emit({"id": r["id"], "results": [{"ok": True, "action": {**a, "signature": "sig", "signer": "ab" * 32}}
                                         for a in r["actions"]]})
