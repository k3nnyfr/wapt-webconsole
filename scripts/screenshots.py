"""Regenerate the documentation screenshots (docs/images) from the demo server, with headless Chrome or Chromium.

    (cd frontend && npm run build) && python3 scripts/screenshots.py

The data is fictional (scripts/demo_server.py). Chrome is looked up in $CHROME, then in the PATH, then on the
Windows side when run from WSL.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
WINDOWS_CHROME = [
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]
PHONE_W, PHONE_H = 412, 860


def phones(*srcs: str) -> str:
    return f"/frames?w={PHONE_W}&h={PHONE_H}&" + "&".join(f"src={quote(s, safe='')}" for s in srcs)


# image -> (path, window size)
SHOTS = {
    "hosts.png": ("/?shot=hosts-selection", "1440,820"),
    "hosts-menu.png": ("/?shot=hosts-menu", "1440,1000"),
    "host-detail.png": ("/hosts/demo-0002", "1440,900"),
    "host-tasks.png": ("/hosts/demo-0002?shot=host-tasks", "1440,760"),
    "assign.png": ("/hosts/demo-0002?shot=assign", "1440,940"),
    "packages.png": ("/packages", "1440,640"),
    "group.png": ("/groups/grp-base", "1440,820"),
    "cleanup.png": ("/packages?shot=cleanup", "1440,700"),
    "journal.png": ("/journal", "1440,560"),
    "store.png": ("/store", "1440,560"),
    "store-plan.png": ("/store?shot=store-plan", "1440,760"),
    "unlock.png": ("/?shot=unlock", "1440,720"),
    "mobile.png": (phones("/", "/hosts/demo-0002", "/?shot=phone-menu"),
                   f"{3 * (PHONE_W + 2) + 2 * 24 + 40},{PHONE_H + 42}"),
}


def find_chrome() -> str:
    for candidate in [os.environ.get("CHROME"), shutil.which("chromium"), shutil.which("chromium-browser"),
                      shutil.which("google-chrome"), *WINDOWS_CHROME]:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("Chrome or Chromium not found: set $CHROME")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def main() -> None:
    if not (demo_server.DIST / "index.html").exists():
        sys.exit("frontend/dist is missing: run `npm run build` in frontend/ first")
    chrome = find_chrome()
    on_windows = chrome.endswith(".exe")
    if on_windows:   # a Windows browser writes on the Windows side: work in the Windows temporary directory
        temp = subprocess.run(["cmd.exe", "/c", "echo %TEMP%"], capture_output=True, text=True, cwd="/mnt/c")
        base = Path(run(["wslpath", "-u", temp.stdout.strip()]))
    else:
        base = Path(tempfile.gettempdir())
    work = Path(tempfile.mkdtemp(prefix="wwc-shots-", dir=base))
    native = (lambda p: run(["wslpath", "-w", str(p)])) if on_windows else str

    port = free_port()
    server = demo_server.serve(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    IMAGES.mkdir(parents=True, exist_ok=True)
    try:
        for name, (path, size) in SHOTS.items():
            target = work / name
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1", "--virtual-time-budget=9000",
                            f"--user-data-dir={native(work / 'profile')}", f"--window-size={size}",
                            f"--screenshot={native(target)}", f"http://localhost:{port}{path}"],
                           capture_output=True, timeout=120)
            if not target.exists():
                sys.exit(f"{name}: no screenshot written")
            shutil.copyfile(target, IMAGES / name)
            print(f"docs/images/{name}")
    finally:
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
