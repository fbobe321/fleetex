# PaperFleet

**Your own private, self-hosted LaTeX editor — a pip-installable launcher built on [Overleaf Community Edition](https://github.com/overleaf/overleaf).**

PaperFleet runs Overleaf on a server *you* control. Install and upgrade it with
`pip install paperfleet`, and keep your customizations in a GitHub fork you can
pull from. Your users only need a web browser.

> This package is a thin, **zero-dependency** Python wrapper around Docker
> Compose. It does **not** reimplement Overleaf — Overleaf CE is a set of
> Node.js services shipped as the `sharelatex/sharelatex` Docker image. This
> launcher pulls that upstream stack, renders a compose file, and gives you a
> friendly CLI to operate it.

---

## Why this exists

You want an Overleaf alternative for work that:

- runs on **your own server**, fully under your control,
- installs and updates with a single command (`pip install -U paperfleet`),
- and lets you keep improvements in a **GitHub fork** you can `git pull`.

That's exactly what this is.

## Requirements

- Linux server with **Docker Engine** + the **Docker Compose v2 plugin**
  (`docker compose version` must work).
- **Python 3.9+**.

## Install

```bash
pip install paperfleet        # from PyPI (once published)
```

or from your GitHub fork (the "GitHub pull" workflow, see below):

```bash
pip install "git+https://github.com/<you>/paperfleet.git"
```

## Quick start

```bash
paperfleet up                     # pull images + start the stack (detached)
paperfleet create-admin you@work.example.com
paperfleet open                   # open http://localhost:8080
```

Then log in as the admin you created. That's it — you have a working,
self-hosted Overleaf.

## Commands

| Command | What it does |
|---|---|
| `paperfleet up` | Pull images and start Overleaf (add `--foreground` to stream logs, `--no-pull` to skip pulling) |
| `paperfleet down` | Stop the stack (data is preserved). `--volumes` also wipes data |
| `paperfleet status` | Show container status |
| `paperfleet logs -f [service]` | Tail logs (optionally for one service) |
| `paperfleet restart` | Restart all services |
| `paperfleet open` | Open the web UI in a browser |
| `paperfleet create-admin <email>` | Create the first admin user |
| `paperfleet exec <service> <cmd...>` | Run a command in a container (e.g. `exec sharelatex bash`) |
| `paperfleet config [--port N ...]` | View or change settings and re-render the compose file |
| `paperfleet version` | Show launcher + Docker versions |

## Configuration

State lives in a single directory: `~/.paperfleet` by default (override with
`PAPERFLEET_HOME` or `--home`). It contains `config.json`, a rendered
`docker-compose.yml`, and a `data/` directory holding the bind-mounted volumes
for the app, MongoDB, and Redis.

```bash
paperfleet config                          # show current settings
paperfleet config --port 9000              # change the HTTP port
paperfleet config --image sharelatex/sharelatex:5.0   # pin an image version
paperfleet config --data-dir /srv/overleaf/data       # move data to a big disk
```

## The update workflow (PyPI + GitHub)

**Upgrade the Overleaf app itself** (new upstream `sharelatex/sharelatex` release):

```bash
paperfleet up          # `up` pulls the latest image by default
# or pin a specific version:
paperfleet config --image sharelatex/sharelatex:<tag> && paperfleet restart
```

**Upgrade this launcher** (new features/fixes in the CLI):

```bash
pip install -U paperfleet               # from PyPI
# or from your fork:
pip install -U "git+https://github.com/<you>/paperfleet.git"
```

**Make your own improvements** — fork this repo on GitHub, edit, and either
install from your fork (`pip install git+...`) or open a PR upstream. Cut a
release by bumping `version` in `pyproject.toml` and publishing:

```bash
python -m build
twine upload dist/*
```

## Development

```bash
pip install -e ".[dev]"
pytest                    # tests mock out Docker; no containers needed
```

## Security note (read before exposing to a network)

Overleaf **Community Edition is designed for fully-trusted environments**.
Sandboxed Compiles (user isolation during LaTeX compilation) are a Server Pro
feature and are **not** available in CE — any user who can compile has broad
access to the `sharelatex` container. For a small trusted team on an internal
server this is fine; do **not** expose CE directly to untrusted users. Put it
behind your VPN / SSO reverse proxy and TLS. See the
[upstream README](https://github.com/overleaf/overleaf#overleaf-community-edition).

## Relationship to upstream & license

This launcher packages and orchestrates the unmodified upstream Overleaf CE
images. Overleaf is a trademark of Overleaf; this is an independent packaging
project and is not affiliated with or endorsed by Overleaf. Overleaf CE is
licensed under **AGPL-3.0**, and this launcher is distributed under the same
license to stay compatible.
