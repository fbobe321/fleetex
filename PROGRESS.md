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

## Testing note
Each service is its own package with its own pytest config. Run per-service
(`cd services/<name> && pytest`) or all at once via `bash services/test-all.sh`.
Do NOT `pytest services/...` from the repo root — the launcher's root config
shadows the per-service `asyncio_mode` and async tests misfire.

## Next session should do
**Phase 5 — `clsi` (★★★).** The LaTeX compiler orchestration — high-value and
isolated, but new territory (shells out to a TeX distribution, manages compile
dirs + output files). Steps:
1. Subagent-map `/data3/overleaf/services/clsi` — the compile request/response
   API (POST compile with resources, sync/word-count, output file serving), how
   it runs latexmk/pdflatex, the compile+output directory layout, caching, and
   whether it uses Mongo/Redis. Note the request/response JSON shapes exactly.
2. Create `services/clsi/`; implement the compile orchestration (shelling to a
   TeX engine — likely UNVERIFIED in CI without a TeX install, like filestore's
   conversions; structure it so the request handling/dir management IS testable).
3. Tests: request parsing, dir layout, output-file listing/serving; mark the
   actual-compile path as needs-TeX. Update this file; commit.
Read ONLY this file, ROADMAP.md, and the clsi source. Note: clsi is bigger
(~7.9k LOC) — expect this to possibly need 2 sessions; if so, split at
"request/dir handling" (session A) vs "compile+output serving" (session B).

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
