"""LaTeX command construction + the pluggable command runner.

``build_latex_command`` is a faithful port of LatexRunner._buildLatexCommand and
is fully testable. ``LocalCommandRunner`` actually shells out to ``latexmk`` (etc.)
— UNVERIFIED in Fleetex CI (no TeX installed); tests inject a fake runner.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

# latexmk flag per compiler (LatexRunner.COMPILER_FLAGS).
COMPILER_FLAGS = {
    "latex": "-pdfdvi",
    "lualatex": "-lualatex",
    "pdflatex": "-pdf",
    "xelatex": "-xelatex",
}

# Root files in these formats are compiled via their generated .tex.
_REWRITE_TO_TEX = (".Rtex", ".md", ".Rmd", ".Rnw")


def main_tex_file(root_resource_path: str) -> str:
    base, ext = os.path.splitext(root_resource_path)
    if ext in _REWRITE_TO_TEX:
        return base + ".tex"
    return root_resource_path


def build_latex_command(main_file: str, compile_dir: str, parsed) -> list[str]:
    argv = [
        "latexmk",
        "-cd",
        "-jobname=output",
        f"-auxdir={compile_dir}",
        f"-outdir={compile_dir}",
        "-synctex=1",
        "-interaction=batchmode",
        "-time",
        "-halt-on-error" if parsed.stop_on_first_error else "-f",
    ]
    argv += list(parsed.flags)
    argv.append(COMPILER_FLAGS[parsed.compiler])
    argv.append(os.path.join(compile_dir, main_file))
    return argv


@dataclass
class RunResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    terminated: bool = False


class CommandRunner:
    def run(self, command: list[str], cwd: str, timeout: float, env: dict | None = None) -> RunResult:
        raise NotImplementedError


class LocalCommandRunner(CommandRunner):
    """Shells out to the real binary. Requires a TeX toolchain; unverified in CI."""

    def run(self, command, cwd, timeout, env=None):
        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        try:
            proc = subprocess.run(
                command, cwd=cwd, timeout=timeout, capture_output=True, text=True, env=run_env
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(exit_code=-1, stdout=exc.stdout or "", timed_out=True)
        except FileNotFoundError:
            # Binary (latexmk/synctex/texcount) not installed.
            return RunResult(exit_code=127, stderr=f"{command[0]}: not found")
        return RunResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
