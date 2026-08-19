# EduMatcher Log Operator Console (`pm-log-ui`)

A browser-based operator console over the logs collected by `pm-log-srv`.
It answers "is anything wrong right now, and has someone dealt with it?" —
a live tail, a searchable/aggregable history, a fingerprint-grouped alert
list with shared acknowledgement, a process registry, and the existing
`pm-log-cli diagnose` heuristics surfaced on a schedule.

**Dependencies:** `pm-log-srv` must be running and reachable (its LALF-PS
publish/pull ports, default `5601`/`5602`) with `log.db` on a filesystem
path the bridge can read. The Diagnostics view additionally needs
`pm-log-cli` on `PATH` wherever the bridge runs; without it, that one
endpoint returns a friendly 503 and every other view keeps working.

## Project layout

```
log-gui/
  apps/
    web/                           React + Vite frontend (six views, WS live tail, theming)
    bridge/                        Fastify: LALF-PS subscriber + log.db reader + WS fan-out + ack store
  packages/
    log-types/                     Shared TS types (rows, filters, issues, WS frame schema)
    log-query/                     Filter -> parameterised SQL compiler + aggregate query builders
  Dockerfile                       Single-container production image
  docker-compose.yml               Compose wrapper around Dockerfile
  Makefile                         Full local and container lifecycle targets
```

Data flow: `pm-log-srv` publishes live rows over LALF-PS (ZeroMQ) and stores
everything in `log.db` (SQLite). The bridge holds exactly one upstream
LALF-PS subscription regardless of browser tab count, opens `log.db`
read-only for history/search/aggregation, fingerprints `WARNING+` rows into
issues, and owns a separate, small SQLite file for acknowledgement state —
the only thing this project writes anywhere.

## Quick start

### Container

```bash
make up     # detects podman or docker, builds image, starts on http://localhost:8091
make down   # stop and remove
```

If you are behind a proxy (or firewall) you need to use `make proxy-up` instead of `make up` to build and run the container. This target will set the HTTP_PROXY and HTTPS_PROXY environment variables for the build and run steps. See the `make help` output for more details. It asumes the two environment variables `http_proxy` and `https_proxy` are set in your shell. If they are not set, the Makefile will default to using `http://host.containers.internal:9000` for both.



The container needs to reach `pm-log-srv`'s LALF-PS ports (`5601`/`5602` by
default) and a filesystem path to `log.db`; see the comments in
`docker-compose.yml` for how those are wired in (two separate volumes: one
read-only mount of `pm-log-srv`'s data directory, one read-write for this
project's own ack store).

### Development server

```bash
make install   # npm ci from lockfile
make dev       # starts the bridge (port 5191) + web dev server (port 8191) together
```

Open **http://127.0.0.1:8191**. This assumes `pm-log-srv` is already
running locally with its default ports (`5600` LALF, `5601` PUB, `5602`
PULL) and `data/log.db` exists. Run `make help` for the full target list.

## Environment variables

| Variable                 | Default                                    | Description                                           |
| -------------------------- | --------------------------------------------- | -------------------------------------------------------- |
| `HOST`                     | `127.0.0.1`                                    | Bridge bind address                                       |
| `PORT`                      | `5191` (dev), `8091` (container)                | Bridge listen port                                         |
| `CORS_ORIGIN`               | `*`                                             | CORS allow-list; restrict to your site origin in production |
| `STATIC_DIR`                | _(unset)_                                       | Serve a built frontend from here (single-container mode)  |
| `LOG_SRV_HOST`              | `127.0.0.1`                                     | Host running `pm-log-srv`                                  |
| `LOG_SRV_PUB_PORT`          | `5601`                                          | `pm-log-srv` LALF-PS publish port                          |
| `LOG_SRV_PULL_PORT`         | `5602`                                          | `pm-log-srv` LALF-PS pull port                             |
| `SUB_ID_PREFIX`             | `pm-log-bridge`                                 | LALF-PS subscription id prefix                             |
| `LEASE_SEC`                 | `30`                                            | LALF-PS subscription lease, in seconds                     |
| `LOG_DB_PATH`               | `<data dir>/log.db`                             | Path to `pm-log-srv`'s SQLite database (read-only)          |
| `ACK_STORE_PATH`            | `<data dir>/log-ui-acks.db`                     | Path to this project's own acknowledgement store (read-write) |
| `ISSUES_RETENTION_DAYS`     | `7`                                             | How long fingerprinted issues are kept                     |
| `ISSUES_MIN_LEVEL`          | `WARNING`                                       | Minimum log level fingerprinted into an issue              |
| `ISSUES_ALERT_LEVEL`        | `ERROR`                                         | Minimum log level that raises an alert                     |
| `ERROR_RATE_NORMAL_PER_MIN` | `5`                                              | Error-rate threshold: normal band                          |
| `ERROR_RATE_ELEVATED_PER_MIN` | `20`                                           | Error-rate threshold: elevated band                        |
| `ERROR_RATE_SEVERE_PER_MIN` | `100`                                            | Error-rate threshold: severe band                          |
| `PROCESS_SILENCE_SEC`       | `30`                                             | Seconds of silence before a process is flagged stalled      |
| `QUERY_MAX_ROWS`            | `5000`                                          | Row cap on interactive queries                             |
| `EXPORT_MAX_ROWS`           | `1000000`                                       | Row cap on CSV/export queries                              |
| `LIVE_BATCH_THRESHOLD_PER_SEC` | `50`                                          | Live-tail rows/sec above which the bridge batches WS frames |
| `LOG_CLI_COMMAND`           | `pm-log-cli`                                    | Command used to invoke `pm-log-cli --format json diagnose` |
| `EDUMATCHER_DATA_DIR`       | _(auto-detected)_                               | Overrides the data directory `LOG_DB_PATH`/`ACK_STORE_PATH` default from |

`<data dir>` resolves the same way the Python side does: `$EDUMATCHER_DATA_DIR`
if set, else `<repo>/src/data` when running from a source checkout, else
`~/.local/share/edumatcher`.

The `PORT` default above (`5191`) applies only when running the bridge
directly via `make dev`/`tsx`; the container always sets `PORT=8091`
explicitly via its Dockerfile, so the two never conflict.

## Startup sequence

1. Start `pm-log-srv` first (it must already be publishing on its LALF-PS
   ports and have created `log.db`).
2. Optionally have `pm-log-cli` on `PATH` if you want the Diagnostics view.
3. Start this GUI: `make up` (container) or `make dev` (development). The
   bridge connects to `pm-log-srv` on startup; if it's unreachable, retry by
   restarting the bridge once `pm-log-srv` is up.

## Other Makefile targets

| Target        | Description                                                          |
| -------------- | ---------------------------------------------------------------------- |
| `build`         | Type-check + production build of all workspaces                        |
| `build-debug`   | Frontend build with sourcemaps, unminified                             |
| `typecheck`     | Type-check every workspace                                             |
| `test`          | Run unit tests (Vitest): log-query, bridge fingerprinting/issue-index/ack-store |
| `lint`          | Alias for `typecheck`                                                  |
| `format`        | Format source with Prettier                                            |
| `dev-web`       | Only the web dev server (Vite)                                         |
| `dev-bridge`    | Only the Fastify bridge (LALF-PS + log.db + WS)                        |
| `cnt-build`     | Build the container image via compose without starting it              |
| `proxy-up`      | Start the container stack through a local dev proxy                    |
| `restart`       | Restart the container stack                                            |
| `logs`          | Follow container logs                                                  |
| `ps`            | Show container stack status                                            |
| `dist`          | Build a distributable: container image + exported OCI tarball in `dist/` |
| `clean`         | Remove local build artifacts and `dist/`                               |

## Other relevant information

**Settings the frontend needs:** `alertLevel`, `issuesMinLevel`,
`processSilenceSec` and the `errorRate` thresholds reach the browser through
`GET /api/ui-config` (`apps/bridge/src/routes/ui-config.ts`). The frontend
deliberately keeps no local defaults for these — extend `UiConfig` in
`packages/log-types/src/ui-config.ts` and read it via `useUiConfig()` rather
than introducing a component-level constant.

**A note on `package-lock.json` and a known npm dedup bug:** `make install`
runs `npm ci` once `package-lock.json` exists. If that lockfile is ever
deleted and regenerated from scratch, some npm versions (observed on npm
11.17.0) crash during dependency resolution with `TypeError: Invalid
Version:` — the workspace root and `apps/web` both resolve the same `vite`/
`esbuild` pair, which trips an arborist dedup bug. `make install` already
works around this: when no lockfile exists yet, it runs
`npm install --no-dedupe` for the first resolution, then relies on plain
`npm ci` from then on. If you hit the crash calling `npm install` directly,
rerun with `--no-dedupe`.

**Keeping the bridge in sync with `pm-log-srv`:** two places re-implement
pieces of `pm-log-srv`'s Python surface in TypeScript and carry a
`MAINTENANCE:`-style comment naming their Python counterpart —
`packages/log-query/src/filter-to-sql.ts` (mirrors
`edumatcher.log_srv.pubsub.LogFilter.sql_where()` /
`edumatcher.log_cli.queries.query_events()`) and
`apps/bridge/src/lalf-ps-uplink.ts` (mirrors the LALF-PS wire messages
implemented in `edumatcher.log_srv.pubsub`). When `pm-log-srv`'s schema,
LALF-PS message set, or `log_cli` query shape changes, update the
corresponding TypeScript side and re-run `npm test`.
