"""Configuration handling for the overleaf-ce launcher.

Configuration lives in a single directory (default ``~/.overleaf-ce``, overridable
with the ``OVERLEAF_CE_HOME`` env var or ``--home``). It contains:

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

from . import MONGO_IMAGE, REDIS_IMAGE, SHARELATEX_IMAGE

try:
    from importlib.resources import files as _resource_files
except ImportError:  # pragma: no cover - Python < 3.9 not supported anyway
    _resource_files = None  # type: ignore[assignment]

CONFIG_FILENAME = "config.json"
COMPOSE_FILENAME = "docker-compose.yml"


def default_home() -> Path:
    """Return the config/home directory for the launcher."""
    env = os.environ.get("OVERLEAF_CE_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".overleaf-ce").resolve()


@dataclass
class Config:
    """Launcher settings, serialized to ``config.json``."""

    project_name: str = "overleaf-ce"
    app_name: str = "Overleaf Community Edition"
    http_port: int = 8080
    site_url: str = "http://localhost:8080"
    sharelatex_image: str = SHARELATEX_IMAGE
    mongo_image: str = MONGO_IMAGE
    redis_image: str = REDIS_IMAGE
    # Path to the data directory; if relative, resolved against ``home``.
    data_dir: str = "data"
    _home: Path = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @property
    def home(self) -> Path:
        return self._home if self._home is not None else default_home()

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
        """Materialize compose file, data dirs, and the mongo init script."""
        self.home.mkdir(parents=True, exist_ok=True)
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
            return (
                _resource_files("overleaf_ce.templates")
                .joinpath(name)
                .read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ModuleNotFoundError):
            pass
    # Fallback for editable/source layouts.
    local = Path(__file__).parent / "templates" / name
    return local.read_text(encoding="utf-8")
