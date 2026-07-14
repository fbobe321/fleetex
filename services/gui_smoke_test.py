#!/usr/bin/env python3
"""Headless-browser GUI smoke test for the Fleetex editor.

Drives the REAL editor in a headless Chromium against a running stack and checks
the things that pure-HTTP tests can't see: that the editor page's JavaScript
actually opens a doc, autosaves, compiles, reflects typed text in the PDF, and
that the Save/Delete buttons work. This is how client-side bugs (e.g. an element
id colliding with a JS global) get caught without a human clicking around.

Run:
    pip install playwright httpx && playwright install chromium
    # start the stack (docker compose up / fleetex up), then:
    python services/gui_smoke_test.py            # against http://localhost:3000
    FLEETEX_URL=http://host:3000 python services/gui_smoke_test.py

Exits non-zero if any check fails. Requires `pdftotext` (poppler-utils) to verify
the compiled PDF text.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ.get("FLEETEX_URL", "http://localhost:3000")
MARK = f"GUI-MARKER-{int(time.time())}"


def _setup():
    c = httpx.Client(base_url=BASE, timeout=30, follow_redirects=True)
    r = c.post("/register", json={"email": f"gui+{int(time.time())}@example.com", "password": "gui-pass-123"})
    assert r.status_code == 200, f"register failed: {r.text}"
    pid = c.post("/project/new", json={"projectName": "GUI Smoke"}).json()["project_id"]
    # a second doc to exercise delete
    did2 = c.post(f"/project/{pid}/doc", json={"name": "chapter.tex"}).json().get("_id")
    return pid, did2, c.cookies.get("overleaf.sid")


def _pdf_text(url, cookie):
    data = httpx.get(url, cookies={"overleaf.sid": cookie}, timeout=30).content
    if data[:4] != b"%PDF":
        return ""
    p = tempfile.mktemp(suffix=".pdf")
    open(p, "wb").write(data)
    txt = subprocess.run(["pdftotext", p, "-"], capture_output=True, text=True).stdout
    os.remove(p)
    return txt


def main():
    pid, did2, cookie = _setup()
    print(f"setup: project {pid}")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies([{"name": "overleaf.sid", "value": cookie, "url": BASE}])
        page = ctx.new_page()
        dialog_value = {"v": ""}  # prompt() answers; confirm() ignores the value
        page.on("dialog", lambda d: d.accept(dialog_value["v"]))
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"PAGEERROR: {e}"))

        page.goto(f"{BASE}/project/{pid}")
        page.wait_for_selector("#ed:not([disabled])", timeout=15000)
        page.wait_for_function("document.querySelector('#ed').value.includes('documentclass')", timeout=15000)
        check("editor opens root doc with content", "documentclass" in page.input_value("#ed"),
              page.eval_on_selector("#cur", "e=>e.textContent"))

        # the Save button must actually be enabled (regression: id=save vs save())
        check("Save button is enabled after open", not page.get_attribute("#savebtn", "disabled") == "",
              f"disabled={page.get_attribute('#savebtn', 'disabled')}")

        # create a folder in the file tree via the New folder button
        fname = "chapters" + str(int(time.time()))[-4:]
        dialog_value["v"] = fname
        page.click("button:has-text('New folder')")
        try:
            page.wait_for_function(
                "[...document.querySelectorAll('.tree .folder')].some(e=>e.textContent.includes('%s'))" % fname,
                timeout=8000)
            made = True
        except Exception:
            made = False
        dialog_value["v"] = ""
        check("New folder creates a folder in the tree", made, fname)
        check("empty folder shows an (empty) hint", page.eval_on_selector_all(".tree .emptyfolder", "e=>e.length") >= 1)

        body = "\\documentclass{article}\n\\begin{document}\n" + MARK + "\n\\end{document}\n"
        page.fill("#ed", body)
        autosaved = _wait_status(page, "Saved")
        check("autosave fires after typing", autosaved, page.eval_on_selector("#statusmsg", "e=>e.textContent"))

        page.click("#compileBtn")
        compiled = _wait_text(page, "#pdfstatus", "compiled", 30000)
        check("compile succeeds", compiled, page.eval_on_selector("#pdfstatus", "e=>e.textContent"))

        pdfurl = page.eval_on_selector("#pdfdl", "e=>e.getAttribute('href')")
        txt = _pdf_text(BASE + pdfurl, cookie) if pdfurl else ""
        check("compiled PDF reflects typed text", MARK in txt, "marker " + ("FOUND" if MARK in txt else "MISSING"))

        page.fill("#ed", body.replace(MARK, MARK + "-2"))
        page.click("#savebtn")
        check("Save button works", _wait_status(page, "Saved"), page.eval_on_selector("#statusmsg", "e=>e.textContent"))

        # drag the editor|preview divider RIGHT (the direction that used to stick
        # because the cursor passed over the PDF iframe) and confirm the editor
        # column actually grows.
        def editor_col_px():
            cols = page.eval_on_selector("#editorEl", "e=>getComputedStyle(e).gridTemplateColumns")
            return float(cols.split()[2].replace("px", ""))  # tree gutter EDITOR gutter pdf
        w0 = editor_col_px()
        box = page.locator("#g2").bounding_box()
        page.mouse.move(box["x"] + 3, box["y"] + box["height"] / 2)
        page.mouse.down()
        for dx in range(0, 260, 20):  # sweep rightward over the iframe
            page.mouse.move(box["x"] + 3 + dx, box["y"] + box["height"] / 2)
        page.mouse.up()
        w1 = editor_col_px()
        check("dragging divider RIGHT widens the editor (over the iframe)", w1 > w0 + 100, f"{w0:.0f}px -> {w1:.0f}px")

        page.click("#pdftoggle")
        check("Hide preview toggles pdf pane", page.eval_on_selector(".editor", "e=>e.classList.contains('nopdf')"))
        page.click("#pdftoggle")  # show preview again for the log-panel check

        # deliberate LaTeX error -> the Logs panel should show a parsed error
        page.fill("#ed", "\\documentclass{article}\n\\begin{document}\n\\undefinedcommand\n\\end{document}\n")
        page.click("#compileBtn")
        page.wait_for_function("document.querySelector('#pdfpane').classList.contains('showlog')", timeout=30000)
        errcount = page.eval_on_selector_all(".logitem.error", "els=>els.length")
        errtext = page.eval_on_selector(".logview", "e=>e.textContent") if errcount else ""
        check("compile error shows in the Logs panel", errcount >= 1,
              f"{errcount} error(s); e.g. {errtext[:60]!r}")

        # delete the second doc via the tree + Delete button
        page.click(f".file[data-id='{did2}']")
        page.wait_for_timeout(500)
        page.click("#delbtn")
        page.wait_for_timeout(800)
        gone = page.eval_on_selector_all(".file", "els=>els.every(e=>e.getAttribute('data-id')!=='%s')" % did2)
        check("delete removes the doc from the tree", gone)

        # persistence: reopen the remaining doc (delete closed it), save a final
        # known doc, then reload the whole page (like leaving and reopening the
        # project) and confirm it is still there
        page.click(".file[data-type='doc']")  # a doc (folders also render as .file now)
        page.wait_for_selector("#ed:not([disabled])", timeout=10000)
        page.wait_for_function("!document.querySelector('#savebtn').disabled", timeout=10000)
        final = "\\documentclass{article}\n\\begin{document}\n" + MARK + "-FINAL\n\\end{document}\n"
        page.fill("#ed", final)
        page.click("#savebtn")
        _wait_status(page, "Saved")
        page.reload()
        page.wait_for_selector("#ed:not([disabled])", timeout=15000)
        page.wait_for_function("document.querySelector('#ed').value.length>0", timeout=15000)
        reopened = page.input_value("#ed")
        check("saved edit persists across a reload", (MARK + "-FINAL") in reopened,
              "marker " + ("FOUND" if (MARK + "-FINAL") in reopened else "MISSING"))

        # put a doc INSIDE the folder: select the folder, then New doc -> it
        # should render nested (indented) under the folder
        page.click(".tree .folder")
        dialog_value["v"] = "inside.tex"
        page.click("button:has-text('New doc')")
        try:
            page.wait_for_function(
                "[...document.querySelectorAll(\".tree .file[data-type='doc']\")]"
                ".some(e=>e.textContent.includes('inside.tex') && parseInt(getComputedStyle(e).paddingLeft)>10)",
                timeout=8000)
            nested = True
        except Exception:
            nested = False
        dialog_value["v"] = ""
        check("a doc created inside a folder is nested under it", nested, "inside.tex indented")

        browser.close()
        if console_errors:
            print("\nBROWSER CONSOLE ERRORS:")
            for e in console_errors[:10]:
                print("  " + e)

    print("\n=== GUI SMOKE RESULTS ===")
    allok = True
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        allok = allok and ok
    print("\n" + ("🎉 ALL GUI CHECKS PASSED" if allok else "❌ SOME GUI CHECKS FAILED"))
    sys.exit(0 if allok else 1)


def _wait_status(page, text, timeout=8000):
    try:
        page.wait_for_function(f"document.querySelector('#statusmsg').textContent.includes('{text}')", timeout=timeout)
        return True
    except Exception:
        return False


def _wait_text(page, sel, text, timeout=8000):
    try:
        page.wait_for_function(f"document.querySelector('{sel}').textContent.includes('{text}')", timeout=timeout)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
