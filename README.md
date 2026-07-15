# Fleetex

**Your own private, self-hosted LaTeX editor — a pip-installable launcher built on [Overleaf Community Edition](https://github.com/overleaf/overleaf).**

Fleetex runs Overleaf on a server *you* control. Install and upgrade it with
`pip install fleetex`, and keep your customizations in a GitHub repo you can
pull from. Your users only need a web browser.

> **Disclaimer:** Fleetex is an independent, community-maintained launcher. It is
> **not affiliated with, endorsed by, or sponsored by Overleaf**. It does not
> redistribute Overleaf's source code — it pulls the official, publicly available
> `sharelatex/sharelatex` Docker image at runtime. "Overleaf" and "ShareLaTeX"
> are trademarks of their respective owners and are used here only nominatively
> to describe what Fleetex runs. Fleetex is distributed under AGPL-3.0 for
> compatibility with Overleaf Community Edition.

> This package is a thin, **zero-dependency** Python wrapper around Docker
> Compose. It does **not** reimplement Overleaf — Overleaf CE is a set of
> Node.js services shipped as the `sharelatex/sharelatex` Docker image. This
> launcher pulls that upstream stack, renders a compose file, and gives you a
> friendly CLI to operate it.

---

## 🐍 The Fleetex Python stack (a from-scratch reimplementation)

This repo also contains a **ground-up Python reimplementation** of Overleaf's
backend services under [`services/`](services/) — see [`ROADMAP.md`](ROADMAP.md)
and [`PROGRESS.md`](PROGRESS.md). Nine services (auth/projects/editor **web**,
**real-time** websockets, **document-updater** OT engine, docstore, filestore,
clsi, chat, notifications) plus a minimal browser frontend with **live
collaborative editing**. The OT engine is TP1-fuzz-verified and its browser twin
is byte-checked against it.

**Run the entire Python stack with one command:**

```bash
docker compose up --build
```

Then open **http://localhost:3000** → register → create/open a project. Open a
second browser tab (or share with someone) editing the same document — changes
sync live. (Ports published to the host: `3000` web, `3026` real-time websocket.)

### …or drive it with the `fleetex` launcher (python edition)

The `fleetex` CLI can run **this** reimplementation instead of the stock Overleaf
CE image. Point it at a checkout and switch editions:

```bash
fleetex config --edition python --source /path/to/fleetex
fleetex up            # builds + starts the Python stack (project: fleetex-app)
fleetex status        # shows the 10 services
fleetex down          # stops it
```

For LAN/remote access, tell it the host address browsers should use (the live-sync
websocket connects there directly):

```bash
fleetex config --advertise-host 192.168.50.21   # your server's LAN IP
fleetex up                                        # → http://192.168.50.21:3000
```

No `create-admin` step — the Python stack uses open self-registration. With no
`--source`, the launcher clones the repo automatically. The `ce` edition
(stock Overleaf CE on :8080) remains the default; switch back with
`fleetex config --edition ce`.

### Backups

Your data (projects, users, docs, uploads) lives in Docker named volumes that
survive rebuilds and upgrades. Snapshot and restore it with:

```bash
fleetex backup                       # writes ~/.fleetex/backups/fleetex-backup-<timestamp>/
fleetex backup --output /mnt/backups # or choose where
fleetex restore ~/.fleetex/backups/fleetex-backup-20260101-120000   # OVERWRITES current data
```

`restore` stops the stack, replaces the data, and prompts before doing anything
destructive. Run a `fleetex backup` before any risky upgrade.

### Auto-start on reboot

Every service uses `restart: unless-stopped`, so once Docker starts at boot the
whole stack comes back up on its own. Enable Docker at boot once:

```bash
sudo systemctl enable docker
fleetex up            # start it once; it now returns after every reboot
```

(`fleetex down` stops it and keeps it stopped across reboots until the next
`fleetex up`.)

### Editor features

The browser editor (served by the `web` service) supports:

- **Live collaborative-ready editing** over HTTP with autosave; LaTeX syntax
  highlighting, a line gutter, and Tab→spaces.
- **Compile to PDF** with an inline preview, plus an Overleaf-style **Logs**
  panel that parses compile errors/warnings (click an error to jump to the line)
  and a raw-log view.
- **File tree with folders** — create folders, drag-and-drop docs/files between
  them, upload into a selected folder, and nested display.
- **Version history** — every save is a version; browse them, see a live diff
  against your current text, and restore.
- **Sharing** by email, **live cursors/presence**, and image includes.
- **Download the whole project** as a zip (all files + the compiled `output.pdf`)
  from the dashboard or the editor toolbar.
- **Resizable panes** (drag the dividers) and a togglable preview.

These ship in the repo's `services/` tree, which the `python` edition builds from
source — so `git pull` on your checkout (then `fleetex up`) delivers editor
updates without needing a launcher upgrade.

### Run without Docker (advanced)

Docker just bundles the dependencies and orchestration — the services themselves
are plain Python ASGI apps (`python -m fleetex_web`, etc.). You can run the stack
directly if you'd rather manage the dependencies yourself.

**Prerequisites (install however you like):**

- **MongoDB** and **Redis** running locally
- **TeX Live** + `latexmk` (only for the `clsi` compile service)
- **Python 3.10+**

**Install the packages from a checkout:**

```bash
pip install -e services/_kit
for s in web real-time document-updater docstore filestore clsi chat notifications project-history; do
  pip install -e "services/$s"
done
```

**Shared environment** (every service reads these; the secret must match between
`web` and `real-time`):

```bash
export MONGO_URL=mongodb://localhost:27017/sharelatex
export REDIS_URL=redis://localhost:6379
export SESSION_SECRET=change-me
```

**Start each service** (own terminal, or `&`). Cross-service URLs point at
`localhost` instead of Docker service names:

| Service | Command | Port |
| --- | --- | --- |
| docstore | `python -m fleetex_docstore` | 3016 |
| filestore | `BACKEND=fs FILESTORE_PATH=./data/filestore python -m fleetex_filestore` | 3009 |
| clsi | `python -m fleetex_clsi` (needs TeX Live) | 3013 |
| chat | `python -m fleetex_chat` | 3010 |
| notifications | `python -m fleetex_notifications` | 3042 |
| project-history | `DOCUMENT_UPDATER_URL=http://localhost:3003 python -m fleetex_project_history` | 3054 |
| document-updater | `DOCSTORE_URL=http://localhost:3016 PROJECT_HISTORY_URL=http://localhost:3054 python -m fleetex_document_updater` | 3003 |
| web | `DOCSTORE_URL=http://localhost:3016 CLSI_URL=http://localhost:3013 DOCUMENT_UPDATER_URL=http://localhost:3003 FILESTORE_URL=http://localhost:3009 PROJECT_HISTORY_URL=http://localhost:3054 WEBSOCKET_URL=http://localhost:3026 python -m fleetex_web` | 3000 |
| real-time | `WEB_HOST=localhost WEB_PORT=3000 DOCUMENT_UPDATER_HOST=localhost python -m fleetex_realtime` | 3026 |

Then open **http://localhost:3000**. (This is exactly what the compose file wires
up for you — Docker is the convenience, not a requirement. The full test suite,
300+ tests, likewise runs with **no Docker** via in-memory Mongo/Redis fakes.)

---

## Why this exists

You want an Overleaf alternative for work that:

- runs on **your own server**, fully under your control,
- installs and updates with a single command (`pip install -U fleetex`),
- and lets you keep improvements in a **GitHub fork** you can `git pull`.

That's exactly what this is.

## Requirements

- Linux server with **Docker Engine** + the **Docker Compose v2 plugin**
  (`docker compose version` must work).
- **Python 3.9+** (for the `fleetex` CLI; the services run Python inside containers).
- **git** — only for the python edition when no `--source` is given (used to clone the stack).
- **~6 GB free disk** (clsi ships TeX Live) and a couple of GB of RAM.

Run **`fleetex doctor`** to check all of the above and report anything missing
before you `fleetex up`.

## Install

```bash
pip install fleetex        # from PyPI (once published)
```

or from your GitHub fork (the "GitHub pull" workflow, see below):

```bash
pip install "git+https://github.com/<you>/fleetex.git"
```

## Quick start

```bash
fleetex up                     # pull images + start the stack (detached)
fleetex create-admin you@work.example.com
fleetex open                   # open http://localhost:8080
```

Then log in as the admin you created. That's it — you have a working,
self-hosted Overleaf.

## Commands

| Command | What it does |
|---|---|
| `fleetex up` | Pull images and start Overleaf (add `--foreground` to stream logs, `--no-pull` to skip pulling) |
| `fleetex down` | Stop the stack (data is preserved). `--volumes` also wipes data |
| `fleetex status` | Show container status |
| `fleetex logs -f [service]` | Tail logs (optionally for one service) |
| `fleetex restart` | Restart all services |
| `fleetex open` | Open the web UI in a browser |
| `fleetex create-admin <email>` | Create the first admin user |
| `fleetex exec <service> <cmd...>` | Run a command in a container (e.g. `exec sharelatex bash`) |
| `fleetex doctor` | Check prerequisites (Docker, Compose v2, git, disk) |
| `fleetex backup` / `restore` | Back up / restore data (projects, docs, uploads) |
| `fleetex app <cmd>` | **Control the app** (projects, docs, compile, download, share) — see below |
| `fleetex config [--port N ...]` | View or change settings and re-render the compose file |
| `fleetex version` | Show launcher + Docker versions |

## Control the app from the CLI (agent-native)

Fleetex isn't just operable from the browser — the whole application is
driveable from the command line via `fleetex app`, so scripts and AI agents can
use it headlessly. Every command supports `--json`.

```bash
fleetex app register --email you@example.com --password 'secret123'   # or login
PID=$(fleetex app new "My Paper" --json | jq -r .project_id)
fleetex app mkdir "$PID" chapters                    # create a folder
fleetex app mkdoc "$PID" intro.tex --folder chapters # create a doc inside it
fleetex app upload "$PID" figure.png --folder chapters   # upload a file into it
cat paper.tex | fleetex app push "$PID" main.tex     # set a document's content
fleetex app compile "$PID" -o paper.pdf              # compile → saves the PDF
fleetex app download "$PID" -o paper.zip             # sources + compiled PDF
fleetex app projects                                 # list; also: tree, pull, rm, rename, members
```

The session is cached in `~/.fleetex/session.json`. See [`SKILL.md`](SKILL.md)
for the agent-facing capability description. `fleetex app --help` lists
everything.

## Configuration

State lives in a single directory: `~/.fleetex` by default (override with
`FLEETEX_HOME` or `--home`). It contains `config.json`, a rendered
`docker-compose.yml`, and a `data/` directory holding the bind-mounted volumes
for the app, MongoDB, and Redis.

```bash
fleetex config                          # show current settings
fleetex config --port 9000              # change the HTTP port
fleetex config --image sharelatex/sharelatex:5.0   # pin an image version
fleetex config --data-dir /srv/overleaf/data       # move data to a big disk
```

## The update workflow (PyPI + GitHub)

**Upgrade the Overleaf app itself** (new upstream `sharelatex/sharelatex` release):

```bash
fleetex up          # `up` pulls the latest image by default
# or pin a specific version:
fleetex config --image sharelatex/sharelatex:<tag> && fleetex restart
```

**Upgrade this launcher** (new features/fixes in the CLI):

```bash
pip install -U fleetex               # from PyPI
# or from your fork:
pip install -U "git+https://github.com/<you>/fleetex.git"
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
