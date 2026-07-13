#!/usr/bin/env python3
"""Full-stack smoke test — drives the running docker-compose stack over HTTP.

Proves the containers build, start, and interoperate end to end: registration,
project creation, doc save, version history (timeline + live-buffer diff), a real
LaTeX compile to PDF, and real-time liveness. Meant to run against the published
host ports (web:3000, real-time:3026). Exits non-zero on the first failure.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

WEB = os.environ.get("WEB_URL", "http://localhost:3000")
RT = os.environ.get("REALTIME_URL", "http://localhost:3026")


def wait_for(url: str, name: str, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
                print(f"  ✓ {name} is up ({url} -> {r.status_code})")
                return
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(2)
    raise SystemExit(f"  ✗ {name} never came up at {url} ({last})")


def main() -> None:
    print("Waiting for services…")
    wait_for(f"{WEB}/status", "web")
    wait_for(f"{RT}/health_check", "real-time")

    c = httpx.Client(base_url=WEB, timeout=90, follow_redirects=True)

    email = f"smoke+{int(time.time())}@example.com"
    r = c.post("/register", json={"email": email, "password": "smoke-pass-123"})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    print(f"  ✓ registered + logged in as {email}")

    r = c.post("/project/new", json={"projectName": "Smoke Project"})
    assert r.status_code == 200, f"create project failed: {r.status_code} {r.text}"
    pid = r.json()["project_id"]
    print(f"  ✓ created project {pid}")

    boot = c.get(f"/project/{pid}?format=json").json()
    did = boot.get("rootDocId")
    assert did, f"no rootDocId in boot: {boot}"
    print(f"  ✓ editor bootstrap ok (root doc {did})")

    latex = "\\documentclass{article}\\begin{document}Hello from the Fleetex smoke test.\\end{document}"
    r = c.post(f"/project/{pid}/doc/{did}", json={"content": latex})
    assert r.status_code in (200, 204), f"save doc failed: {r.status_code} {r.text}"

    r = c.post(f"/project/{pid}/doc/{did}/history/version", json={"content": latex, "source": "save"})
    assert r.status_code in (200, 201), f"record version failed: {r.status_code} {r.text}"
    versions = c.get(f"/project/{pid}/doc/{did}/history").json()["versions"]
    assert versions, f"no versions recorded: {versions}"
    v = versions[-1]["version"]
    print(f"  ✓ history version recorded (v{v}); timeline has {len(versions)}")

    d = c.post(f"/project/{pid}/doc/{did}/history/diff-against/{v}", json={"content": latex + " Plus an unsaved edit."}).json()
    assert d.get("to") == "current" and any("i" in s for s in d.get("diff", [])), f"live diff wrong: {d}"
    print("  ✓ live-buffer diff computed")

    print("Compiling (real LaTeX via clsi)…")
    r = c.post(f"/project/{pid}/compile")
    assert r.status_code == 200, f"compile request failed: {r.status_code} {r.text}"
    comp = r.json().get("compile", {})
    pdf = next((f for f in comp.get("outputFiles", []) if f.get("path") == "output.pdf"), None)
    assert comp.get("status") == "success" and pdf, f"compile did not succeed: {comp}"
    pdf_bytes = c.get(pdf["url"]).content
    assert pdf_bytes[:4] == b"%PDF", f"output is not a PDF: {pdf_bytes[:20]!r}"
    print(f"  ✓ compiled a real PDF ({len(pdf_bytes)} bytes) and fetched it via the web proxy")

    print("\n🎉 full-stack smoke test PASSED")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"\n✗ SMOKE TEST FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
