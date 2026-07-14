#!/usr/bin/env python3
"""Real-time collaboration test: two browser tabs editing the same doc converge.

Drives two headless-browser tabs against a running stack, has each type at a
different position concurrently, and asserts both editors end up identical and
contain both edits (the OT convergence property).

IMPORTANT: the browser opens the live-sync websocket to WEBSOCKET_URL directly,
so the page host must match that host (else the session cookie isn't sent to
real-time and the connection is rejected). Point FLEETEX_URL at the same host the
stack advertises:

    FLEETEX_URL=http://localhost:3000 python services/realtime_collab_test.py     # default WEBSOCKET_URL
    FLEETEX_URL=http://192.168.50.21:3000 python services/realtime_collab_test.py  # LAN advertise-host

Requires: pip install playwright httpx && playwright install chromium
"""
from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ.get("FLEETEX_URL", "http://localhost:3000")
HOST = urlparse(BASE).hostname
TRIALS = int(os.environ.get("TRIALS", "3"))


def _one_trial(pw, t: int) -> bool:
    c = httpx.Client(base_url=BASE, timeout=40, follow_redirects=True)
    c.post("/register", json={"email": f"collab{t}+{int(time.time())}@example.com", "password": "collab-pass-123"})
    pid = c.post("/project/new", json={"projectName": f"Collab {t}"}).json()["project_id"]
    cookie = c.cookies.get("overleaf.sid")

    ctx = pw.chromium.launch().new_context()
    ctx.add_cookies([{"name": "overleaf.sid", "value": cookie, "domain": HOST, "path": "/"}])
    a, b = ctx.new_page(), ctx.new_page()
    for p in (a, b):
        p.goto(f"{BASE}/project/{pid}")
        p.wait_for_selector("#ed:not([disabled])", timeout=15000)
    time.sleep(2.5)  # let live-sync connect (upgradeLive retries until joined)

    # concurrent edits at different positions
    a.focus("#ed"); a.press("#ed", "End"); a.type("#ed", " <FROM-A>", delay=30)
    b.focus("#ed"); b.press("#ed", "Home"); b.type("#ed", "<FROM-B> ", delay=30)
    time.sleep(4)

    av, bv = a.input_value("#ed"), b.input_value("#ed")
    ctx.browser.close()
    ok = av == bv and "FROM-A" in av and "FROM-B" in av
    print(f"  trial {t}: converged={av == bv}  both-edits={'FROM-A' in av and 'FROM-B' in av}")
    return ok


def main():
    print(f"real-time collab test against {BASE} (cookie host {HOST})")
    with sync_playwright() as pw:
        passed = sum(_one_trial(pw, t) for t in range(TRIALS))
    print(f"\n{passed}/{TRIALS} trials converged with both edits present")
    if passed == TRIALS:
        print("🎉 real-time collaboration converges")
        sys.exit(0)
    print("❌ real-time collaboration did not reliably converge")
    sys.exit(1)


if __name__ == "__main__":
    main()
