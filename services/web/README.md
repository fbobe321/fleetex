# fleetex-web (auth slice)

Python port of the **authentication slice** of Overleaf's `web` service (Phase 7).
`web` is the monolith — this is the **first slice** (login/sessions + the internal
project-join API). Later slices (project CRUD, editor page, file tree, serving the
frontend) come in subsequent sessions. Default port **3000**.

## What's here

- **Sessions & cookies** — the critical Node-interop piece. Cookie value
  `s:<sid>.<HMAC-SHA256-b64-no-pad>` (sign with current `SESSION_SECRET`, verify
  against all secrets), Redis `sess:<sid>` JSON store with the mandatory
  `validationToken = "v1:"+sid[-4:]`, and the `session.passport.user` object shape.
  **A session written here is readable by the Node services (and vice-versa).**
- **Passwords** — bcrypt `$2a$12$` (no pepper, reject >72 bytes, sanitize control chars).
- **Auth endpoints** — `POST /login` (`{redir:/project}` 200, wrong password 401,
  invalid email 400, writes signed cookie + session), `POST /logout` (destroys the
  Redis session), `POST /user/password/update` (session-backed).
- **`POST /project/:id/join`** — the internal API `real-time` calls (basic-auth):
  computes `privilegeLevel` (owner/readAndWrite/review/readOnly) from project
  ownership/collaborators/public+token access, `isRestrictedUser`, and returns the
  (redacted-if-restricted) project view.

This closes the **cookie/session gap** flagged in Phase 6 (real-time): a browser
that logs in here gets a session the real-time service can read.

## Project CRUD slice (Phase 7b)

- **List** — `POST /api/project` → `{totalSize, projects[]}` with per-user
  `archived`/`trashed` booleans, `accessLevel`/`source`, owner/lastUpdatedBy
  injected. Cascading owner→invite→token dedupe; filters (archived/trashed/
  ownedByUser/sharedWithUser) + sort. `GET /user/projects` → lightweight list.
- **Create** — `POST /project/new` → builds the project doc + rootFolder tree +
  `main.tex` doc metadata, returns `{project_id, owner_ref, owner}`.
- **Rename/settings** — `POST /project/:id/rename` (owner), `.../settings`
  (compiler/name/lang, write access), `.../settings/admin` (publicAccessLevel, owner).
- **Archive/trash** — `POST`/`DELETE /project/:id/archive` and `.../trash`
  (per-user ObjectId arrays; archive⇄trash are mutually exclusive per user).
- **Delete** — `DELETE /project/:id` (owner) → soft-delete into `deletedProjects`.
- **Clone** — `POST /project/:id/clone` (read access) → copies the tree with fresh ids.

Name validation matches upstream (≤150 chars, no `/`/`\`, no leading/trailing
whitespace). **Deviation:** upstream mixes `:Project_id`/`:project_id` casing per
route; this port normalizes to lowercase `/project/:id` throughout (a fresh
frontend, not the Node bundle). Doc/file **contents** live in docstore/filestore
(bridged/deferred) — this slice manages the project document + tree metadata.

## Deferred / stubbed (documented)

Registration (admin-only upstream; use `UserManager.create_user` here), CSRF
(csurf — needed only if serving the Node frontend), rate limiting, captcha,
HaveIBeenPwned check, email sending, SSO/SAML/LDAP, `loginEpoch` parallel-login
lock, bcrypt auto-upgrade. The rest of `web` (project/editor/files/frontend) is
future Phase-7 slices.

## Run & test

```bash
pip install -e services/_kit -e "services/web[dev]"
pytest services/web            # passwords, cookie signing, sessions, authz, HTTP — no Mongo/Redis needed
python -m fleetex_web          # serve on :3000 (needs Mongo + Redis)
```
