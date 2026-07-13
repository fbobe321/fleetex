"""Command-line interface for the fleetex launcher.

Usage examples::

    fleetex up                 # pull images and start the stack (detached)
    fleetex up --foreground    # start in the foreground, stream logs
    fleetex status             # show container status
    fleetex logs -f            # follow logs
    fleetex open               # open the web UI in a browser
    fleetex create-admin you@example.com
    fleetex down               # stop the stack (keeps data)
    fleetex down --volumes     # stop and DELETE all data
    fleetex config --port 9000 # change settings and re-render compose
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .compose import DockerError, capture, ensure_ready, run
from .config import Config


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _load(args: argparse.Namespace) -> Config:
    home = Path(args.home).expanduser().resolve() if args.home else None
    return Config.load(home)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_up(args: argparse.Namespace) -> int:
    cfg = _load(args)
    ensure_ready(cfg)
    if cfg.is_python:
        # Build our own service images from source; the browser reaches the
        # live-sync websocket at advertise_host, so pass it through.
        up_args = ["up", "--build"]
        if not args.foreground:
            up_args.append("--detach")
        run(cfg, up_args, extra_env={"WEBSOCKET_URL": cfg.websocket_url})
        if not args.foreground:
            print(f"\nFleetex (Python stack) is starting at {cfg.web_url}")
            print("First run builds the images — the clsi service ships TeX Live,")
            print("so it can take several minutes. Subsequent starts are fast.")
            print("Open the URL and click 'Create account' — no admin step needed.")
        return 0
    if not args.no_pull:
        print(f"Pulling images ({cfg.sharelatex_image} + mongo + redis)...")
        run(cfg, ["pull"], check=False)
    up_args = ["up"]
    if not args.foreground:
        up_args.append("--detach")
    run(cfg, up_args)
    if not args.foreground:
        print(f"\nFleetex is starting at {cfg.site_url}")
        print("First boot can take a minute while the database initializes.")
        print("Create the first admin user with:")
        print("    fleetex create-admin you@example.com")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not cfg.active_compose_path().is_file():
        return _err("nothing to stop (no compose file). Run `fleetex up` first.")
    ensure_ready(cfg)
    down_args = ["down"]
    if args.volumes:
        confirm = input(
            "This will DELETE all Overleaf data (projects, users, uploads). "
            "Type 'yes' to continue: "
        )
        if confirm.strip().lower() != "yes":
            return _err("aborted")
        down_args.append("--volumes")
    run(cfg, down_args)
    if args.volumes:
        print("Stack stopped. Note: bind-mounted data under the data dir is not")
        print(f"removed by Docker. Delete it manually if desired: {cfg.data_path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not cfg.active_compose_path().is_file():
        print("Not configured yet. Run `fleetex up` to create and start the stack.")
        return 0
    ensure_ready(cfg)
    return run(cfg, ["ps"], check=False)


def cmd_logs(args: argparse.Namespace) -> int:
    cfg = _load(args)
    ensure_ready(cfg)
    log_args = ["logs"]
    if args.follow:
        log_args.append("--follow")
    if args.service:
        log_args.append(args.service)
    return run(cfg, log_args, check=False)


def cmd_restart(args: argparse.Namespace) -> int:
    cfg = _load(args)
    ensure_ready(cfg)
    return run(cfg, ["restart"], check=False)


def cmd_open(args: argparse.Namespace) -> int:
    cfg = _load(args)
    print(f"Opening {cfg.web_url}")
    webbrowser.open(cfg.web_url)
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if cfg.is_python:
        print("The Python stack uses open self-registration — there is no separate")
        print(f"admin step. Open {cfg.web_url} and click 'Create account'.")
        return 0
    ensure_ready(cfg)
    # Upstream ships a create-user script inside the sharelatex container.
    print(f"Creating admin user {args.email} ...")
    rc = run(
        cfg,
        [
            "exec",
            "sharelatex",
            "grunt",
            "user:create-admin",
            f"--email={args.email}",
        ],
        check=False,
    )
    if rc != 0:
        print(
            "\nIf the grunt task is unavailable in your image version, use the "
            "newer script instead:",
            file=sys.stderr,
        )
        print(
            "    fleetex exec sharelatex node "
            "modules/server-ce-scripts/scripts/create-user.mjs "
            f"--admin --email={args.email}",
            file=sys.stderr,
        )
    return rc


def cmd_exec(args: argparse.Namespace) -> int:
    cfg = _load(args)
    ensure_ready(cfg)
    if not args.command:
        return _err("provide a command to run, e.g. `fleetex exec sharelatex bash`")
    return run(cfg, ["exec"] + args.command, check=False)


def cmd_config(args: argparse.Namespace) -> int:
    cfg = _load(args)
    changed = False
    for attr in (
        "app_name",
        "http_port",
        "site_url",
        "sharelatex_image",
        "mongo_image",
        "redis_image",
        "data_dir",
        "project_name",
        "edition",
        "source_dir",
        "advertise_host",
    ):
        val = getattr(args, attr, None)
        if val is not None:
            setattr(cfg, attr, val)
            changed = True
    # Keep site_url in sync with the port unless the user set it explicitly.
    if args.http_port is not None and args.site_url is None:
        cfg.site_url = f"http://localhost:{cfg.http_port}"
    if changed:
        cfg.save()
        cfg.write_runtime_files()
        print(f"Updated config: {cfg.config_path}")
        if not cfg.is_python:
            print(f"Re-rendered compose: {cfg.compose_path}")
        print("Run `fleetex up` (or `restart`) to apply.")
    else:
        # No flags: show current config.
        print(f"home:            {cfg.home}")
        print(f"edition:         {cfg.edition}")
        if cfg.is_python:
            print(f"web_url:         {cfg.web_url}")
            print(f"advertise_host:  {cfg.advertise_host}")
            print(f"source_dir:      {cfg.effective_source_dir}")
        else:
            print(f"app_name:        {cfg.app_name}")
            print(f"http_port:       {cfg.http_port}")
            print(f"site_url:        {cfg.site_url}")
            print(f"sharelatex_image:{cfg.sharelatex_image}")
            print(f"mongo_image:     {cfg.mongo_image}")
            print(f"redis_image:     {cfg.redis_image}")
            print(f"data_dir:        {cfg.data_path}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if cfg.is_python:
        print(f"fleetex launcher {__version__} (python edition)")
        print(f"stack source: {cfg.effective_source_dir}")
    else:
        print(f"fleetex launcher {__version__} (ce edition)")
        print(f"targets image: {cfg.sharelatex_image}")
    probe = capture(cfg, ["version"])
    if probe.returncode == 0:
        print(probe.stdout.strip().splitlines()[0] if probe.stdout else "")
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fleetex",
        description="Fleetex: self-host your own private LaTeX editor "
        "(built on Overleaf Community Edition) via Docker with a single "
        "pip-installable command.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--home",
        help="Config/data directory (default: $FLEETEX_HOME or ~/.fleetex)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="Start the Overleaf stack")
    up.add_argument("--foreground", action="store_true", help="Run in foreground")
    up.add_argument("--no-pull", action="store_true", help="Skip pulling images")
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="Stop the Overleaf stack")
    down.add_argument(
        "--volumes", action="store_true", help="Also remove Docker volumes (DELETES DATA)"
    )
    down.set_defaults(func=cmd_down)

    st = sub.add_parser("status", help="Show container status")
    st.set_defaults(func=cmd_status)

    lg = sub.add_parser("logs", help="Show logs")
    lg.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    lg.add_argument("service", nargs="?", help="Limit to one service (sharelatex/mongo/redis)")
    lg.set_defaults(func=cmd_logs)

    rs = sub.add_parser("restart", help="Restart the stack")
    rs.set_defaults(func=cmd_restart)

    op = sub.add_parser("open", help="Open the web UI in a browser")
    op.set_defaults(func=cmd_open)

    ca = sub.add_parser("create-admin", help="Create the first admin user")
    ca.add_argument("email", help="Admin email address")
    ca.set_defaults(func=cmd_create_admin)

    ex = sub.add_parser("exec", help="Run a command inside a service container")
    ex.add_argument("command", nargs=argparse.REMAINDER, help="service + command")
    ex.set_defaults(func=cmd_exec)

    cf = sub.add_parser("config", help="View or change launcher settings")
    cf.add_argument("--app-name", dest="app_name")
    cf.add_argument("--port", dest="http_port", type=int)
    cf.add_argument("--site-url", dest="site_url")
    cf.add_argument("--image", dest="sharelatex_image", help="sharelatex image tag")
    cf.add_argument("--mongo-image", dest="mongo_image")
    cf.add_argument("--redis-image", dest="redis_image")
    cf.add_argument("--data-dir", dest="data_dir")
    cf.add_argument("--project-name", dest="project_name")
    cf.add_argument(
        "--edition",
        dest="edition",
        choices=["ce", "python"],
        help="ce = stock Overleaf CE image; python = Fleetex's own reimplementation",
    )
    cf.add_argument("--source", dest="source_dir", help="Path to a Fleetex checkout (python edition)")
    cf.add_argument(
        "--advertise-host",
        dest="advertise_host",
        help="Host/IP browsers use to reach the stack (python edition; use the "
        "server's LAN IP for remote access)",
    )
    cf.set_defaults(func=cmd_config)

    vs = sub.add_parser("version", help="Show launcher and Docker versions")
    vs.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DockerError as exc:
        return _err(str(exc))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
