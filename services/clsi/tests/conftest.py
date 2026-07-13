"""Fixtures: a fake command runner that simulates the TeX toolchain, so the whole
compile/synctex/wordcount orchestration is testable without a TeX install."""

from __future__ import annotations

import os

import pytest

from fleetex_clsi.app import build_app
from fleetex_clsi.config import ClsiConfig
from fleetex_clsi.latex_runner import CommandRunner, RunResult


class FakeToolchain(CommandRunner):
    """Simulates latexmk/synctex/texcount by writing plausible outputs."""

    def __init__(self, produce_pdf: bool = True) -> None:
        self.produce_pdf = produce_pdf
        self.calls: list = []
        self.envs: list = []

    def run(self, command, cwd, timeout, env=None):
        self.calls.append(command)
        self.envs.append(env)
        tool = command[0]
        if tool == "latexmk":
            open(os.path.join(cwd, "output.log"), "w").write("log")
            open(os.path.join(cwd, "output.synctex.gz"), "wb").write(b"synctex")
            if self.produce_pdf:
                with open(os.path.join(cwd, "output.pdf"), "wb") as fh:
                    fh.write(b"%PDF-1.5 fake pdf content")
            return RunResult(exit_code=0, stdout="Run number 1 of pdflatex")
        if tool == "synctex":
            if command[1] == "view":
                return RunResult(0, stdout="Output:x\nPage:1\nh:100.5\nv:200.5\nW:300.0\nH:10.0\n")
            return RunResult(0, stdout="Output:x\nInput:main.tex\nLine:3\nColumn:-1\n")
        if tool == "texcount":
            return RunResult(0, stdout="Encoding: ascii\nWords in text: 42\nWords in headers: 5\n")
        return RunResult(127, stderr="unknown tool")


@pytest.fixture
def config(tmp_path):
    return ClsiConfig(
        compiles_dir=str(tmp_path / "compiles"),
        output_dir=str(tmp_path / "output"),
        cache_dir=str(tmp_path / "cache"),
        download_host="http://dl.example",
    )


@pytest.fixture
def runner():
    return FakeToolchain()


@pytest.fixture
def app(config, runner):
    return build_app(config, runner=runner)
