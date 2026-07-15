"""Agent-native control of the running Fleetex app over its HTTP API.

`fleetex app ...` drives the actual application — projects, documents, compiles,
downloads, sharing — the same endpoints the browser uses. Stdlib only (urllib),
so the launcher stays dependency-free. Every command supports ``--json`` for
agents; human-readable output otherwise.

The session cookie from ``fleetex app login`` (or ``register``) is stored in
``<home>/session.json`` keyed by the web URL and reused by later commands.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .config import Config

COOKIE_NAME = "overleaf.sid"


class AppError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #
class Client:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.base = cfg.web_url.rstrip("/")
        self._session = _load_session(cfg)
        self.cookie = self._session.get(self.base, {}).get("cookie")

    @property
    def email(self) -> str | None:
        return self._session.get(self.base, {}).get("email")

    def _persist(self, email: str | None = None) -> None:
        entry = self._session.setdefault(self.base, {})
        if self.cookie:
            entry["cookie"] = self.cookie
        if email:
            entry["email"] = email
        _save_session(self.cfg, self._session)

    def request(self, method: str, path: str, body=None, raw: bool = False):
        url = self.base + path
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = f"{COOKIE_NAME}={self.cookie}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            if exc.code in (401, 403):
                raise AppError("not logged in (or no access). Run `fleetex app login`.")
            raise AppError(f"{method} {path} -> HTTP {exc.code}: {detail}")
        except urllib.error.URLError as exc:
            raise AppError(f"cannot reach {self.base} ({exc.reason}). Is the stack up? Try `fleetex up`.")
        for sc in resp.headers.get_all("Set-Cookie") or []:
            if sc.startswith(f"{COOKIE_NAME}="):
                self.cookie = sc.split(";")[0].split("=", 1)[1]
        payload = resp.read()
        if raw:
            return payload
        return json.loads(payload) if payload else {}

    # -- auth ------------------------------------------------------------- #
    def login(self, email: str, password: str) -> None:
        self.request("POST", "/login", {"email": email, "password": password})
        self._persist(email)

    def register(self, email: str, password: str) -> None:
        self.request("POST", "/register", {"email": email, "password": password})
        self._persist(email)

    def logout(self) -> None:
        try:
            self.request("POST", "/logout")
        except AppError:
            pass
        self._session.pop(self.base, None)
        _save_session(self.cfg, self._session)
        self.cookie = None

    # -- projects --------------------------------------------------------- #
    def projects(self) -> list[dict]:
        return self.request("POST", "/api/project", {}).get("projects", [])

    def new_project(self, name: str) -> str:
        return self.request("POST", "/project/new", {"projectName": name})["project_id"]

    def delete_project(self, pid: str) -> None:
        self.request("DELETE", f"/project/{pid}")

    def rename_project(self, pid: str, name: str) -> None:
        self.request("POST", f"/project/{pid}/rename", {"newProjectName": name})

    def tree(self, pid: str) -> list[dict]:
        return self.request("GET", f"/project/{pid}/tree").get("entities", [])

    def _doc_id_for_path(self, pid: str, path: str) -> str:
        want = "/" + path.lstrip("/")
        for e in self.tree(pid):
            if e["type"] == "doc" and e["path"] == want:
                return e["id"]
        raise AppError(f"no document at path {want!r} in project {pid}")

    def doc_pull(self, pid: str, path: str) -> str:
        doc_id = self._doc_id_for_path(pid, path)
        return self.request("GET", f"/project/{pid}/doc/{doc_id}?plain=true", raw=True).decode("utf-8", "replace")

    def doc_push(self, pid: str, path: str, content: str) -> None:
        doc_id = self._doc_id_for_path(pid, path)
        self.request("POST", f"/project/{pid}/doc/{doc_id}", {"content": content})

    def compile(self, pid: str) -> dict:
        return self.request("POST", f"/project/{pid}/compile").get("compile", {})

    def fetch(self, path: str) -> bytes:
        return self.request("GET", path, raw=True)

    def download_zip(self, pid: str) -> bytes:
        return self.request("GET", f"/project/{pid}/download/zip", raw=True)

    def members(self, pid: str) -> list[dict]:
        return self.request("GET", f"/project/{pid}/members").get("members", [])

    def add_member(self, pid: str, email: str, level: str) -> dict:
        return self.request("POST", f"/project/{pid}/members", {"email": email, "privilegeLevel": level})

    def remove_member(self, pid: str, user_id: str) -> None:
        self.request("DELETE", f"/project/{pid}/members/{user_id}")


def _load_session(cfg: Config) -> dict:
    p = Path(cfg.home) / "session.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_session(cfg: Config, data: dict) -> None:
    Path(cfg.home).mkdir(parents=True, exist_ok=True)
    (Path(cfg.home) / "session.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
def _emit(as_json: bool, human: str, data) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
    elif human:
        print(human)


# --------------------------------------------------------------------------- #
# command handlers (called from cli.py; each returns an exit code)
# --------------------------------------------------------------------------- #
def cmd(cfg: Config, args) -> int:
    as_json = getattr(args, "json", False)
    action = args.app_command
    try:
        c = Client(cfg)
        if action == "login":
            email = args.email or input("Email: ")
            password = args.password or getpass.getpass("Password: ")
            c.login(email, password)
            _emit(as_json, f"✅ logged in as {email} ({c.base})", {"ok": True, "email": email, "url": c.base})
        elif action == "register":
            email = args.email or input("Email: ")
            password = args.password or getpass.getpass("Password (min 6): ")
            c.register(email, password)
            _emit(as_json, f"✅ registered + logged in as {email}", {"ok": True, "email": email})
        elif action == "logout":
            c.logout()
            _emit(as_json, "✅ logged out", {"ok": True})
        elif action == "whoami":
            _emit(as_json, c.email or "(not logged in)", {"email": c.email, "url": c.base})
        elif action == "projects":
            projs = c.projects()
            human = "\n".join(f"{p['id']}  {p.get('accessLevel',''):9} {p.get('name','')}" for p in projs) or "(no projects)"
            _emit(as_json, human, projs)
        elif action == "new":
            pid = c.new_project(args.name)
            _emit(as_json, pid, {"project_id": pid})
        elif action == "rm":
            c.delete_project(args.project)
            _emit(as_json, f"✅ deleted {args.project}", {"ok": True, "project_id": args.project})
        elif action == "rename":
            c.rename_project(args.project, args.name)
            _emit(as_json, "✅ renamed", {"ok": True})
        elif action == "tree":
            ents = c.tree(args.project)
            human = "\n".join(f"{e['type']:6} {e['path']}" for e in ents) or "(empty)"
            _emit(as_json, human, ents)
        elif action == "pull":
            text = c.doc_pull(args.project, args.path)
            if getattr(args, "output", None):
                Path(args.output).write_text(text, encoding="utf-8")
                _emit(as_json, f"✅ wrote {args.output}", {"ok": True, "path": args.output})
            else:
                sys.stdout.write(text)
        elif action == "push":
            content = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
            c.doc_push(args.project, args.path, content)
            _emit(as_json, f"✅ updated {args.path}", {"ok": True, "path": args.path})
        elif action == "compile":
            comp = c.compile(args.project)
            pdf = next((f for f in comp.get("outputFiles", []) if f.get("path") == "output.pdf"), None)
            out = args.output or "output.pdf"
            saved = None
            if comp.get("status") == "success" and pdf:
                Path(out).write_bytes(c.fetch(pdf["url"]))
                saved = out
            _emit(as_json, (f"✅ {comp.get('status')} -> {saved}" if saved else f"✗ compile {comp.get('status')}"),
                  {"status": comp.get("status"), "pdf": saved, "outputFiles": [f.get("path") for f in comp.get("outputFiles", [])]})
            return 0 if saved else 1
        elif action == "download":
            out = args.output or f"{args.project}.zip"
            Path(out).write_bytes(c.download_zip(args.project))
            _emit(as_json, f"✅ saved {out}", {"ok": True, "file": out})
        elif action == "members":
            if args.add:
                m = c.add_member(args.project, args.add, args.level)
                _emit(as_json, f"✅ added {args.add} ({args.level})", m)
            elif args.remove:
                c.remove_member(args.project, args.remove)
                _emit(as_json, f"✅ removed {args.remove}", {"ok": True})
            else:
                ms = c.members(args.project)
                human = "\n".join(f"{m.get('user_id',''):26} {m.get('privilegeLevel',''):11} {m.get('email','')}" for m in ms)
                _emit(as_json, human, ms)
        else:
            raise AppError(f"unknown app command {action!r}")
        return 0
    except AppError as exc:
        if as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
