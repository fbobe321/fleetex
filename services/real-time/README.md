# fleetex-realtime

Python port of Overleaf's `real-time` microservice (Phase 6) — the websocket
layer the browser editor connects to. Default port **3026**.

## ⚠️ Biggest caveat: Socket.IO protocol version

Overleaf's `real-time` runs the **legacy Socket.IO v0.9 protocol**, and the
frontend ships the matching `socket.io-client@0.9`. This Python port uses
**`python-socketio` (Engine.IO v3/v4)**, which is **NOT wire-compatible** with
that old client. So this service is a faithful reimplementation of the *logic and
integration contracts*, but a drop-in swap against the existing frontend bundle
would require **updating the browser socket.io client** (or a protocol shim). This
is an inherent boundary, flagged loudly rather than hidden.

## What IS fully faithful (protocol-agnostic, tested)

These interoperate with the existing Node `web` / `document-updater` / other
`real-time` instances byte-for-byte, because they're plain JSON over Redis/HTTP:

- **Redis pub/sub bridge** — `editor-events` (`{room_id, message, payload}`) and
  `applied-ops` (`{doc_id, op}`) shapes; the applied-op fan-out (source client gets
  `otUpdateApplied {v, doc}`, others get the full op, `dup` skipped, `tsRT` stripped).
- **document-updater queue** — `queue_change` RPUSHes `PendingUpdates:{docId}` then
  `pending-updates-list[-shard]` with `projectId:docId`, in that order.
- **ConnectedUsersManager** — the `clients_in_project:{pid}` SET + `connected_user:{pid}:{cid}`
  HASH with the right TTLs and the `client_age < 10s` refresh filter.
- **WebApiManager** (`/project/:id/join`) and **document-updater** HTTP fetch, with
  the exact status→error mapping.
- **Event logic** — join/joinDoc (with the JS `unescape(encodeURIComponent)` line
  encoding + restricted-user comment stripping), applyOtUpdate (metadata stamping +
  op-type authorization), clientTracking, disconnect→flush.

## Bridged, not reimplemented (still Node this phase)

`web` (authorization), `document-updater` (doc storage + OT), and Redis are talked
to over their existing HTTP/Redis contracts.

## Simplifications (documented gaps)

- **Session/cookie auth** — the Node service reads a signed `overleaf.sid` cookie →
  Redis session → user. This port takes the user id via the socket `auth` payload;
  wiring the full cookie/session-store handshake is deferred.
- Per-doc/-project Redis channel subscription optimization, drain-rate pacing, PDF
  caching of ranges, and the debug endpoints are simplified.

## Run & test

```bash
pip install -e services/_kit -e "services/real-time[dev]"
pytest services/real-time            # bridge + managers + server + HTTP, no Redis/TeX needed
python -m fleetex_realtime           # serve on :3026 (needs Redis + web + document-updater)
```
