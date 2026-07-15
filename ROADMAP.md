# Fleetex — Python Reimplementation Roadmap

> **Goal:** incrementally reimplement Overleaf Community Edition's **backend
> services in Python**, one service at a time, over months — while always
> keeping a fully working system. This is a marathon, deliberately run slow.

---

## 1. Honest scope

Overleaf CE is a large system. Reimplementing all of it is a multi-month,
sustained effort. Before committing, understand what is and isn't in scope.

**In scope (Python):** the ~11 backend microservices — HTTP APIs, background
workers, Redis/Mongo access, the LaTeX compile orchestration, the real-time
collaboration engine.

**NOT ported to Python:** the **browser frontend** (`services/web/frontend`,
~154k lines of React/TypeScript). It runs in the browser and stays JS/TS
regardless of backend language. We **reuse Overleaf's existing frontend** and
only reimplement the backend it talks to. (A bespoke frontend is a separate,
optional, much later project.)

**Real sizes of the backend to rebuild** (non-test source, from upstream):

| Service            | LOC    | Difficulty | Role |
|--------------------|-------:|:----------:|------|
| notifications      | ~540   | ★☆☆☆☆ | user notifications CRUD |
| chat               | ~950   | ★☆☆☆☆ | project chat messages |
| filestore          | ~980   | ★★☆☆☆ | binary file storage (local/S3) |
| docstore           | ~1540  | ★★☆☆☆ | document contents in Mongo |
| web (backend only) | ~5–10k | ★★★★☆ | auth, projects, editor page, API glue |
| real-time          | ~3550  | ★★★★☆ | websocket layer (socket.io protocol) |
| clsi               | ~7890  | ★★★☆☆ | LaTeX compiler orchestration |
| document-updater   | ~12300 | ★★★★★ | **OT engine** — the hard core |
| project-history    | ~11800 | ★★★★★ | history capture/compression |
| history-v1         | ~9880  | ★★★★★ | history storage backend |
| git-bridge         | (Java) | ★★★★☆ | optional; Git access to projects |

## 2. Strategy: strangler-fig, one service at a time

Do **not** attempt a big-bang rewrite. Instead:

1. Fleetex already runs the real Overleaf (Node) via Docker Compose.
2. Pick the smallest/most-isolated service not yet ported.
3. Reimplement it in Python behind the **same external contract** (same HTTP
   routes, same Redis keys/pubsub channels, same Mongo collections/shapes).
4. Add it to the compose stack as an alternate image; run it **alongside** the
   Node original and verify behavior matches (contract tests + diff).
5. Flip the stack to route to the Python service. Keep the Node one available
   for rollback.
6. Commit. Ship a version. Move on. Repeat.

Benefits: you always have a working Overleaf, every step is independently
testable against ground truth, and **each session touches one small piece** —
which is exactly what keeps token usage low.

## 3. Target Python stack

- **Web framework:** FastAPI (async; Pydantic for request/response models).
- **ASGI server:** uvicorn (behind gunicorn for prod).
- **MongoDB:** Motor (async) / PyMongo.
- **Redis:** redis-py (async).
- **WebSockets:** the `real-time` service must speak the **socket.io** protocol
  the frontend expects — use `python-socketio` (ASGI mode), not raw WS.
- **Object storage:** boto3 (S3) + local FS backend for `filestore`.
- **LaTeX:** `clsi` shells out to a TeX distribution (tectonic or texlive) —
  same as upstream, just orchestrated from Python.
- **Testing:** pytest + a "contract test" harness that runs the Python service
  and the Node original side-by-side and asserts identical responses.

Each service becomes its own installable package under `fleetex/services/<name>/`.

## 4. The hard core — read before touching collaboration

`document-updater` + `project-history` + `history-v1` + the OT libraries
(`overleaf-editor-core`, `ranges-tracker`) implement **operational
transformation**: concurrent edits from multiple users merged consistently.
This is subtle, correctness-critical, and where naive rewrites silently corrupt
documents. Rules:

- Replace these **last**, after everything else is stable.
- Port the OT algorithms **line-for-line first**, optimize never-first.
- Build an exhaustive differential test suite (random op sequences applied to
  both the Node and Python engines; assert identical converged state) **before**
  trusting the Python version with real data.
- It is completely legitimate to keep these three services running the **Node**
  image forever and never port them. A "mostly-Python Overleaf" is a fine
  end state.

## 5. Phased plan

Each phase = one service. Each phase is broken into session-sized tasks
(≈ one focused session each). Do them in order; earlier ones teach the patterns
(FastAPI service skeleton, Mongo/Redis wiring, contract-test harness) you reuse
later.

### Phase 0 — Foundations (do once)
- [ ] `fleetex/services/` layout + a shared `fleetex-service-kit` (config, logging, Mongo/Redis clients, health endpoint).
- [ ] Contract-test harness: spin up Node service + Python service, replay requests, diff responses.
- [ ] Compose overrides so any single service can be flipped Node↔Python.

### Phase 1 — `notifications` (★, warm-up)
- [ ] Map the HTTP API (list/create/delete) and Mongo `notifications` collection.
- [ ] Implement FastAPI service.
- [ ] Contract tests green vs Node.
- [ ] Flip in compose; smoke test in the running app.

### Phase 2 — `chat` (★)
- [ ] Map API + `messages` collection.
- [ ] Implement, contract-test, flip.

### Phase 3 — `filestore` (★★)
- [ ] Local-FS backend first; S3 backend second.
- [ ] Streaming upload/download parity; contract-test, flip.

### Phase 4 — `docstore` (★★)
- [ ] Doc storage + archiving semantics; contract-test, flip.

### Phase 5 — `clsi` (★★★, high-value, isolated)
- [ ] Compile request/response API + output file serving.
- [ ] Shell out to TeX; reproduce cache/output-dir behavior.
- [ ] Contract-test with sample projects; flip.

### Phase 6 — `real-time` (★★★★)
- [ ] Implement socket.io server (python-socketio) matching the frontend's events.
- [ ] Redis pub/sub bridge to document-updater (still Node at this point).
- [ ] Verify live editing works end-to-end; flip.

### Phase 7 — `web` backend (★★★★, the monolith — split into many sub-phases)
- [ ] Auth & sessions (login, register, password, admin).
- [ ] Project CRUD + membership/sharing.
- [ ] Editor page + the API calls the frontend makes on load.
- [ ] File tree, uploads, linked files.
- [ ] Templates, settings, misc pages.
- [ ] Serve Overleaf's existing frontend bundle from the Python app.
- (Each bullet is itself several sessions. Keep Node `web` running until each
  slice is proven, route slice-by-slice via a reverse proxy.)

### Phase 8 — the hard core (★★★★★, optional, last)
- [ ] Differential test harness for OT (random-op fuzzing vs Node).
- [ ] `document-updater` (OT apply/flush/Redis doc lifecycle).
- [ ] `history-v1` storage.
- [ ] `project-history` capture/compression.
- [ ] Only flip after the fuzzer runs clean for a long time.

## 6. How to run each session cheaply (token discipline)

- **One service (or one endpoint) per session.** Never load the whole codebase.
- Start each session by reading only: this ROADMAP, the target Node service's
  routes/models, and the contract-test harness. Nothing else.
- Definition of done for a session: code + contract test green + committed.
  Ship a patch version when a service flips.
- Keep a running log in `PROGRESS.md` (what's done, what's next, any gotchas) so
  the next session starts with full context in a few hundred tokens, not by
  re-reading source.
- Prefer delegating a single bounded "map the Node service's API" read to a
  subagent (its long file-reads don't land in your main context).

## 7. Definition of "done"

A defensible end state is: notifications, chat, filestore, docstore, clsi,
real-time, and the web backend all in Python, reusing Overleaf's frontend, with
the OT core either ported-and-fuzz-verified or deliberately kept on Node. At
that point Fleetex is a genuinely independent, mostly-Python LaTeX platform.

## 8. Delivered — current state (beyond the original scope)

The reimplementation goal is **met and exceeded**. All backend services are in
Python (notifications, chat, filestore, docstore, clsi, real-time,
document-updater incl. the fuzz-verified OT core, web) **plus** a new
`project-history` service. A self-contained browser editor replaces the reused
frontend: live collaborative editing (convergence-tested), compile-to-PDF with
an Overleaf-style errors/logs panel, a folder file-tree (create / drag-drop /
upload-into), version history with live diff + restore, sharing, presence,
resizable panes, and project download (zip incl. the compiled PDF). One-command
Docker stack; a headless GUI test harness guards it.

### 8a. Agent-native CLI (product direction beyond the port)

Fleetex is operable three ways: the **browser**, the **`fleetex` stack CLI**
(up/down/status/logs/backup/restore/doctor + reboot-safe restart policy), and
**`fleetex app` — full headless control of the application** over its HTTP API
so scripts and AI agents can use it without a browser (the "CLI-Anything"
agent-native pattern):

- auth (login/register/logout/whoami), projects (list/new/rm/rename),
- files (tree, **mkdir**, **mkdoc**, **upload**, pull, push),
- **compile** (saves the PDF), **download** (project zip), sharing (members).

Every command supports `--json` (agent-readable) with scriptable exit codes; the
session is cached; capabilities are discoverable via `fleetex app --help` and
[`SKILL.md`](SKILL.md). Stdlib-only, so the launcher stays dependency-free.

**Requirement:** any future application feature added to the `web` API should
ship a matching `fleetex app` subcommand (with `--json`) so the app stays fully
agent-controllable.
