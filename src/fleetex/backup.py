"""Back up / restore the stack's data.

The python edition keeps data in Docker named volumes; the ce edition uses
bind-mounted directories under the data dir. Both are captured here so
``fleetex backup`` / ``fleetex restore`` work regardless of edition.

The compile cache (clsi_data) is intentionally skipped — it is disposable.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .compose import DockerError
from .config import Config

# volumes worth backing up (projects/users/docs live in mongo; uploads in
# filestore; sessions in redis). clsi_data is a disposable compile cache.
PYTHON_DATA_VOLUMES = ["mongo_data", "filestore_data", "redis_data"]


def _run(cmd: list[str]) -> None:
    try:
        proc = subprocess.run(cmd)
    except FileNotFoundError:
        raise DockerError("the `docker` CLI was not found on PATH")
    if proc.returncode != 0:
        raise DockerError(f"`{' '.join(cmd)}` exited with status {proc.returncode}")


def backup(cfg: Config, output: str | None = None) -> Path:
    """Write a timestamped backup and return its directory."""
    base = Path(output).expanduser().resolve() if output else (cfg.home / "backups")
    dest = base / f"fleetex-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    if cfg.is_python:
        for vol in PYTHON_DATA_VOLUMES:
            full = f"{cfg.python_project_name}_{vol}"
            print(f"  backing up volume {full} ...")
            _run([
                "docker", "run", "--rm", "-v", f"{full}:/data:ro", "-v", f"{dest}:/backup",
                "alpine", "tar", "czf", f"/backup/{vol}.tar.gz", "-C", "/data", ".",
            ])
    else:
        print(f"  backing up data dir {cfg.data_path} ...")
        _run(["tar", "czf", str(dest / "ce-data.tar.gz"), "-C", str(cfg.data_path), "."])
    return dest


def restore(cfg: Config, source: str) -> None:
    """Overwrite current data with a backup directory (stack must be stopped)."""
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise DockerError(f"backup directory not found: {src}")
    if cfg.is_python:
        found = False
        for vol in PYTHON_DATA_VOLUMES:
            arch = src / f"{vol}.tar.gz"
            if not arch.is_file():
                print(f"  (skipping {vol}: no {arch.name} in backup)")
                continue
            found = True
            full = f"{cfg.python_project_name}_{vol}"
            print(f"  restoring volume {full} ...")
            _run([
                "docker", "run", "--rm", "-v", f"{full}:/data", "-v", f"{src}:/backup",
                "alpine", "sh", "-c",
                f"find /data -mindepth 1 -delete 2>/dev/null; tar xzf /backup/{vol}.tar.gz -C /data",
            ])
        if not found:
            raise DockerError(f"no recognised volume archives in {src}")
    else:
        arch = src / "ce-data.tar.gz"
        if not arch.is_file():
            raise DockerError(f"no ce-data.tar.gz in {src}")
        _run(["sh", "-c", f"find '{cfg.data_path}' -mindepth 1 -delete; tar xzf '{arch}' -C '{cfg.data_path}'"])
