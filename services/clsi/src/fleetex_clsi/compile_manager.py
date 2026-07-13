"""CompileManager — orchestration (port of CompileManager.js core flow).

Ties together resource writing, the latexmk run (via the injected runner), output
discovery, and build-dir caching into a CompileResult. Also drives synctex and
wordcount (which shell out via the same runner).
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field

from .config import ClsiConfig
from .errors import NotFoundError
from .latex_runner import CommandRunner, LocalCommandRunner, build_latex_command, main_tex_file, sandbox_env
from .lock_manager import LockManager
from .output_files import find_output_files, generate_build_id, save_output_files
from .parsers import parse_edit_output, parse_view_output, parse_wordcount
from .request_parser import ParsedRequest
from .resource_writer import ResourceWriter

_DRAFT_PREFIX = (
    "\\PassOptionsToPackage{draft}{graphicx}"
    "\\PassOptionsToPackage{draft}{graphics}\n"
)


@dataclass
class CompileResult:
    status: str
    output_files: list = field(default_factory=list)
    build_id: str = ""
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)


class CompileManager:
    def __init__(self, config: ClsiConfig, runner: CommandRunner | None = None) -> None:
        self.config = config
        self.runner = runner or LocalCommandRunner()
        self.locks = LockManager(config.compile_concurrency_limit)

    # -- paths ------------------------------------------------------------ #
    def compile_name(self, project_id: str, user_id: str | None) -> str:
        return f"{project_id}-{user_id}" if user_id else project_id

    def compile_dir(self, name: str) -> str:
        return os.path.join(self.config.compiles_dir, name)

    def output_dir(self, name: str) -> str:
        return os.path.join(self.config.output_dir, name)

    # -- compile ---------------------------------------------------------- #
    def run_compile(self, project_id: str, user_id: str | None, parsed: ParsedRequest) -> CompileResult:
        name = self.compile_name(project_id, user_id)
        cdir = self.compile_dir(name)
        odir = self.output_dir(name)
        os.makedirs(cdir, exist_ok=True)

        with self.locks.acquire(cdir):
            t0 = time.time()
            resources = ResourceWriter(cdir).sync_resources_to_disk(parsed)
            if parsed.draft:
                self._inject_draft_mode(cdir, parsed.root_resource_path)
            t_sync = time.time()

            main = main_tex_file(parsed.root_resource_path)
            command = build_latex_command(main, cdir, parsed)
            run = self.runner.run(command, cwd=cdir, timeout=parsed.timeout_ms / 1000, env=sandbox_env())
            t_compile = time.time()

            files = find_output_files(cdir, {r.path for r in resources})
            build_id = generate_build_id()
            saved = save_output_files(odir, files, cdir, build_id)
            t_output = time.time()

        status = self._determine_status(saved, parsed, run)
        stats = {"latexmk-errors": 1 if run.exit_code not in (0,) and not saved else 0}
        timings = {
            "sync": int((t_sync - t0) * 1000),
            "compile": int((t_compile - t_sync) * 1000),
            "output": int((t_output - t_compile) * 1000),
            "compileE2E": int((t_output - t0) * 1000),
        }
        return CompileResult(status=status, output_files=saved, build_id=build_id, stats=stats, timings=timings)

    def _determine_status(self, saved: list, parsed: ParsedRequest, run) -> str:
        if run.timed_out:
            return "timedout"
        if run.terminated:
            return "terminated"
        pdf = next((f for f in saved if f["path"] == "output.pdf"), None)
        if pdf is not None and pdf.get("size", 0) > 0:
            return "success"
        if parsed.stop_on_first_error:
            return "stopped-on-first-error"
        return "failure"

    def _inject_draft_mode(self, compile_dir: str, root: str) -> None:
        path = os.path.join(compile_dir, root)
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            original = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_DRAFT_PREFIX + original)

    # -- stop / clear ----------------------------------------------------- #
    def stop_compile(self, project_id: str, user_id: str | None) -> None:
        # Local runner has no external process registry to signal; no-op stop.
        return None

    def clear_project(self, project_id: str, user_id: str | None) -> None:
        name = self.compile_name(project_id, user_id)
        shutil.rmtree(self.compile_dir(name), ignore_errors=True)
        shutil.rmtree(self.output_dir(name), ignore_errors=True)

    # -- synctex ---------------------------------------------------------- #
    def _require_synctex(self, compile_dir: str) -> None:
        if not os.path.isfile(os.path.join(compile_dir, "output.synctex.gz")):
            raise NotFoundError("output.synctex.gz not found")

    def synctex_from_code(self, project_id, user_id, file, line, column) -> list[dict]:
        name = self.compile_name(project_id, user_id)
        cdir = self.compile_dir(name)
        self._require_synctex(cdir)
        input_path = os.path.join(cdir, file)
        command = ["synctex", "view", "-i", f"{line}:{column}:{input_path}", "-o", os.path.join(cdir, "output.pdf")]
        run = self.runner.run(command, cwd=cdir, timeout=60, env=sandbox_env())
        return parse_view_output(run.stdout)

    def synctex_from_pdf(self, project_id, user_id, page, h, v) -> list[dict]:
        name = self.compile_name(project_id, user_id)
        cdir = self.compile_dir(name)
        self._require_synctex(cdir)
        command = ["synctex", "edit", "-o", f"{page}:{h}:{v}:{os.path.join(cdir, 'output.pdf')}"]
        run = self.runner.run(command, cwd=cdir, timeout=60, env=sandbox_env())
        return parse_edit_output(run.stdout, cdir)

    def wordcount(self, project_id, user_id, filename) -> dict:
        name = self.compile_name(project_id, user_id)
        cdir = self.compile_dir(name)
        command = ["texcount", "-nocol", "-inc", os.path.join(cdir, filename)]
        run = self.runner.run(command, cwd=cdir, timeout=60, env=sandbox_env())
        return parse_wordcount(run.stdout)
