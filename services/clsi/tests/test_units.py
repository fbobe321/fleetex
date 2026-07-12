"""Unit tests for the pure/reproducible pieces (no TeX needed)."""

from __future__ import annotations

import os

import pytest

from fleetex_clsi.errors import AlreadyCompilingError, InvalidRequestError, TooManyCompileRequestsError
from fleetex_clsi.latex_runner import RunResult, build_latex_command, main_tex_file
from fleetex_clsi.lock_manager import LockManager
from fleetex_clsi.output_files import find_output_files, save_output_files
from fleetex_clsi.parsers import parse_edit_output, parse_view_output, parse_wordcount
from fleetex_clsi.request_parser import parse
from fleetex_clsi.resource_writer import ResourceWriter


# --- request parser ------------------------------------------------------ #
def test_parse_defaults():
    p = parse({"compile": {"resources": [{"path": "main.tex", "content": "x"}]}})
    assert p.compiler == "pdflatex"
    assert p.timeout_ms == 600_000
    assert p.root_resource_path == "main.tex"
    assert len(p.resources) == 1 and p.resources[0].content == "x"


def test_parse_timeout_capped_and_ms():
    p = parse({"compile": {"options": {"timeout": 9999}}})
    assert p.timeout_ms == 600_000  # capped at 600s -> ms


def test_parse_rejects_bad_compiler_and_dotdot():
    with pytest.raises(InvalidRequestError):
        parse({"compile": {"options": {"compiler": "wordstar"}}})
    with pytest.raises(InvalidRequestError):
        parse({"compile": {"resources": [{"path": "../evil.tex", "content": "x"}]}})


# --- latex command ------------------------------------------------------- #
def test_build_latex_command_pdflatex():
    p = parse({"compile": {"options": {"compiler": "pdflatex"}}})
    argv = build_latex_command("main.tex", "/c", p)
    assert argv[0] == "latexmk"
    assert "-pdf" in argv and "-f" in argv and "-synctex=1" in argv
    assert argv[-1] == "/c/main.tex"
    assert "-auxdir=/c" in argv and "-outdir=/c" in argv


def test_build_latex_command_engines_and_halt():
    for compiler, flag in [("xelatex", "-xelatex"), ("lualatex", "-lualatex"), ("latex", "-pdfdvi")]:
        p = parse({"compile": {"options": {"compiler": compiler, "stopOnFirstError": True}}})
        argv = build_latex_command("main.tex", "/c", p)
        assert flag in argv
        assert "-halt-on-error" in argv and "-f" not in argv


def test_main_tex_file_rewrites():
    assert main_tex_file("main.Rtex") == "main.tex"
    assert main_tex_file("main.md") == "main.tex"
    assert main_tex_file("main.tex") == "main.tex"


# --- resource writer ----------------------------------------------------- #
def test_resource_writer_writes_and_cleans(tmp_path):
    base = str(tmp_path / "c")
    os.makedirs(base)
    open(os.path.join(base, "stale.tex"), "w").write("old")
    open(os.path.join(base, "output.pdf"), "wb").write(b"old pdf")
    p = parse({"compile": {"options": {"syncState": "s1"}, "resources": [{"path": "main.tex", "content": "hi"}]}})
    ResourceWriter(base).sync_resources_to_disk(p)
    assert open(os.path.join(base, "main.tex")).read() == "hi"
    assert not os.path.exists(os.path.join(base, "stale.tex"))  # extraneous removed
    assert not os.path.exists(os.path.join(base, "output.pdf"))  # force-deleted
    assert "stateHash:s1" in open(os.path.join(base, ".project-sync-state")).read()


def test_resource_writer_rejects_escape(tmp_path):
    base = str(tmp_path / "c")
    os.makedirs(base)
    from fleetex_clsi.request_parser import ParsedRequest, Resource

    p = ParsedRequest(resources=[Resource(path="../escape.tex", content="x")])
    with pytest.raises(InvalidRequestError):
        ResourceWriter(base).sync_resources_to_disk(p)


# --- output files -------------------------------------------------------- #
def test_find_and_save_output_files(tmp_path):
    cdir = str(tmp_path / "c")
    odir = str(tmp_path / "o")
    os.makedirs(cdir)
    open(os.path.join(cdir, "main.tex"), "w").write("input")
    open(os.path.join(cdir, "output.pdf"), "wb").write(b"%PDF fake")
    open(os.path.join(cdir, "output.log"), "w").write("log")
    files = find_output_files(cdir, {"main.tex"})
    paths = {f["path"] for f in files}
    assert paths == {"output.pdf", "output.log"}  # input excluded
    saved = save_output_files(odir, files, cdir, "abc-123")
    pdf = next(f for f in saved if f["path"] == "output.pdf")
    assert pdf["build"] == "abc-123" and pdf["size"] > 0
    assert pdf["type"] == "pdf"
    assert os.path.isfile(os.path.join(odir, "generated-files", "abc-123", "output.pdf"))


# --- parsers ------------------------------------------------------------- #
def test_parse_view_output():
    out = "Output:x\nPage:2\nh:100.5\nv:200.25\nW:300.0\nH:12.5\n"
    assert parse_view_output(out) == [{"page": 2, "h": 100.5, "v": 200.25, "width": 300.0, "height": 12.5}]


def test_parse_edit_output_relativizes(tmp_path):
    base = str(tmp_path)
    abs_input = os.path.join(base, "main.tex")
    out = f"Output:x\nInput:{abs_input}\nLine:3\nColumn:-1\n"
    assert parse_edit_output(out, base) == [{"file": "main.tex", "line": 3, "column": -1}]


def test_parse_wordcount():
    out = "Encoding: ascii\nWords in text: 42\nWords in headers: 5\n"
    wc = parse_wordcount(out)
    assert wc["encode"] == "ascii" and wc["textWords"] == 42 and wc["headWords"] == 5


# --- lock manager -------------------------------------------------------- #
def test_lock_manager_double_acquire_raises():
    lm = LockManager()
    with lm.acquire("/c/proj"):
        with pytest.raises(AlreadyCompilingError):
            with lm.acquire("/c/proj"):
                pass
    # released after context — can re-acquire
    with lm.acquire("/c/proj"):
        pass


def test_lock_manager_concurrency_limit():
    lm = LockManager(concurrency_limit=1)
    with lm.acquire("/c/a"):
        with pytest.raises(TooManyCompileRequestsError):
            with lm.acquire("/c/b"):
                pass


# --- LocalCommandRunner plumbing (real subprocess, no TeX) ---------------- #
def test_local_runner_captures_output_and_exit(tmp_path):
    import sys

    from fleetex_clsi.latex_runner import LocalCommandRunner

    runner = LocalCommandRunner()
    ok = runner.run([sys.executable, "-c", "print('hello')"], cwd=str(tmp_path), timeout=10)
    assert ok.exit_code == 0 and ok.stdout.strip() == "hello"
    bad = runner.run([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=str(tmp_path), timeout=10)
    assert bad.exit_code == 3


def test_local_runner_missing_binary_returns_127(tmp_path):
    from fleetex_clsi.latex_runner import LocalCommandRunner

    result = LocalCommandRunner().run(["definitely-not-a-real-binary-xyz"], cwd=str(tmp_path), timeout=5)
    assert result.exit_code == 127
