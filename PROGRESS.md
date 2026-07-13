# Fleetex Reimplementation — Progress Log

> Update this at the end of every session. Keep it short. The next session reads
> **only this file + ROADMAP.md** to get oriented — cheap context, no source re-reads.

## Current status
- **Launcher (v0.1.1):** shipped — runs the real Node Overleaf via Docker. ✅
- **Phase 0 (foundations):** DONE ✅ — `services/_kit` (`fleetex-service-kit`):
  `Settings`, `create_app` (FastAPI + Mongo/Redis lifespan + /health, /status,
  optional `status_text`), JSON logging, lazy db factories, contract harness. 12 tests.
- **Phase 1 (`notifications`):** DONE ✅ — `services/notifications`
  (`fleetex-notifications`). 8 routes + /status + /health_check + 404 catch-all,
  dedup/forceCreate, soft-read via `$unset templateKey`, bulk delete,
  Express-compatible JSON. 19 tests (+1 skipped = live-Node diff), port 3042.
- **Phase 2 (`chat`):** DONE ✅ — `services/chat` (`fleetex-chat`). Two
  collections (rooms+messages). Global + thread messages, threads
  (getThreads/getThread/resolve/reopen/resolved-thread-ids), destroyProject,
  duplicate/generate/clone. Matches Node quirks: send re-adds room_id=projectId,
  lists newest-first & strip room_id, grouped threads ascending, empty-thread
  404, `{"message":"Validation errors"}` vs plain-text ObjectId 400s,
  `{"message":"Not found"}` 404. 28 tests pass, boots under uvicorn, port 3010.
  - **Same caveat as Phase 1:** verified vs spec + mongomock, not yet diffed vs
    a live Node instance (`FLEETEX_NODE_BASE=... pytest -k contract_vs_node`).

- **Phase 3 (`filestore`):** DONE ✅ — `services/filestore` (`fleetex-filestore`).
  Storage-only, no Mongo/Redis. Local-FS backend fully ported (flattened keys vs
  subdirectory blobs, atomic temp+rename writes, range reads, md5, copy/delete).
  Routes: template HEAD/GET/POST (+sub_type), generic `/bucket/:bucket/key/*`,
  history global+project blob GETs, /status (`filestore is up`), /health_check
  (`OK`). Matches quirks: **range returns 200 not 206** with sliced body & no
  range headers; GET sets no Content-Type; HEAD sets only Content-Length;
  404-or-500-only errors; cacheWarm→`OK`. 23 tests, boots under uvicorn.
  - **Gaps (documented):** S3/GCS backends not ported (fs only). Image
    conversion (format/style → imagemagick+optipng) is coded but UNVERIFIED (no
    binaries in CI); failures → 500 as in Node.

- **Phase 4 (`docstore`):** DONE ✅ — `services/docstore` (`fleetex-docstore`).
  Mongo (`docs`) + **archiving to object storage**. ~18 routes: single-doc
  (get/peek/raw/deleted), project reads (getAllDocs/doc-with-ranges/ranges/
  doc-versions/doc-deleted/comment-thread-ids/tracked-changes-user-ids/has-ranges),
  writes (POST update, PATCH soft-delete, deprecated DELETE→500), archive/
  unarchive/destroy. rev bumps only on lines/ranges change; version-decrement→409;
  optimistic-lock retry; docViews omit null fields; unarchive→200. Archive payload
  = plain JSON `{lines,ranges,rev,schema_v:1}` key `projectId/docId`; peek reads
  archived w/o writing Mongo (x-doc-status). 19 tests, boots under uvicorn.
  - **Deviations (documented):** plain `$set` update instead of Node's
    `$literal` aggregation pipeline (same optimistic-lock behavior). Archive
    backends = in-memory (tests) + fs; **S3/GCS deferred to the persistor port**.
  - Kit gained `Response.headers` in the contract harness (for x-doc-status).

- **Phase 5 (`clsi`):** DONE ✅ — `services/clsi` (`fleetex-clsi`). LaTeX compiler
  orchestration, no Mongo/Redis. Ports: RequestParser, ResourceWriter (+extraneous
  cleanup + .project-sync-state), compile/output dir layout, **latexmk argv build**,
  OutputFileFinder + build-dir caching (generated-files/<buildId>/, output.pdf size),
  compile-response assembly (status enum, outputFiles url), synctex + texcount
  **parsers**, LockManager (423/503). Routes: compile (+user), stop, clear,
  sync/code, sync/pdf, wordcount, status. 24 tests, boots under uvicorn.
  - **The command runner is INJECTABLE** — `LocalCommandRunner` shells out to real
    latexmk/synctex/texcount (Dockerfile installs TeX Live); tests inject a fake
    toolchain so the whole flow is exercised end-to-end. Runner plumbing itself is
    verified with a real subprocess; only the **TeX binaries** are unverified (none
    in CI). **Deferred:** URL resources (need filestore UrlCache), docker sandboxed
    compiles, PDF caching, output-zip.

- **Phase 6 (`real-time`):** DONE ✅ — `services/real-time` (`fleetex-realtime`).
  Websocket layer via python-socketio (ASGI) + FastAPI HTTP, Redis-backed.
  Fully-faithful protocol-agnostic core (tested): Redis bridge (editor-events +
  applied-ops shapes, fan-out with {v,doc} ack vs full-op, tsRT strip, dup skip),
  document-updater queue (PendingUpdates:{doc} + pending-updates-list), Connected
  UsersManager (SET+HASH keys+TTLs+10s refresh filter), WebApiManager join,
  joinDoc (JS line encoding + restricted comment strip), applyOtUpdate (metadata
  + op-type authorization), clientTracking, disconnect→flush. HTTP: /, /status,
  /clients, count-connected-clients, sendMessage, drain, disconnect. 31 tests,
  boots under uvicorn (socket.io handshake responds).
  - **⚠️ HEADLINE CAVEAT:** Node uses **Socket.IO v0.9 protocol**; python-socketio
    is EIO3/4 — **NOT wire-compatible** with Overleaf's frontend socket.io-client.
    A real swap needs the browser client updated. The Redis/HTTP interop IS
    byte-compatible with Node web/document-updater.
  - **Simplified (documented):** cookie/session-store auth (user id taken from
    socket `auth` payload instead), per-channel subscription optimization, drain
    pacing. web + document-updater are bridged (still Node), not reimplemented.

## Testing note
Each service is its own package with its own pytest config. Run per-service
(`cd services/<name> && pytest`) or all at once via `bash services/test-all.sh`.
Do NOT `pytest services/...` from the repo root — the launcher's root config
shadows the per-service `asyncio_mode` and async tests misfire.

## Milestone: the "tidy tier" (Phases 0-6) is COMPLETE ✅
All 6 services + foundations done: notifications, chat, filestore, docstore, clsi,
real-time. 156 tests, CI green. web + document-updater/OT still Node (bridged).

- **Phase 7a (`web` — auth slice):** DONE ✅ — `services/web` (`fleetex-web`).
  FIRST slice of the monolith. Sessions (`s:<sid>.<HMAC-SHA256>` cookie —
  **verified byte-identical to Node's cookie-signature via openssl**; Redis
  `sess:<sid>` JSON + `validationToken v1:sid[-4:]`; `passport.user` shape),
  bcrypt `$2a$12$` passwords, `POST /login` (signed cookie + session, 401 wrong
  pw, 400 bad email), `POST /logout`, `POST /user/password/update`, and the
  internal **`POST /project/:id/join`** (basic-auth) with full privilegeLevel +
  isRestrictedUser + redacted project view. 23 tests, boots under uvicorn.
  **This closes the real-time cookie/session gap** — a browser logging in here
  gets a session real-time can read.
  - **Deferred:** registration endpoint (use UserManager.create_user), CSRF,
    rate-limit, captcha, HIBP, email, SSO/LDAP, loginEpoch lock. Rest of web
    (project/editor/files/frontend) = future Phase-7 slices.

- **Phase 7b (`web` — project CRUD slice):** DONE ✅ — `services/web/projects.py`.
  `POST /api/project` list (cascading owner→invite→token dedupe, per-user
  archived/trashed booleans, accessLevel/source, owner injection, filters+sort),
  `GET /user/projects`, `POST /project/new` (doc+tree+main.tex), rename/settings/
  settings-admin (owner/write auth), archive/trash (per-user arrays), soft-delete
  →deletedProjects, clone (tree copy w/ fresh ids). Name validation (≤150, no /\,
  no lead/trail ws). 37 web tests. **Also fixed a latent authz bug:** logged-in
  token members (tokenAccess*_refs on tokenBased projects) now get read access.
  - **Deferred:** doc/file *contents* (docstore/filestore bridge), history id,
    TPDS, example-template creation (needs filestore). Route casing normalized to
    lowercase (upstream mixes :Project_id/:project_id).

- **Phase 7c (`web` — editor page-load slice):** DONE ✅ — `services/web/editor.py`.
  3 read endpoints: `GET /project/:id` (bootstrap JSON: user, userSettings from
  user.ace, wsUrl, compiler, rootDocId, ...), `GET /project/:id/entities` (flat
  file-tree walk), `GET /project/:id/doc/:doc_id` (**bridges the docstore service**
  for lines/version/ranges; pathname from the projects tree; ?plain=true→text).
  Enriched the join model view (mainBibliographyDoc_id, features defaults, etc).
  46 web tests. **This is the first real cross-service bridge** (web→docstore HTTP).
  - **Deferred:** filestore binary download, spelling, otMigrationStage/history
    (stubbed), anonymous-token editor access.

- **Phase 7d (`web` — file-tree ops slice):** DONE ✅ — `services/web/file_tree.py`.
  add doc/folder, rename, move, delete, upload — all write-auth, all publish an
  `editor-events` Redis message (reciveNewDoc/reciveNewFolder/reciveEntityRename/
  reciveEntityMove/removeEntity/reciveNewFile) consumed by real-time. SafePath name
  rules, dup + blocked-name + folder-into-descendant guards, 2000-entity cap, 50MB
  upload. Bridges docstore (doc create/delete), filestore (binary hash). 60 web tests.
  - **Deviation:** whole-tree save vs positional-$ (same result). Binary filestore
    *persistence* deferred (storage-only filestore has no project-file route; hash computed).

## Milestone: web is functionally usable ✅
web now does auth + project CRUD + editor bootstrap + doc bridge + full file-tree
ops. A user can log in, manage projects, open one, load/edit the file tree.
8 services, 217 tests, CI green. Still Node: the OT engine (document-updater/
project-history) + serving the actual frontend bundle.

- **Phase 7e (`web` — minimal frontend, browser-openable):** DONE ✅ —
  `services/web/frontend.py` + editor.py additions. Self-contained vanilla-JS
  pages (login/register/dashboard/editor, no build/CDN). Added: open registration
  (`POST /register`, config-gated), doc-save (`POST /project/:id/doc/:doc_id`
  bridging docstore), `/project/:id/tree` (entities+ids), content-negotiation on
  `GET /project/:id` (HTML for browsers, JSON for `?format=json`). 69 web tests.
  - **VERIFIED END-TO-END against real Mongo+Redis (docker):** browser flow
    register→create→open→**edit→save→read-back**→add-file, content confirmed
    persisted in Mongo's `docs` collection via web→docstore bridge. First real
    multi-service run of the Python stack.
  - **Fixed a real config bug:** docstore passed `env={}` to the kit Settings so it
    ignored `MONGO_URL` (always used compose default `mongo:27017`). Now reads real
    env. (Other services were unaffected — they manage their own conn or use no DB.)
  - **Single-user editing over HTTP.** Live multi-user OT needs Phase 8.

## How to run the stack (verified)
`docker run mongo:8.0` + `redis:6.2`, then
`MONGO_URL=... python -m fleetex_docstore` (:3016) and
`MONGO_URL=... REDIS_URL=... DOCSTORE_URL=http://localhost:3016 SESSION_SECRET=... python -m fleetex_web` (:3000).
Open http://localhost:3000 → register → create/open a project.

- **Phase 8 (`document-updater` — THE OT CORE):** DONE ✅ — `services/document-updater`
  (`fleetex-document-updater`). The collaboration engine. `ot_text.py` = line-for-line
  port of the ShareJS text OT type (apply/transform/compose/transform_x). **Verified
  by TP1 convergence fuzzer: 200,000 random concurrent-op checks, 0 violations.**
  Lifecycle: RedisManager (Node-compatible keys: doclines/DocVersion/DocOps/
  PendingUpdates), engine.process_update (server transform loop, side 'left'),
  DocumentUpdater (get-doc w/ docstore fallback, process pending, publish applied-ops),
  DispatchManager (BLPOP pending-updates-list shards), HTTP (GET doc + ops, setDoc,
  flush, delete). 33 tests incl. multi-client pipeline convergence. Interoperates with
  the ported real-time service via Redis (pending-updates in, applied-ops out).
  - **Deferred:** full ranges-tracker track-changes (only position-shift ported),
    history-ot doc type, project-history queueing, setDoc line-diff.

## 🎉🎉 MILESTONE: all 8 backend services + OT core are in Python
notifications, chat, filestore, docstore, clsi, real-time, web (auth+projects+
editor+files+frontend), document-updater. **9 packages, 259 tests, CI green.**
Fleetex is a functionally-complete, mostly-Python Overleaf. What remains Node:
NOTHING structural — project-history (undo/version-history) is the last upstream
service not ported, and it's optional. The frontend bundle is a fresh minimal one.

## LIVE-COLLAB WIRED ✅ (verified end-to-end)
Browser multi-user editing works. `services/web/collab_js.py` = browser OT client
(text OT ported to JS — **cross-checked byte-identical to the Python engine over
5000 random transforms via node**) + minimal Socket.IO-v4 client over WebSocket +
ShareJS inflight/buffer CollabDoc. Editor page (`frontend.py`) uses it. Added the
missing server piece: **real-time now subscribes to `applied-ops`/`editor-events`**
(`pubsub.py`) and document-updater starts its BLPOP dispatchers.
- **Verified with real Mongo+Redis+docstore+document-updater+real-time+web + two
  socket.io clients:** concurrent edits (A prepends, B appends from same version)
  CONVERGE — clients + server all agree.
- **3 real bugs the live run caught (mocks couldn't):**
  1. kit `create_app` used a `lifespan`, so FastAPI IGNORED `@app.on_event` →
     dispatchers + pubsub never started. Fixed: kit `on_startup` hook.
  2. web `/join` 500'd — `build_project_view` returned the rootFolder tree with
     ObjectId ids (not JSON-serializable). Fixed: `authorization.json_safe`.
  3. document-updater dispatchers dropped updates on redis socket-timeout during
     blocking BLPOP. Fixed: dedicated blocking redis connection + finite timeout.
- **Demo run:** see "How to run the stack" above + set WEBSOCKET_URL=http://<rt-host>:3026
  for web, and run real-time (:3026) + document-updater (:3003) too.

## One-command launch ✅
`docker-compose.yml` at repo root runs the whole Python stack: `docker compose up
--build` → mongo + redis + all 9 services on the compose network (only web:3000 and
real-time:3026 published to host; browser WEBSOCKET_URL=http://localhost:3026).
**Verified:** built + ran the core stack via compose, live-collab converged through
it; all 9 services build+start (clsi's TeX Live layer is heavy but valid). Added the
missing document-updater Dockerfile.

## Compile button wired to clsi ✅ (real LaTeX compile verified)
- clsi serves output files (`GET /project/:id/build/:build/output/:file`, what nginx
  did upstream).
- web `compile.py`: `ClsiManager` gathers each doc's live content from
  document-updater, POSTs the clsi compile request, rewrites output URLs to
  web-proxied paths; routes `POST /project/:id/compile` + `GET /project/:id/output/
  :build/:file` (proxies clsi). Config: CLSI_URL, DOCUMENT_UPDATER_URL.
- Editor page: "Compile ▶" button + PDF preview pane (iframe), Ctrl/Cmd+Enter.
- **VERIFIED end-to-end in the compose stack (clsi has TeX Live):** wrote real LaTeX,
  POST compile → status success + output.pdf, fetched the 65 KB `%PDF-1.7` through
  web's proxy. Actual latexmk compilation on the Python stack.

## Live cursors + presence ✅
Server side already existed (clientTracking.*); wired the browser:
- collab.js: caretCoords (mirror-div), colorFor, posToRowCol/rowColToPos.
- editor page: presence avatar bar, remote-cursor overlay (colored caret + name
  label), sends clientTracking.updatePosition on cursor move (throttled), handles
  clientUpdated/clientDisconnected, getConnectedUsers on join. Prunes stale peers.
- real-time server: preserve client-supplied display name in the broadcast.
- **VERIFIED end-to-end (2 socket clients):** A moves cursor -> B receives it with
  name; getConnectedUsers=2; disconnect broadcast received. (Pixel rendering is
  best-effort/standard mirror-div; data flow proven.)

## Images in compiles ✅ (verified)
filestore: project-file store (POST/GET /project/:id/file/:fid). web: FilestoreClient
POSTs binaries there; ClsiManager includes fileRefs as url resources; clsi
ResourceWriter fetches url resources into the compile dir. Editor: Upload button.
**VERIFIED in compose:** uploaded a PNG -> \includegraphics -> compile success -> PDF.

## Sharing / collaborators ✅ (verified)
web/collaborators.py: GET/POST /project/:id/members + DELETE /project/:id/members/:uid
(owner-only add/remove by email, moves between readAndWrite/review/readOnly). Editor:
Share button. Registered BEFORE file-tree routes so /members/:id isn't shadowed by
the /{entity_type}/:id catch-all. **VERIFIED in compose:** Alice shares -> Bob (a
different user) sees it in his dashboard (readWrite/invite) and can open it.

## Editor upgrade ✅
`frontend.py` editor page: LaTeX syntax highlighting (a `<pre class=hl>` layer
behind a transparent-text textarea — commands/%comments/{braces} colored,
HTML-escaped first so content can't inject markup), line-number gutter with
synced scroll, Tab→2 spaces, PDF download link on successful compile. The
verified OT/textarea binding is untouched — `updateView()` only reads `ed.value`
to render the overlay. collab.js OT engine unchanged. Highlighting logic
node-tested; JS syntax `node --check`ed.

## Security hardening ✅ (3 fronts)
- **real-time socket auth**: the client used to hand real-time its own `user_id`
  in the socket.io auth payload — any socket could impersonate any account. Now
  `session_auth.py` reads the signed `overleaf.sid` cookie off the WebSocket
  handshake, verifies it with the shared `SESSION_SECRET`, loads `sess:<sid>`
  from the shared Redis, and takes the id from `passport.user._id`; client
  `user_id` is ignored. **Verified:** a web-minted cookie resolves in real-time;
  a tampered one is rejected. compose shares SESSION_SECRET/COOKIE_NAME.
- **web CSRF**: `security.py` Origin-guard middleware — unsafe methods carrying a
  foreign browser Origin get 403; no-Origin requests (curl, tests, real-time's
  Basic-auth `/join`) pass. Atop the existing SameSite=Lax cookies.
- **clsi compile sandbox**: client `flags` flowed straight into the latexmk argv
  (a caller could pass `-shell-escape` → RCE). Now flags are validated
  (shell-escape/write18/output-directory/jobname/... rejected) and every compile
  runs with a locked-down TeX env (`shell_escape=f`, `openin_any=p`,
  `openout_any=p`).

## project-history service ✅ (NEW — the last unported upstream service)
`services/project-history` (`fleetex-project-history`, port 3054). Document
**version history**: snapshot-at-save-point versions in Mongo (`history_versions`),
per-project monotonic version numbers, consecutive-identical dedup. API: record
snapshot, project/doc timeline, full-version content, segment diff (`{u|i|d}`) +
unified diff, and **restore** (pushes a past version back into the live doc via
document-updater setDoc). `diff.py` = token-level exact diff. document-updater
checkpoints a version here on every flush (best-effort `HistoryClient`, gated on
`PROJECT_HISTORY_URL`; absent by default so it never breaks editing). Wired into
compose. **21 service tests + 2 document-updater hook tests. Verified on real
Mongo:** timeline/dedup/pathname-carry/diff/restore/scoped-purge, and the
document-updater→project-history HTTP contract end-to-end.

### History UI in the editor ✅
`web/history.py` proxies the browser's history calls to project-history (single
origin, cookie-authorized: reads need read access, recording needs write). Save
(⌘/Ctrl+S) records a version. The editor has a slide-in **History panel**
(🕘 History): lists the open doc's versions, click one to see a color-coded
"what changed in this version" diff (server `{u|i|d}` segments), and **Restore**
loads that version's content back through the *verified OT edit path*
(`makeOp`+`submitLocal`) so every connected client converges — no setDoc
divergence. 6 web proxy tests. **Verified end-to-end through the real web proxy →
real project-history → real Mongo:** record, timeline, diff, restore-fetch.

## Next session should do
Phases 0-8 COMPLETE + live-collab + compose + compile + presence. Remaining work is polish/hardening, user's
choice:
- **project-history** service (the one unported upstream service: version history/
  undo). Optional; similar hard-core caution as OT.
- **Live-collab wiring**: connect the frontend editor to real-time socket.io +
  document-updater so multi-user editing works in the browser end-to-end (the pieces
  all exist now — real-time + document-updater + web + OT are all ported).
- **A compose file** running the whole Python stack (web+real-time+document-updater+
  docstore+clsi+filestore+chat+notifications+mongo+redis) for one-command launch.
- **Hardening**: contract-diff any service against its Node original; fill deferred
  gaps (filestore project-file route, S3 backends, ranges track-changes).
Ask the user. Read ONLY this file + ROADMAP before starting.

## Services ported (Node → Python)
_(none yet)_

| Service | Status | Version flipped | Notes |
|---------|--------|-----------------|-------|
| notifications | DONE ✅ | Python | |
| chat | DONE ✅ | Python | |
| filestore | DONE ✅ | Python | + project-file store (images) |
| docstore | DONE ✅ | Python | |
| clsi | DONE ✅ | Python | sandboxed (flag validation + locked TeX env) |
| real-time | DONE ✅ | Python | socket handshake cookie-authenticated |
| web (backend) | DONE ✅ | Python | auth+projects+editor+files+frontend+sharing+compile+CSRF |
| document-updater | DONE ✅ | Python | OT core; TP1-fuzzed; flush→history hook |
| project-history | DONE ✅ | Python | snapshot versions + diff + restore (port 3054) |
| history-v1 | n/a | – | folded into project-history (snapshot model) |

## Gotchas / decisions log
- Frontend stays JS/TS (React); we reuse Overleaf's. Only backends go to Python.
- Reference the Node source in the sibling repo at `/data3/overleaf/services/<name>`.
