# fleetex-project-history

Document **version history** for Fleetex — the "see past versions / restore" feature.

Each stored version is a full-content snapshot of one document, taken at a save
point (a document-updater flush, an explicit save, a restore, or a manual
checkpoint). Versions carry a per-project monotonic number so the whole project
shares one ordered timeline. Consecutive identical snapshots of a doc are
de-duplicated.

## Granularity

This is **snapshot-at-save-point** history, not per-keystroke track-changes. It's
enough to browse and restore prior versions; the finer op-level history can layer
on later by consuming document-updater's `applied-ops` feed into the same store.

## API

| Method & path | Purpose |
| --- | --- |
| `POST /project/:id/doc/:doc/version` | Record a snapshot `{content, pathname?, user_id?, source?}` (dedup vs latest). |
| `GET /project/:id/versions?limit=&before=` | Project timeline (metadata, newest first). |
| `GET /project/:id/doc/:doc/versions` | One document's timeline. |
| `GET /project/:id/version/:v` | A version's full content. |
| `GET /project/:id/doc/:doc/diff?from=&to=` | Segment diff (`{u|i|d}`) + unified diff between two versions. |
| `POST /project/:id/doc/:doc/restore/:v` | Restore a past version into the live doc (via document-updater setDoc). |
| `DELETE /project/:id` | Purge a project's history. |

## Wiring

document-updater checkpoints a snapshot here on every flush (best-effort, set
`PROJECT_HISTORY_URL`). Restore calls back into document-updater via
`DOCUMENT_UPDATER_URL`.

Runs on port **3054**. `python -m fleetex_project_history`.
