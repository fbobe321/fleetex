"""Thin wrapper around the Docker CLI / ``docker compose``.

We deliberately shell out to the ``docker`` binary rather than depend on a
Python SDK: every host that can run Overleaf already has Docker installed, and
this keeps the launcher dependency-free.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Sequence

from .config import Config


class DockerError(RuntimeError):
    """Raised when Docker is missing or a compose command fails."""


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _compose_base(cfg: Config) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        cfg.project_name,
        "--file",
        str(cfg.compose_path),
    ]


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
    cfg.write_runtime_files()


def run(cfg: Config, args: Sequence[str], *, check: bool = True) -> int:
    """Run a ``docker compose`` subcommand, streaming output to the terminal."""
    cmd = _compose_base(cfg) + list(args)
    proc = subprocess.run(cmd)
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
