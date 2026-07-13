"""End-to-end HTTP tests using the fake toolchain (no TeX needed)."""

from __future__ import annotations

from fleetex_service_kit.contract import call_asgi

PID = "proj-123_ABC"
UID = "600000000000000000000001"
BODY = {"compile": {"options": {"compiler": "pdflatex"}, "rootResourcePath": "main.tex",
                    "resources": [{"path": "main.tex", "content": "\\documentclass{article}\\begin{document}hi\\end{document}"}]}}


async def test_status_endpoints(app):
    s = await call_asgi(app, "GET", "/status")
    assert s.status == 200 and s.text == "CLSI is alive\n"
    ps = await call_asgi(app, "GET", f"/project/{PID}/status")
    assert ps.status == 200 and ps.text == "OK"


async def test_compile_success(app):
    r = await call_asgi(app, "POST", f"/project/{PID}/compile", json=BODY)
    assert r.status == 200
    compile = r.json["compile"]
    assert compile["status"] == "success"
    assert compile["buildId"]
    pdf = next(f for f in compile["outputFiles"] if f["path"] == "output.pdf")
    assert pdf["type"] == "pdf" and pdf["size"] > 0
    assert pdf["url"] == f"http://dl.example/project/{PID}/build/{pdf['build']}/output/output.pdf"
    # log file is also an output
    assert any(f["path"] == "output.log" for f in compile["outputFiles"])


async def test_compile_with_user_id_in_url(app):
    r = await call_asgi(app, "POST", f"/project/{PID}/user/{UID}/compile", json=BODY)
    pdf = next(f for f in r.json["compile"]["outputFiles"] if f["path"] == "output.pdf")
    assert pdf["url"] == f"http://dl.example/project/{PID}/user/{UID}/build/{pdf['build']}/output/output.pdf"


async def test_compile_failure_when_no_pdf(config):
    from fleetex_clsi.app import build_app
    from tests.conftest import FakeToolchain  # type: ignore

    app = build_app(config, runner=FakeToolchain(produce_pdf=False))
    r = await call_asgi(app, "POST", f"/project/{PID}/compile", json=BODY)
    assert r.json["compile"]["status"] == "failure"


async def test_invalid_project_id_500(app):
    r = await call_asgi(app, "POST", "/project/bad!id/compile", json=BODY)
    assert r.status == 500


async def test_stop_and_clear(app):
    await call_asgi(app, "POST", f"/project/{PID}/compile", json=BODY)
    assert (await call_asgi(app, "POST", f"/project/{PID}/compile/stop")).status == 204
    assert (await call_asgi(app, "DELETE", f"/project/{PID}")).status == 204


async def test_synctex_and_wordcount(app):
    # compile first so output.synctex.gz exists
    await call_asgi(app, "POST", f"/project/{PID}/compile", json=BODY)
    code = await call_asgi(app, "GET", f"/project/{PID}/sync/code", params={"file": "main.tex", "line": 3, "column": 1})
    assert code.json["pdf"] == [{"page": 1, "h": 100.5, "v": 200.5, "width": 300.0, "height": 10.0}]
    pdf = await call_asgi(app, "GET", f"/project/{PID}/sync/pdf", params={"page": 1, "h": 100.0, "v": 200.0})
    assert pdf.json["code"] == [{"file": "main.tex", "line": 3, "column": -1}]
    wc = await call_asgi(app, "GET", f"/project/{PID}/wordcount", params={"file": "main.tex"})
    assert wc.json["texcount"]["textWords"] == 42


async def test_output_file_serving(app):
    import os
    # place a compiled output where save_output_files would put it, then fetch it
    build = "abc123-def456"
    out_dir = os.path.join(app.state.manager.output_dir(PID), "generated-files", build)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "output.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.5 compiled")
    r = await call_asgi(app, "GET", f"/project/{PID}/build/{build}/output/output.pdf")
    assert r.status == 200 and r.text == "%PDF-1.5 compiled"
    missing = await call_asgi(app, "GET", f"/project/{PID}/build/{build}/output/nope.pdf")
    assert missing.status == 404


async def test_synctex_404_without_output(app):
    # no compile yet -> output.synctex.gz missing -> 404
    r = await call_asgi(app, "GET", f"/project/{PID}/sync/code", params={"file": "main.tex", "line": 1, "column": 1})
    assert r.status == 404
