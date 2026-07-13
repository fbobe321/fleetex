"""Configuration handling for the fleetex launcher.

Configuration lives in a single directory (default ``~/.fleetex``, overridable
with the ``FLEETEX_HOME`` env var or ``--home``). It contains:

* ``config.json``         - launcher settings (port, image tags, data dir ...)
* ``docker-compose.yml``  - the rendered compose file (regenerated on demand)
* ``data/``               - bind-mounted volumes for sharelatex/mongo/redis
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from string import Template

from . import MONGO_IMAGE, PYTHON_PROJECT_NAME, REDIS_IMAGE, SHARELATEX_IMAGE

try:
    from importlib.resources import files as _resource_files
except ImportError:  # pragma: no cover - Python < 3.9 not supported anyway
    _resource_files = None  # type: ignore[assignment]

CONFIG_FILENAME = "config.json"
COMPOSE_FILENAME = "docker-compose.yml"


def default_home() -> Path:
    """Return the config/home directory for the launcher."""
    env = os.environ.get("FLEETEX_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".fleetex").resolve()


@dataclass
class Config:
    """Launcher settings, serialized to ``config.json``."""

    project_name: str = "fleetex"
    app_name: str = "Fleetex"
    http_port: int = 8080
    site_url: str = "http://localhost:8080"
    sharelatex_image: str = SHARELATEX_IMAGE
    mongo_image: str = MONGO_IMAGE
    redis_image: str = REDIS_IMAGE
    # Path to the data directory; if relative, resolved against ``home``.
    data_dir: str = "data"
    # "ce"     -> run stock Overleaf Community Edition (the sharelatex image).
    # "python" -> run Fleetex's own Python reimplementation via its compose file.
    edition: str = "ce"
    # For the python edition: a local checkout of the fleetex repo. When empty,
    # the launcher clones it into ``<home>/fleetex-src``.
    source_dir: str = ""
    # For the python edition: the host/IP browsers use to reach the stack. The
    # browser opens the live-sync websocket to this host directly, so on a LAN it
    # must be the server's address, not localhost.
    advertise_host: str = "localhost"
    _home: Path = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @property
    def home(self) -> Path:
        return self._home if self._home is not None else default_home()

    # -- edition helpers --------------------------------------------------
    @property
    def is_python(self) -> bool:
        return self.edition == "python"

    @property
    def effective_source_dir(self) -> Path:
        if self.source_dir:
            return Path(self.source_dir).expanduser().resolve()
        return (self.home / "fleetex-src").resolve()

    @property
    def python_compose_path(self) -> Path:
        return self.effective_source_dir / "docker-compose.yml"

    @property
    def python_project_name(self) -> str:
        return PYTHON_PROJECT_NAME

    def active_compose_path(self) -> Path:
        """The compose file the active edition operates on."""
        return self.python_compose_path if self.is_python else self.compose_path

    @property
    def websocket_url(self) -> str:
        """URL the browser opens the live-sync websocket to (python edition)."""
        return f"http://{self.advertise_host}:3026"

    @property
    def web_url(self) -> str:
        """The URL to show the user for the running stack."""
        if self.is_python:
            return f"http://{self.advertise_host}:3000"
        return self.site_url

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else (self.home / p)

    @property
    def config_path(self) -> Path:
        return self.home / CONFIG_FILENAME

    @property
    def compose_path(self) -> Path:
        return self.home / COMPOSE_FILENAME

    # -- persistence ------------------------------------------------------
    @classmethod
    def load(cls, home: Path | None = None) -> "Config":
        home = (home or default_home()).resolve()
        cfg_file = home / CONFIG_FILENAME
        data: dict = {}
        if cfg_file.is_file():
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        known = {f for f in cls().__dict__ if not f.startswith("_")}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg._home = home
        return cfg

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        self.config_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- rendering --------------------------------------------------------
    def _substitutions(self) -> dict:
        return {
            "PROJECT_NAME": self.project_name,
            "APP_NAME": self.app_name,
            "HTTP_PORT": str(self.http_port),
            "SITE_URL": self.site_url,
            "SHARELATEX_IMAGE": self.sharelatex_image,
            "MONGO_IMAGE": self.mongo_image,
            "REDIS_IMAGE": self.redis_image,
            "DATA_DIR": str(self.data_path),
        }

    def render_compose(self) -> str:
        template_text = _read_template("docker-compose.yml.tmpl")
        # ``safe_substitute`` leaves unknown ``$`` sequences untouched so we do
        # not choke on any literal shell-style values a user might add later.
        return Template(template_text).safe_substitute(self._substitutions())

    def write_runtime_files(self) -> None:
        """Materialize compose file, data dirs, and the mongo init script.

        The python edition drives the repo's own docker-compose.yml, so there is
        no CE template to render — just ensure the home dir exists.
        """
        self.home.mkdir(parents=True, exist_ok=True)
        if self.is_python:
            return
        data = self.data_path
        for sub in ("sharelatex", "mongo", "redis"):
            (data / sub).mkdir(parents=True, exist_ok=True)
        # The replica-set init script is bind-mounted by the compose file.
        (data / "mongodb-init-replica-set.js").write_text(
            _read_template("mongodb-init-replica-set.js"), encoding="utf-8"
        )
        self.compose_path.write_text(self.render_compose(), encoding="utf-8")


def _read_template(name: str) -> str:
    """Read a packaged template file, working both installed and from source."""
    if _resource_files is not None:
        try:
            # Resolve via the ``fleetex`` package (which has an __init__), not the
            # ``fleetex.templates`` data dir: on Python 3.9 the latter is a
            # namespace package whose __file__ is None, so files() raises
            # TypeError (Path(None)). Going through the real package avoids that.
            return (
                _resource_files("fleetex")
                .joinpath("templates")
                .joinpath(name)
                .read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ModuleNotFoundError, TypeError, NotADirectoryError):
            pass
    # Fallback for editable/source layouts (also the safety net if the above fails).
    local = Path(__file__).parent / "templates" / name
    return local.read_text(encoding="utf-8")
