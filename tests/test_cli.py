"""Tests that exercise config rendering and CLI wiring without touching Docker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleetex.cli import build_parser
from fleetex.config import Config


def test_default_config_roundtrip(tmp_path: Path):
    cfg = Config.load(tmp_path)
    assert cfg.http_port == 8080
    cfg.http_port = 9000
    cfg.save()
    reloaded = Config.load(tmp_path)
    assert reloaded.http_port == 9000
    # persisted file is valid JSON with the changed value
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["http_port"] == 9000


def test_render_compose_substitutes_placeholders(tmp_path: Path):
    cfg = Config.load(tmp_path)
    cfg.http_port = 9000
    cfg.app_name = "My Lab Overleaf"
    rendered = cfg.render_compose()
    assert "${" not in rendered  # every placeholder resolved
    assert "9000:80" in rendered
    assert "My Lab Overleaf" in rendered
    assert "sharelatex/sharelatex" in rendered


def test_write_runtime_files_creates_expected_layout(tmp_path: Path):
    cfg = Config.load(tmp_path)
    cfg.write_runtime_files()
    assert cfg.compose_path.is_file()
    for sub in ("sharelatex", "mongo", "redis"):
        assert (cfg.data_path / sub).is_dir()
    assert (cfg.data_path / "mongodb-init-replica-set.js").is_file()


def test_data_dir_relative_resolves_under_home(tmp_path: Path):
    cfg = Config.load(tmp_path)
    assert cfg.data_path == tmp_path / "data"


def test_data_dir_absolute_is_respected(tmp_path: Path):
    cfg = Config.load(tmp_path)
    abs_dir = tmp_path / "elsewhere"
    cfg.data_dir = str(abs_dir)
    assert cfg.data_path == abs_dir


@pytest.mark.parametrize(
    "argv",
    [
        ["up"],
        ["up", "--foreground", "--no-pull"],
        ["down"],
        ["down", "--volumes"],
        ["status"],
        ["logs", "-f", "sharelatex"],
        ["create-admin", "a@b.com"],
        ["config", "--port", "9000"],
        ["version"],
    ],
)
def test_parser_accepts_expected_commands(argv):
    parser = build_parser()
    ns = parser.parse_args(argv)
    assert hasattr(ns, "func")


def test_config_command_shows_when_no_flags(tmp_path: Path, capsys):
    from fleetex.cli import main

    rc = main(["--home", str(tmp_path), "config"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "http_port:" in out
