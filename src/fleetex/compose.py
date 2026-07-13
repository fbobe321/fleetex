"""Thin wrapper around the Docker CLI / ``docker compose``.

We deliberately shell out to the ``docker`` binary rather than depend on a
Python SDK: every host that can run Overleaf already has Docker installed, and
this keeps the launcher dependency-free.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Mapping, Sequence

from . import REPO_URL
from .config import Config


class DockerError(RuntimeError):
    """Raised when Docker is missing or a compose command fails."""


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _compose_base(cfg: Config) -> list[str]:
    if cfg.is_python:
        project, compose_file = cfg.python_project_name, cfg.python_compose_path
    else:
        project, compose_file = cfg.project_name, cfg.compose_path
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(compose_file),
    ]


def _ensure_python_source(cfg: Config) -> None:
    """Make sure a fleetex checkout with a docker-compose.yml is available."""
    src = cfg.effective_source_dir
    if cfg.python_compose_path.is_file():
        return
    if cfg.source_dir:
        raise DockerError(
            f"no docker-compose.yml under the configured source dir {src}. "
            "Point `fleetex config --source` at a Fleetex checkout."
        )
    if shutil.which("git") is None:
        raise DockerError(
            "git is required to fetch the Fleetex Python stack (or set "
            "`fleetex config --source <path>` to a local checkout)."
        )
    print(f"Fetching the Fleetex Python stack into {src} ...")
    src.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(src)])
    if proc.returncode != 0 or not cfg.python_compose_path.is_file():
        raise DockerError(f"failed to fetch the Fleetex source into {src}")


def ensure_ready(cfg: Config) -> None:
    """Verify Docker is present and Compose v2 is available; render runtime files."""
    if not _docker_available():
        raise DockerError(
            "The `docker` CLI was not found on PATH. Install Docker Engine + the "
            "Compose plugin: https://docs.docker.com/engine/install/"
        )
    probe = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise DockerError(
            "`docker compose` (Compose v2) is not available. Install the Docker "
            "Compose plugin: https://docs.docker.com/compose/install/\n"
            + (probe.stderr or probe.stdout).strip()
        )
    if cfg.is_python:
        _ensure_python_source(cfg)
        cfg.write_runtime_files()  # just ensures home dir exists
    else:
        cfg.write_runtime_files()


def run(
    cfg: Config,
    args: Sequence[str],
    *,
    check: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> int:
    """Run a ``docker compose`` subcommand, streaming output to the terminal."""
    cmd = _compose_base(cfg) + list(args)
    env = {**os.environ, **extra_env} if extra_env else None
    proc = subprocess.run(cmd, env=env)
    if check and proc.returncode != 0:
        raise DockerError(
            f"`{' '.join(cmd)}` exited with status {proc.returncode}"
        )
    return proc.returncode


def capture(cfg: Config, args: Sequence[str]) -> subprocess.CompletedProcess:
    """Run a ``docker compose`` subcommand and capture its output."""
    return subprocess.run(
        _compose_base(cfg) + list(args), capture_output=True, text=True
    )
