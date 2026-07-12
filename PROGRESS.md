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

## Testing note
Each service is its own package with its own pytest config. Run per-service
(`cd services/<name> && pytest`) or all at once via `bash services/test-all.sh`.
Do NOT `pytest services/...` from the repo root — the launcher's root config
shadows the per-service `asyncio_mode` and async tests misfire.

## Next session should do
**Phase 6 — `real-time` (★★★★).** The websocket layer — HARDER (stateful,
socket.io protocol, Redis pub/sub). This is where the client editor connects.
Steps:
1. Subagent-map `/data3/overleaf/services/real-time` — the socket.io events the
   frontend emits/expects (joinProject, joinDoc, applyOtUpdate, leaveDoc, etc.),
   the Redis pub/sub channels bridging to document-updater, session/auth handshake,
   and the HTTP surface (/status, health). Note exact event names + payloads.
2. Create `services/real-time/`; implement a `python-socketio` (ASGI) server
   matching the frontend's events. Redis via redis-py (kit already provides it).
   document-updater is still Node at this point — bridge to it via Redis.
3. Tests: socket.io connection + event round-trips (python-socketio has a test
   client); Redis interactions (fakeredis). Update this file; commit.
Read ONLY this file, ROADMAP.md, and the real-time source. NOTE: real-time needs
`python-socketio` (new dep) — the kit's create_app is HTTP-only, so this service
mounts a socket.io ASGI app alongside. Likely needs care; may split into
"connection/handshake" vs "doc events" if large.

## Services ported (Node → Python)
_(none yet)_

| Service | Status | Version flipped | Notes |
|---------|--------|-----------------|-------|
| notifications | not started | – | |
| chat | not started | – | |
| filestore | not started | – | |
| docstore | not started | – | |
| clsi | not started | – | |
| real-time | not started | – | |
| web (backend) | not started | – | |
| document-updater | not started | – | hard core — do last |
| project-history | not started | – | hard core — do last |
| history-v1 | not started | – | hard core — do last |

## Gotchas / decisions log
- Frontend stays JS/TS (React); we reuse Overleaf's. Only backends go to Python.
- Reference the Node source in the sibling repo at `/data3/overleaf/services/<name>`.
