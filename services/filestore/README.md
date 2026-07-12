# fleetex-filestore

Python port of Overleaf's `filestore` microservice (Phase 3). Storage-only — **no
Mongo, no Redis**. This phase implements the **local-filesystem backend**; S3/GCS
come later.

## Surface

- **Template files:** `HEAD/GET/POST /template/:id/v/:version/:format` (+ `/:sub_type` GET).
- **Generic passthrough:** `GET /bucket/:bucket/key/*`.
- **History blobs:** `GET /history/global/hash/:hash`, `GET /history/project/:historyId/hash/:hash`.
- **Ops:** `GET /status` → `filestore is up`, `GET /health_check` → `OK`.

### Fidelity notes (the tricky bits)

- **Range requests return `200`, not `206`** — the body is the sliced bytes with
  no `Content-Range`/`Accept-Ranges` (matching the Node original). First `bytes=`
  range only, inclusive end, parsed against a 1 GiB ceiling; malformed → full file.
- GET sets no `Content-Type`/`ETag`; HEAD sets only `Content-Length`.
- Missing → `404` (empty); any other error → `500` with the message as plain text.
- fs key layout: non-blob keys are **flattened** (`/`→`_`); history blobs keep
  real subdirectories. Writes are atomic (temp dir + rename).
- `?cacheWarm=true` returns `OK` without transferring the file.

### Known gap

Image conversion (`?format=png` / `?style=thumbnail|preview`) is **implemented but
unverified** — it shells out to ImageMagick `convert`/`pdftocairo` + `optipng`
(installed in the Dockerfile) exactly like the original, but isn't exercised in
Fleetex CI. Missing binaries or failures return `500` (ConversionError), matching Node.

## Run & test

```bash
pip install -e services/_kit -e "services/filestore[dev]"
pytest services/filestore                 # storage + HTTP tests, no external deps
BACKEND=fs FILESTORE_PATH=/tmp/fs python -m fleetex_filestore   # serve on :3009
```

Default port **3009**. Flip via the Overleaf container's `FILESTORE_URL`
(see [`../README.md`](../README.md)).
