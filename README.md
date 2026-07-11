# overleaf-ce

**A pip-installable launcher for self-hosting [Overleaf Community Edition](https://github.com/overleaf/overleaf).**

Run your own Overleaf on a server you control, install and upgrade it with
`pip`, and keep your customizations in a GitHub fork you can pull from.

> This package is a thin, **zero-dependency** Python wrapper around Docker
> Compose. It does **not** reimplement Overleaf — Overleaf CE is a set of
> Node.js services shipped as the `sharelatex/sharelatex` Docker image. This
> launcher pulls that upstream stack, renders a compose file, and gives you a
> friendly CLI to operate it.

---

## Why this exists

You want an Overleaf alternative for work that:

- runs on **your own server**, fully under your control,
- installs and updates with a single command (`pip install -U overleaf-ce`),
- and lets you keep improvements in a **GitHub fork** you can `git pull`.

That's exactly what this is.

## Requirements

- Linux server with **Docker Engine** + the **Docker Compose v2 plugin**
  (`docker compose version` must work).
- **Python 3.9+**.

## Install

```bash
pip install overleaf-ce        # from PyPI (once published)
```

or from your GitHub fork (the "GitHub pull" workflow, see below):

```bash
pip install "git+https://github.com/<you>/overleaf-ce.git"
```

## Quick start

```bash
overleaf-ce up                     # pull images + start the stack (detached)
overleaf-ce create-admin you@work.example.com
overleaf-ce open                   # open http://localhost:8080
```

Then log in as the admin you created. That's it — you have a working,
self-hosted Overleaf.

## Commands

| Command | What it does |
|---|---|
| `overleaf-ce up` | Pull images and start Overleaf (add `--foreground` to stream logs, `--no-pull` to skip pulling) |
| `overleaf-ce down` | Stop the stack (data is preserved). `--volumes` also wipes data |
| `overleaf-ce status` | Show container status |
| `overleaf-ce logs -f [service]` | Tail logs (optionally for one service) |
| `overleaf-ce restart` | Restart all services |
| `overleaf-ce open` | Open the web UI in a browser |
| `overleaf-ce create-admin <email>` | Create the first admin user |
| `overleaf-ce exec <service> <cmd...>` | Run a command in a container (e.g. `exec sharelatex bash`) |
| `overleaf-ce config [--port N ...]` | View or change settings and re-render the compose file |
| `overleaf-ce version` | Show launcher + Docker versions |

## Configuration

State lives in a single directory: `~/.overleaf-ce` by default (override with
`OVERLEAF_CE_HOME` or `--home`). It contains `config.json`, a rendered
`docker-compose.yml`, and a `data/` directory holding the bind-mounted volumes
for the app, MongoDB, and Redis.

```bash
overleaf-ce config                          # show current settings
overleaf-ce config --port 9000              # change the HTTP port
overleaf-ce config --image sharelatex/sharelatex:5.0   # pin an image version
overleaf-ce config --data-dir /srv/overleaf/data       # move data to a big disk
```

## The update workflow (PyPI + GitHub)

**Upgrade the Overleaf app itself** (new upstream `sharelatex/sharelatex` release):

```bash
overleaf-ce up          # `up` pulls the latest image by default
# or pin a specific version:
overleaf-ce config --image sharelatex/sharelatex:<tag> && overleaf-ce restart
```

**Upgrade this launcher** (new features/fixes in the CLI):

```bash
pip install -U overleaf-ce               # from PyPI
# or from your fork:
pip install -U "git+https://github.com/<you>/overleaf-ce.git"
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
