# EduMatcher Log Operator Console (`pm-log-ui`)

A browser-based operator console over the logs collected by `pm-log-srv`.
It answers "is anything wrong right now, and has someone dealt with it?" —
a live tail, a searchable/aggregable history, a fingerprint-grouped alert
list with shared acknowledgement, a process registry, and the existing
`pm-log-cli diagnose` heuristics surfaced on a schedule.

> **Design** — the full design proposal (data-availability audit, protocol
> reasoning, per-view wireframes, and the open questions this build resolves
> or defers) lives at
> **[docs-design/EduMatcher-log-GUI.md](../../docs-design/EduMatcher-log-GUI.md)**.
> This README is the **developer** reference: project layout and getting
> started.

## Project layout

```
log-gui/
  apps/
    web/                           React + Vite frontend (six views, WS live tail, theming)
    bridge/                        Fastify: LALF-PS subscriber + log.db reader + WS fan-out + ack store
  packages/
    log-types/                     Shared TS types (rows, filters, issues, WS frame schema)
    log-query/                     Filter -> parameterised SQL compiler + aggregate query builders
  Dockerfile / docker-compose.yml  Single-container production image
  Makefile                         Full local and container lifecycle targets
```

Data flow: `pm-log-srv` publishes live rows over LALF-PS (ZeroMQ) and stores
everything in `log.db` (SQLite). The bridge holds exactly one upstream
LALF-PS subscription regardless of browser tab count, opens `log.db`
read-only for history/search/aggregation, fingerprints `WARNING+` rows into
issues, and owns a separate, small SQLite file for acknowledgement state —
the only thing this project writes anywhere.

## Getting started

**Fastest path — container:**

```bash
make up     # detects podman or docker, builds image, starts on http://localhost:8091
make down   # stop and remove
```

The container needs to reach `pm-log-srv`'s LALF-PS ports (`5601`/`5602` by
default) and a filesystem path to `log.db`; see the comments in
`docker-compose.yml` for how those are wired in.

**Local development:**

```bash
make install   # npm ci from lockfile
make dev       # starts the bridge (port 8091) + web dev server (port 5178) together
```

Open **http://127.0.0.1:5178**. Run `make help` for a full list of targets.

This assumes `pm-log-srv` is already running locally with its default ports
(`5600` LALF, `5601` PUB, `5602` PULL) and `data/log.db` exists. Override with
environment variables (`LOG_SRV_HOST`, `LOG_SRV_PUB_PORT`, `LOG_SRV_PULL_PORT`,
`LOG_DB_PATH`, `ACK_STORE_PATH`) — see `apps/bridge/src/config.ts` for the
full list and defaults, which mirror the design's §20 config reference.

### Settings the frontend needs

`alertLevel`, `issuesMinLevel`, `processSilenceSec` and the `errorRate`
thresholds reach the browser through **`GET /api/ui-config`**
(`apps/bridge/src/routes/ui-config.ts`). The frontend deliberately keeps **no
local defaults** for these — a fallback constant in a component is how these
settings previously ended up parsed-but-ignored, with the bridge reading an
environment variable while the UI used a hard-coded number. When adding a
setting the UI must respect, extend `UiConfig` in
`packages/log-types/src/ui-config.ts` and read it via `useUiConfig()`; do not
introduce a component-level constant.

Anything shared between the two sides belongs in `@edumatcher/log-types` for
the same reason — `classifyErrorRate()` lives there so the bridge and the
browser cannot disagree about where a severity band begins.

### A note on `package-lock.json` and a known npm dedup bug

`make install` runs `npm ci` once `package-lock.json` exists, exactly like
`config-gui`. If that lockfile is ever deleted and regenerated from scratch,
some npm versions (observed on npm 11.17.0) crash during dependency
resolution with `TypeError: Invalid Version:` thrown from
`@npmcli/arborist`'s dedup step. The cause: the workspace root (via
`vitest`'s `vite` peer dependency) and `apps/web` (which needs its own real
`vite` devDependency to run the dev server/build) both resolve to the
*same* `vite` version, which pulls the *same* `esbuild` version at both
nesting levels — and that specific "two nodes, identical version, should
dedupe" case trips the bug in that npm release. `config-gui` never hits
this because its older `vitest` pin happens to resolve a different `vite`/
`esbuild` pair than its own `apps/web` — an accident of version history,
not a deliberate design.

`make install`'s `install` target already works around this: when no
lockfile exists yet, it runs `npm install --no-dedupe` for the first
resolution (skipping the crashing dedup step), then relies on plain
`npm ci` against the resulting lockfile from then on. If you hit the
`Invalid Version:` crash anyway (e.g. calling `npm install` directly
instead of through `make install`), rerun with `--no-dedupe`.

## Developer commands

```bash
npm test              # unit tests: log-query, bridge fingerprinting/issue-index/ack-store (Vitest)
npm run typecheck     # type-check every workspace
npm run build         # type-check + build the production frontend bundle
```

## Diagnostics endpoint and `pm-log-cli`

`GET /api/diagnostics` shells out to `pm-log-cli --format json diagnose`
rather than reimplementing the seven heuristics in TypeScript, so there is
exactly one implementation to keep correct (see design §12.2, §23 open
question 1). This means the Diagnostics view needs `pm-log-cli` installed
and on `PATH` wherever the bridge runs; if it is not, the endpoint returns a
friendly 503 and every other view keeps working. Override the command with
the `LOG_CLI_COMMAND` environment variable if it isn't invoked as
`pm-log-cli` in your deployment (e.g. `poetry run pm-log-cli`).

## Maintenance — keeping the bridge in sync with `pm-log-srv`

Two places re-implement pieces of `pm-log-srv`'s Python surface in
TypeScript, and both carry a `MAINTENANCE:`-style comment naming their
Python counterpart:

- `packages/log-query/src/filter-to-sql.ts` mirrors
  `edumatcher.log_srv.pubsub.LogFilter.sql_where()` /
  `edumatcher.log_cli.queries.query_events()`.
- `apps/bridge/src/lalf-ps-uplink.ts` mirrors the LALF-PS wire messages
  documented in `docs-design/EduMatcher-log-srv.md` §15 and implemented in
  `edumatcher.log_srv.pubsub`.
- `apps/bridge/src/fingerprint.ts` implements the normalisation rules from
  `docs-design/EduMatcher-log-GUI.md` §11.1 — there is no Python
  counterpart to mirror, since fingerprinting is new surface this project
  introduces.

When `pm-log-srv`'s schema, LALF-PS message set, or `log_cli` query shape
changes, update the corresponding TypeScript side and re-run `npm test`.
