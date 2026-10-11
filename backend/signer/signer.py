"""Signature helper of wapt-webconsole, executed by ``waptpython`` (the interpreter of the WAPT Linux agent).

It is never imported by the backend: the backend runs it as a subprocess so that signatures are produced by
WAPT's reference implementation (``waptcrypto``), the one the agents check.

Protocol: one JSON request on stdin, one JSON object per result on stdout, then exit.

    {"op": "info", "certificate": "...", "private_key": "...", "password": "..."}
        -> {"ok": true, "cn": ..., "fingerprint": ..., "not_after": ..., "code_signing": ..., "key_matches": ...}

    {"op": "sign_actions", "certificate": "...", "private_key": "...", "password": "...", "actions": [{...}]}
        -> {"ok": true, "action": {...signed...}} per action (or {"ok": false, "error": ...})

    {"op": "verify_actions", "trusted_certs": ["..."], "required_attributes": ["uuid", "action"], "actions": [...]}
        -> {"ok": true, "verified_by": ...} per action, as the agent checks it (``check_action_signature``)

    {"op": "build_packages", "certificate": "...", "private_key": "...", "password": "...", "output_dir": "...",
     "jobs": [{"control": {"package": "<host uuid>", "version": "12", "section": "host", "depends": "..."},
               "inc": true}]}
        -> {"ok": true, "package": ..., "version": ..., "path": ..., "control": {...}, "files": [...]} per job
        Host and group packages hold only a control file: built from their attributes
        (``build_management_package``, as the WAPT console does), version incremented unless ``inc`` is false,
        signed, then checked against the signer certificate. Nothing is uploaded.

    {"op": "serve", "certificate": "...", "private_key": "...", "password": "..."}
        -> {"ok": true, "ready": true, "cn": ..., "fingerprint": ...}, then one request per stdin line, until EOF:
           {"id": 1, "op": "sign_actions", "actions": [...]} -> {"id": 1, "results": [<as sign_actions>]}
        The key is decrypted once and stays in this process only: the backend keeps the process while a user has
        unlocked the key, and ends it (closing stdin) afterwards.

The passphrase only travels on stdin: never on the command line nor in the environment.
"""

import json
import os
import sys
import traceback
import zipfile

# waptpython runs with -I: PYTHONPATH is ignored and WAPT's modules (waptcrypto, waptutils...) are not on sys.path
sys.path.insert(0, os.environ.get("WAPT_BASE_DIR", "/opt/wapt"))

from waptcrypto import SSLCABundle, SSLPrivateKey, check_action_signature
from waptpackage import PackageEntry
from waptutils import is_pem_key_encrypted


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def load_signer(req):
    """Private key and certificate chain of the signer; the key must match the first certificate."""
    password = req.get("password") or None
    if password is None and is_pem_key_encrypted(req["private_key"]):
        # waptcrypto would prompt on a console this process does not have
        raise ValueError("the private key is encrypted: a passphrase is required")
    # None for an unencrypted key: waptcrypto rejects a password, even empty, for such a key
    key = SSLPrivateKey(req["private_key"], password=password)
    bundle = SSLCABundle()
    bundle.add_certificates_from_pem(pem_filename=req["certificate"], trusted=True)
    chain = bundle.certificates()
    if not chain:
        raise ValueError("no certificate in %s" % req["certificate"])
    if not chain[0].match_key(key):
        raise ValueError("the private key does not match the certificate %s" % chain[0].cn)
    return key, chain


def op_info(req):
    key, chain = load_signer(req)
    cert = chain[0]
    emit({"ok": True, "cn": cert.cn, "fingerprint": cert.fingerprint, "not_after": str(cert.not_after),
          "code_signing": bool(cert.is_code_signing), "key_matches": True})


def sign_all(key, chain, actions):
    results = []
    for action in actions or []:
        try:
            results.append({"ok": True, "action": key.sign_claim(action, signer_certificate_chain=chain)})
        except Exception as e:
            results.append({"ok": False, "uuid": action.get("uuid"), "error": "%s: %s" % (type(e).__name__, e)})
    return results


def op_sign_actions(req):
    key, chain = load_signer(req)
    for result in sign_all(key, chain, req.get("actions")):
        emit(result)


def op_serve(req):
    key, chain = load_signer(req)
    req.pop("password", None)
    emit({"ok": True, "ready": True, "cn": chain[0].cn, "fingerprint": chain[0].fingerprint})
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if request.get("op") != "sign_actions":
                raise ValueError("unsupported op %r" % request.get("op"))
            emit({"id": request.get("id"), "results": sign_all(key, chain, request.get("actions"))})
        except Exception as e:
            emit({"id": None, "error": "%s: %s" % (type(e).__name__, e)})


def op_verify_actions(req):
    bundle = SSLCABundle()
    for path in req.get("trusted_certs") or []:
        bundle.add_certificates_from_pem(pem_filename=path, trusted=True)
    required = req.get("required_attributes") or ["uuid", "action"]
    for action in req.get("actions") or []:
        try:
            emit({"ok": True, "verified_by": check_action_signature(bundle, action, required_attributes=required)})
        except Exception as e:
            emit({"ok": False, "uuid": action.get("uuid"), "error": "%s: %s" % (type(e).__name__, e)})


# control attributes kept from the stored package; signature, repository and local attributes are rebuilt
KEPT_ATTRIBUTES = set(PackageEntry.required_attributes + PackageEntry.optional_attributes) - {"package_uuid"}


def op_build_packages(req):
    key, chain = load_signer(req)
    signers = SSLCABundle()
    signers.add_certificates_from_pem(pem_filename=req["certificate"], trusted=True)
    os.makedirs(req["output_dir"], exist_ok=True)
    for job in req.get("jobs") or []:
        control = {k: v for k, v in job["control"].items() if k in KEPT_ATTRIBUTES and v not in (None, "")}
        try:
            pe = PackageEntry(package=control.pop("package"), version=str(control.pop("version", "") or "0"),
                              section=control.pop("section", "host"), **control)
            if job.get("inc", True):
                pe.inc_build()
            path = pe.build_management_package(target_directory=req["output_dir"])
            pe.sign_package(private_key=key, certificate=chain)
            check = PackageEntry(waptfile=path)
            verified_by = check.check_control_signature(trusted_bundle=signers)
            with zipfile.ZipFile(path) as z:
                files = sorted(z.namelist())
            emit({"ok": True, "package": check.package, "version": check.version, "path": path,
                  "size": os.path.getsize(path), "verified_by": verified_by.cn, "files": files,
                  "control": {k: v for k, v in check.as_dict().items() if v not in (None, "")}})
        except Exception as e:
            emit({"ok": False, "package": job["control"].get("package"), "error": "%s: %s" % (type(e).__name__, e),
                  "trace": traceback.format_exc()})


OPS = {"info": op_info, "sign_actions": op_sign_actions, "verify_actions": op_verify_actions,
       "build_packages": op_build_packages, "serve": op_serve}


def main():
    try:
        # serve mode keeps reading stdin: only its first line is the request
        req = json.loads(sys.stdin.readline())
        OPS[req["op"]](req)
    except Exception as e:
        emit({"ok": False, "fatal": True, "error": "%s: %s" % (type(e).__name__, e), "trace": traceback.format_exc()})
        sys.exit(1)


if __name__ == "__main__":
    main()
