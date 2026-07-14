"""Preflight environment checks for ``fleetex doctor``.

Reports whether the host has what Fleetex needs (Docker, Compose v2, git, disk,
Python) so problems are caught before ``fleetex up`` rather than mid-build.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from .config import Config

OK, WARN, FAIL = "ok", "warn", "fail"


def _run_ok(cmd: list[str]) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False, ""
    out = (p.stdout or p.stderr or "").strip()
    return p.returncode == 0, out.splitlines()[0] if out else ""


def run_checks(cfg: Config) -> list[tuple[str, str, str]]:
    """Return a list of ``(name, severity, detail)`` prerequisite checks."""
    checks: list[tuple[str, str, str]] = []

    v = sys.version_info
    checks.append(("Python >= 3.9 (for the fleetex CLI)", OK if v >= (3, 9) else FAIL, f"{v.major}.{v.minor}.{v.micro}"))

    docker = shutil.which("docker")
    checks.append(("Docker CLI", OK if docker else FAIL,
                   docker or "not found on PATH — install: https://docs.docker.com/engine/install/"))

    if docker:
        daemon_ok, _ = _run_ok(["docker", "info"])
        checks.append(("Docker daemon running", OK if daemon_ok else FAIL,
                       "" if daemon_ok else "`docker info` failed — start Docker / check permissions (add your user to the docker group)"))
        compose_ok, ver = _run_ok(["docker", "compose", "version"])
        checks.append(("Docker Compose v2 plugin", OK if compose_ok else FAIL,
                       ver or "missing — install: https://docs.docker.com/compose/install/"))

    if cfg.is_python:
        if cfg.python_compose_path.is_file():
            checks.append(("Stack source (python edition)", OK, str(cfg.effective_source_dir)))
        else:
            git = shutil.which("git")
            if cfg.source_dir:
                checks.append(("Stack source (python edition)", FAIL,
                               f"no docker-compose.yml under {cfg.effective_source_dir}"))
            else:
                checks.append(("git (to fetch the stack source)", OK if git else FAIL,
                               git or "needed to clone the repo, or set `fleetex config --source <checkout>`"))

    try:
        base = cfg.home if cfg.home.exists() else cfg.home.parent
        free_gb = shutil.disk_usage(str(base)).free / 1e9
        sev = OK if free_gb >= 8 else (WARN if free_gb >= 4 else FAIL)
        note = "" if sev == OK else "clsi ships TeX Live (~2-4 GB) plus other images"
        checks.append((f"Free disk >= 8 GB ({free_gb:.1f} GB free)", sev, note))
    except OSError:
        pass

    return checks


def summarize(checks: list[tuple[str, str, str]]) -> str:
    """Worst severity across the checks."""
    sevs = {s for _n, s, _d in checks}
    if FAIL in sevs:
        return FAIL
    if WARN in sevs:
        return WARN
    return OK
