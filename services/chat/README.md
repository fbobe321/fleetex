# fleetex-chat

Python port of Overleaf's `chat` microservice (Phase 2). Mongo-only (no Redis),
two collections (`rooms` + `messages`). A room *is* a thread; the global room is
the one with no `thread_id`.

## Surface

Global messages, thread messages (send/list/get/edit/delete), threads
(`getThreads`, `getThread`, resolve/reopen, `resolved-thread-ids`), and
project-level ops (`destroyProject`, `duplicate-comment-threads`,
`generate-thread-data`, `clone-comment-threads`). `GET /status` → `chat is alive`.

Faithful to the Node original's quirks: send response re-adds `room_id` =
projectId; list responses are newest-first and strip `room_id`; grouped threads
are ascending; `getThread` 404s when a room has no messages; validation errors
are `{"message":"Validation errors"}` (400) while bad ObjectIds are plain-text
400s; unmatched routes are `{"message":"Not found"}` (404).

## Run & test

```bash
pip install -e services/_kit -e "services/chat[dev]"
pytest services/chat            # full HTTP + unit tests, no DB needed
python -m fleetex_chat          # serve on :3010 (needs Mongo)
```

Default port **3010**. Flip into the stack via the Overleaf container's
`CHAT_URL` env var (see [`../README.md`](../README.md)).
