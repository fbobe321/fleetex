"""Tests for the agent-native `fleetex app` client (urllib mocked)."""

from __future__ import annotations

import json
from pathlib import Path

from fleetex.app import Client
from fleetex.cli import build_parser
from fleetex.config import Config


class _Resp:
    def __init__(self, body: bytes = b"", cookies=None):
        self._body = body
        self._cookies = cookies or []

    def read(self):
        return self._body

    @property
    def headers(self):
        outer = self

        class _H:
            def get_all(self, name):
                return outer._cookies if name == "Set-Cookie" else []

        return _H()


def _client(tmp_path):
    cfg = Config.load(tmp_path)
    cfg.edition = "python"
    cfg.advertise_host = "localhost"
    return Client(cfg)


def test_login_captures_and_persists_cookie(tmp_path: Path, monkeypatch):
    def fake(req, timeout=0):
        assert req.method == "POST" and req.full_url.endswith("/login")
        return _Resp(b'{"redir":"/projects"}', ["overleaf.sid=ABC123; Path=/; HttpOnly"])

    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = _client(tmp_path)
    c.login("a@b.com", "pw")
    assert c.cookie == "ABC123"
    sess = json.loads((tmp_path / "session.json").read_text())
    assert sess[c.base]["cookie"] == "ABC123" and sess[c.base]["email"] == "a@b.com"


def test_projects_new_and_tree(tmp_path: Path, monkeypatch):
    def fake(req, timeout=0):
        u = req.full_url
        if u.endswith("/api/project"):
            return _Resp(b'{"projects":[{"id":"p1","name":"X","accessLevel":"owner"}]}')
        if u.endswith("/project/new"):
            return _Resp(b'{"project_id":"pNEW"}')
        if u.endswith("/tree"):
            return _Resp(b'{"entities":[{"id":"d1","path":"/main.tex","type":"doc"}]}')
        return _Resp(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = _client(tmp_path)
    assert c.projects()[0]["id"] == "p1"
    assert c.new_project("My") == "pNEW"
    assert c.tree("pNEW")[0]["path"] == "/main.tex"
    assert c._doc_id_for_path("pNEW", "main.tex") == "d1"


def test_error_maps_401_to_login_hint(tmp_path: Path, monkeypatch):
    import urllib.error

    def fake(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = _client(tmp_path)
    try:
        c.projects()
        assert False, "expected AppError"
    except Exception as exc:  # AppError
        assert "login" in str(exc).lower()


def test_mkdoc_mkdir_resolve_folder(tmp_path: Path, monkeypatch):
    posted = []

    def fake(req, timeout=0):
        u = req.full_url
        if u.endswith("/tree"):
            return _Resp(b'{"entities":[{"id":"f1","path":"/chapters","type":"folder"}]}')
        if u.endswith("/doc") or u.endswith("/folder"):
            posted.append(json.loads(req.data.decode()))
            return _Resp(b'{"_id":"new1","name":"x"}')
        return _Resp(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = _client(tmp_path)
    c.mkdoc("p", "intro.tex", "chapters")
    c.mkdir("p", "sub", "chapters")
    assert posted[0]["parent_folder_id"] == "f1" and posted[0]["name"] == "intro.tex"
    assert posted[1]["parent_folder_id"] == "f1"


def test_multipart_encoder():
    from fleetex.app import _encode_multipart

    body, ctype = _encode_multipart({"name": "logo.png", "folder_id": "f1"}, "qqfile", "logo.png", b"\x89PNGbytes")
    assert ctype.startswith("multipart/form-data; boundary=----fleetex")
    assert b'name="name"' in body and b"logo.png" in body
    assert b'name="qqfile"; filename="logo.png"' in body and b"\x89PNGbytes" in body


def test_upload_posts_multipart(tmp_path: Path, monkeypatch):
    f = tmp_path / "pic.png"
    f.write_bytes(b"\x89PNGdata")
    sent = {}

    def fake(req, timeout=0):
        if req.full_url.endswith("/tree"):
            return _Resp(b'{"entities":[]}')
        if req.full_url.endswith("/upload"):
            sent["ctype"] = req.headers.get("Content-type")
            sent["len"] = len(req.data)
            return _Resp(b'{"success":true,"entity_type":"file"}')
        return _Resp(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = _client(tmp_path)
    res = c.upload("p", str(f), "pic.png", None)
    assert res["success"] is True
    assert sent["ctype"].startswith("multipart/form-data") and sent["len"] > 0


def test_repl_is_stateful(tmp_path: Path, monkeypatch, capsys):
    from fleetex import app as appmod

    lines = iter(["projects", "use p1", "pwd", "tree", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())

    def fake(req, timeout=0):
        if req.full_url.endswith("/api/project"):
            return _Resp(b'{"projects":[{"id":"p1","name":"X","accessLevel":"owner"}]}')
        if req.full_url.endswith("/project/p1/tree"):
            return _Resp(b'{"entities":[{"id":"d1","path":"/main.tex","type":"doc"}]}')
        return _Resp(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake)
    cfg = Config.load(tmp_path)
    cfg.edition = "python"
    cfg.advertise_host = "localhost"
    rc = appmod.repl(cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "p1" in out and "current project: p1" in out
    # `tree` with no project arg used the selected p1 (hit /project/p1/tree)
    assert "/main.tex" in out


def test_parser_accepts_app_subcommands():
    p = build_parser()
    for argv in (
        ["app", "repl"],
        ["app", "login"],
        ["app", "register", "--email", "a@b.com"],
        ["app", "projects", "--json"],
        ["app", "new", "Name"],
        ["app", "rm", "pid"],
        ["app", "tree", "pid"],
        ["app", "mkdoc", "pid", "intro.tex", "--folder", "chapters"],
        ["app", "mkdir", "pid", "chapters"],
        ["app", "upload", "pid", "logo.png", "--folder", "chapters", "--name", "l.png"],
        ["app", "pull", "pid", "main.tex", "-o", "out.tex"],
        ["app", "push", "pid", "main.tex", "-f", "in.tex"],
        ["app", "compile", "pid", "-o", "x.pdf"],
        ["app", "download", "pid"],
        ["app", "members", "pid", "--add", "e@x.com", "--level", "readOnly"],
    ):
        ns = p.parse_args(argv)
        assert ns.command == "app" and hasattr(ns, "func") and ns.app_command
