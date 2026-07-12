# fleetex-docstore

Python port of Overleaf's `docstore` microservice (Phase 4). Mongo (single `docs`
collection) + **archiving to object storage**. No Redis.

## Surface (~18 routes)

Single-doc reads (`get`, `peek`, `raw`, `deleted`), project reads (`getAllDocs`,
`doc-with-ranges`, `ranges`, `doc-versions`, `doc-deleted`, `comment-thread-ids`,
`tracked-changes-user-ids`, `has-ranges`), writes (`POST` update, `PATCH`
soft-delete, deprecated `DELETE`), and archive ops (`archive`, per-doc `archive`,
`unarchive`, `destroy`). `GET /status` → `docstore is alive`.

### Fidelity notes

- **rev** starts at 1; increments **only when lines or ranges change** (not
  version-only). Optimistic lock via `{rev: previousRev}` filter (one retry on
  conflict, then 500).
- **Archiving**: payload is plain JSON `{lines, ranges, rev, schema_v:1}` keyed
  `"<projectId>/<docId>"`; non-s3 backends md5-verify on read. `get` unarchives
  back into Mongo; `peek` reads archived content without writing (sets
  `x-doc-status`).
- docViews **omit null fields** (no `null`s in JSON).
- Errors: NotFound→404, DocModified/VersionDecremented→409, invalid id / other→500;
  update validation→400/413; `unarchive`→**200** (not 204).

### Implementation choices (documented deviations)

- The Node original uses aggregation-pipeline updates with `$literal` wrapping
  (to avoid `$`-interpretation in a pipeline); we use a plain `$set` dict update,
  which stores values literally and gives the **same** optimistic-lock behavior.
- Archive backends: an in-memory store (tests) and a filesystem store are
  provided; **S3/GCS come with the object-persistor port later**.

## Run & test

```bash
pip install -e services/_kit -e "services/docstore[dev]"
pytest services/docstore                 # core + HTTP tests, no external deps
python -m fleetex_docstore               # serve on :3016 (needs Mongo)
```

Default port **3016**. Flip via the Overleaf container's `DOCSTORE_URL`.
