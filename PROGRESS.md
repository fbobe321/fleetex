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

## Testing note
Each service is its own package with its own pytest config. Run per-service
(`cd services/<name> && pytest`) or all at once via `bash services/test-all.sh`.
Do NOT `pytest services/...` from the repo root — the launcher's root config
shadows the per-service `asyncio_mode` and async tests misfire.

## Next session should do
**Phase 4 — `docstore` (★★).** Back to Mongo territory (JSON docs), but with
archiving semantics. Steps:
1. Subagent-map `/data3/overleaf/services/docstore` — routes, the `docs` (and any
   `docOps`/deleted-docs) collections + exact shapes, how doc lines/ranges are
   stored, versioning, and the **archiving-to-object-storage** behavior (does it
   call filestore/persistor? gzip? inline vs archived docs?). Note Mongo/Redis use.
2. Create `services/docstore/` on the kit; implement routes; mongomock tests.
3. Update this file; commit.
Read ONLY this file, ROADMAP.md, and the docstore source. notifications/chat are
the Mongo-service template; filestore showed the streaming/persistor pattern if
docstore archives to object storage.

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
