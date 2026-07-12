# fleetex-document-updater

Python port of Overleaf's `document-updater` — the **operational-transformation
collaboration engine** (Phase 8, the hard/optional core). No Mongo directly; live
state in Redis, snapshots bridged from docstore. Default port **3003**.

## The OT core (correctness-first)

`ot_text.py` is a **line-for-line port** of the ShareJS text OT type
(`sharejs/types/text.js` + `helpers.js`): `apply`, `compose`, `transform_position`,
`transform_component` (all four insert/delete cases + comments), and the
`transform_x` N² driver with split/recursion. Op format: a list of components,
each `{"i":str,"p":int}` / `{"d":str,"p":int}` / `{"c":str,"p":int,"t":id}`.

**Verified by a TP1 convergence fuzzer** (`tests/test_ot_text.py`): random
concurrent op pairs must satisfy `apply(apply(s,a),b') == apply(apply(s,b),a')`
(a'=transform(a,b,'left'), b'=transform(b,a,'right')). CI runs thousands of checks;
a standalone 200k-iteration run passed with 0 violations. TP1 *is* "identical
converged state" — the roadmap's mandated gate before trusting the engine.

## The lifecycle

- **RedisManager** — the live doc working set with Node-compatible keys
  (`doclines:{docId}` JSON array, `DocVersion`, `DocOps` history, `Ranges`,
  `PendingUpdates:{docId}`), so it interoperates with the ported real-time service.
- **engine.process_update** — the server transform loop (model.js): transform the
  incoming op forward through every concurrent op in `[base_v, current_v)` as side
  `'left'`, then apply; version advances by the number of applied ops.
- **DocumentUpdater** — get-doc (Redis-first, docstore fallback), process pending
  updates, commit to Redis, and **publish applied ops to the `applied-ops` channel**
  the real-time service consumes (`{project_id, doc_id, op}`).
- **DispatchManager** — BLPOP the `pending-updates-list[-shard]` queues real-time
  RPUSHes to, and process the doc.
- **HTTP** — `GET /project/:id/doc/:docId?fromVersion=N` (lines+version+catch-up ops,
  docstore fallback), `POST` setDoc, flush, `DELETE` doc/project.

## Verification (no Node needed)

The full pipeline is tested end-to-end with fakeredis: two and many concurrent
clients editing from the same version all **converge** to the same document (Redis
state == transform-folded applied ops), and applied ops publish in the shape
real-time consumes.

## Deferred (documented)

Full ranges-tracker (track-changes merge/undo — only position-shifting is ported),
history-ot doc type (this ports `sharejs-text-ot`), project-history queueing,
hashing/size-limit edge cases, and the setDoc line-diff (setDoc here replaces the
snapshot rather than diffing into ops).

## Run

```bash
pip install -e services/_kit -e "services/document-updater[dev]"
pytest services/document-updater      # OT fuzzer + pipeline convergence, no infra
python -m fleetex_document_updater     # serve :3003 + dispatchers (needs Redis + docstore)
```
