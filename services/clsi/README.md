# fleetex-clsi

Python port of Overleaf's `clsi` (Common LaTeX Service Interface) — the LaTeX
compiler orchestration (Phase 5). **No Mongo/Redis** (state is on-disk +
in-memory). Default port **3013**.

## Surface

- `POST /project/:id[/user/:uid]/compile` → `{compile: {status, outputFiles, buildId, stats, timings, ...}}`
- `POST .../compile/stop` → 204; `DELETE /project/:id[/user/:uid]` (clear cache) → 204
- `GET .../sync/code` (code→pdf) and `GET .../sync/pdf` (pdf→code)
- `GET .../wordcount`
- `GET|POST /project/:id/status` → `OK`; `GET /status` → `CLSI is alive`; `GET /health_check`

Compile status enum: `success`, `failure`, `stopped-on-first-error`, `error`,
`timedout`, `terminated`, plus `compile-in-progress` (423), `conflict`/
`missing-updates` (409), `unavailable` (503).

## What's reproduced vs what needs TeX

**Fully ported & tested in Python (no TeX):** request parsing (RequestParser),
resource writing + extraneous cleanup + `.project-sync-state`, compile-dir/output-dir
layout, the **latexmk argv construction**, output-file discovery, build-dir caching
(`generated-files/<buildId>/`, `output.pdf` size), response JSON assembly, the
**synctex & texcount output parsers**, and the per-project lock.

**Needs a TeX toolchain (UNVERIFIED in CI):** actually running `latexmk`,
`synctex`, `texcount`. The command runner is **injectable** — `LocalCommandRunner`
shells out to the real binaries (the Dockerfile installs TeX Live); tests inject a
fake toolchain so the whole orchestration is exercised end-to-end.

**Deferred:** URL-backed resources (need the filestore UrlCache), Docker
sandboxed compiles (Server-Pro only), PDF caching, output-zip, clsi-cache shards.
Output *serving* is by nginx in upstream (the `url` fields point at it), not this app.

## Run & test

```bash
pip install -e services/_kit -e "services/clsi[dev]"
pytest services/clsi                 # orchestration + parsers, no TeX needed
python -m fleetex_clsi               # serve on :3013 (real compiles need TeX Live)
```
