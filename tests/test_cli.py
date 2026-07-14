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


# --- python edition ------------------------------------------------------- #
def test_edition_defaults_to_ce(tmp_path: Path):
    cfg = Config.load(tmp_path)
    assert cfg.edition == "ce" and not cfg.is_python


def test_python_edition_config_roundtrip(tmp_path: Path):
    from fleetex.cli import main

    rc = main([
        "--home", str(tmp_path), "config",
        "--edition", "python", "--source", str(tmp_path / "src"),
        "--advertise-host", "192.168.50.21",
    ])
    assert rc == 0
    cfg = Config.load(tmp_path)
    assert cfg.is_python
    assert cfg.effective_source_dir == (tmp_path / "src").resolve()
    assert cfg.advertise_host == "192.168.50.21"
    assert cfg.web_url == "http://192.168.50.21:3000"
    assert cfg.websocket_url == "http://192.168.50.21:3026"


def test_python_edition_compose_base_targets_repo_compose(tmp_path: Path):
    from fleetex.compose import _compose_base

    cfg = Config.load(tmp_path)
    cfg.edition = "python"
    cfg.source_dir = str(tmp_path / "checkout")
    base = _compose_base(cfg)
    assert "--project-name" in base and "fleetex-app" in base
    assert str((tmp_path / "checkout" / "docker-compose.yml").resolve()) in base


def test_python_edition_write_runtime_is_noop(tmp_path: Path):
    cfg = Config.load(tmp_path)
    cfg.edition = "python"
    cfg.write_runtime_files()
    # no CE artifacts rendered in python edition
    assert not cfg.compose_path.is_file()
    assert not (cfg.data_path / "mongodb-init-replica-set.js").is_file()


def test_create_admin_python_needs_no_docker(tmp_path: Path, capsys):
    from fleetex.cli import main

    Config.load(tmp_path)  # ensure home exists
    main(["--home", str(tmp_path), "config", "--edition", "python"])
    capsys.readouterr()
    rc = main(["--home", str(tmp_path), "create-admin", "me@example.com"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "open self-registration" in out.lower() or "create account" in out.lower()


def test_parser_accepts_python_config_flags():
    parser = build_parser()
    ns = parser.parse_args(["config", "--edition", "python", "--source", "/x", "--advertise-host", "10.0.0.5"])
    assert ns.edition == "python" and ns.source_dir == "/x" and ns.advertise_host == "10.0.0.5"


# --- backup / restore ----------------------------------------------------- #
def test_parser_accepts_backup_and_restore():
    parser = build_parser()
    assert hasattr(parser.parse_args(["backup"]), "func")
    assert hasattr(parser.parse_args(["backup", "--output", "/tmp/b"]), "func")
    ns = parser.parse_args(["restore", "/tmp/b/fleetex-backup-x"])
    assert ns.source == "/tmp/b/fleetex-backup-x"


def test_backup_python_tars_each_data_volume(tmp_path: Path, monkeypatch):
    from fleetex import backup as bk

    cmds = []
    monkeypatch.setattr(bk, "_run", lambda cmd: cmds.append(" ".join(cmd)))
    cfg = Config.load(tmp_path)
    cfg.edition = "python"
    dest = bk.backup(cfg, output=str(tmp_path / "out"))
    assert dest.name.startswith("fleetex-backup-")
    for vol in ("mongo_data", "filestore_data", "redis_data"):
        assert any(f"fleetex-app_{vol}:/data" in c and f"/backup/{vol}.tar.gz" in c for c in cmds), vol
    # the disposable compile cache is not backed up
    assert not any("clsi_data" in c for c in cmds)


def test_backup_ce_tars_data_dir(tmp_path: Path, monkeypatch):
    from fleetex import backup as bk

    cmds = []
    monkeypatch.setattr(bk, "_run", lambda cmd: cmds.append(" ".join(cmd)))
    cfg = Config.load(tmp_path)  # ce is the default edition
    bk.backup(cfg, output=str(tmp_path / "out"))
    assert any("ce-data.tar.gz" in c and str(cfg.data_path) in c for c in cmds)


# --- doctor --------------------------------------------------------------- #
def test_parser_accepts_doctor():
    assert hasattr(build_parser().parse_args(["doctor"]), "func")


def test_doctor_checks_report_python_and_docker(tmp_path: Path):
    from fleetex import doctor

    cfg = Config.load(tmp_path)
    checks = doctor.run_checks(cfg)
    names = [n for n, _s, _d in checks]
    assert any("Python" in n for n in names)
    assert any("Docker CLI" in n for n in names)
    # Python-version check always passes on a supported interpreter
    py = next(c for c in checks if "Python" in c[0])
    assert py[1] == doctor.OK
    assert doctor.summarize(checks) in (doctor.OK, doctor.WARN, doctor.FAIL)


def test_doctor_command_runs(tmp_path: Path, capsys):
    from fleetex.cli import main

    rc = main(["--home", str(tmp_path), "doctor"])
    assert rc in (0, 1)
    out = capsys.readouterr().out
    assert "fleetex doctor" in out and "Docker CLI" in out


def test_restore_python_untars_into_volumes(tmp_path: Path, monkeypatch):
    from fleetex import backup as bk

    src = tmp_path / "fleetex-backup-1"
    src.mkdir()
    (src / "mongo_data.tar.gz").write_bytes(b"x")  # only mongo present
    cmds = []
    monkeypatch.setattr(bk, "_run", lambda cmd: cmds.append(" ".join(cmd)))
    cfg = Config.load(tmp_path)
    cfg.edition = "python"
    bk.restore(cfg, str(src))
    assert any("fleetex-app_mongo_data:/data" in c for c in cmds)
    assert not any("filestore_data" in c for c in cmds)  # absent archive skipped
