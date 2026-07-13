"""Compile sandboxing: dangerous flags rejected, TeX locked down at run time."""

from __future__ import annotations

import pytest

from fleetex_clsi.compile_manager import CompileManager
from fleetex_clsi.errors import InvalidRequestError
from fleetex_clsi.latex_runner import sandbox_env
from fleetex_clsi.request_parser import ParsedRequest, Resource, parse

from conftest import FakeToolchain


def _body(flags):
    return {"compile": {"rootResourcePath": "main.tex", "options": {"flags": flags},
                        "resources": [{"path": "main.tex", "content": "hi"}]}}


@pytest.mark.parametrize("flag", [
    "-shell-escape", "--shell-escape", "-enable-write18", "-shell_escape",
    "-output-directory=/etc", "-cnf-line=shell_escape=t", "-jobname=x",
])
def test_dangerous_flags_rejected(flag):
    with pytest.raises(InvalidRequestError):
        parse(_body([flag]))


def test_nonoption_flag_rejected():
    with pytest.raises(InvalidRequestError):
        parse(_body(["/etc/passwd"]))


def test_safe_flags_pass():
    parsed = parse(_body(["-shell-restricted", "-file-line-error"]))
    assert parsed.flags == ["-shell-restricted", "-file-line-error"]


def test_sandbox_env_disables_shell_escape():
    env = sandbox_env()
    assert env["shell_escape"] == "f"
    assert env["openin_any"] == "p"
    assert env["openout_any"] == "p"


def test_compile_passes_sandbox_env_to_runner(config):
    runner = FakeToolchain()
    mgr = CompileManager(config, runner=runner)
    parsed = ParsedRequest(root_resource_path="main.tex", resources=[Resource(path="main.tex", content="hi")])
    mgr.run_compile("proj1", "user1", parsed)
    # the latexmk invocation must carry the locked-down environment
    assert runner.envs and runner.envs[0]["shell_escape"] == "f"
