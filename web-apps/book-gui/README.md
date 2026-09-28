# EduMatcher Order Book Viewer (`pm-book`)

The web companion to `pm-viewer`: one symbol's full order book — every price
level on both sides, the session statistics and a trade tape — with symbol
switching, dark and light themes, and font scaling. Structured the same way
as `terminal-gui`: an `apps/*` + `packages/*` npm workspace, a small Node/
Fastify bridge alongside a Vite/React frontend, Zustand for client state.

The design, and the reasons behind it, are in
[`docs-design/EduMatcher-Book-GUI.md`](../../docs-design/EduMatcher-Book-GUI.md).

**Dependencies:** `pm-api-gwy` is required — the bridge reads _everything_
through it: the live book and trades from `WS /api/v1/market-data`, today's
trades, the previous close and the session timezone from `/api/v1/history/*`,
and the symbol list from `/api/v1/reference/symbols`. It uses a read-only API
key (`gateway_id: null`), issued on the `dashboards` instance (default
`http://127.0.0.1:8081`), not on `desk` (8080). The key never reaches the
browser. `pm-stats` should run too: without it the statistics cover only the
trades seen since the symbol was opened, and the header says so. `pm-log-srv`
is optional; if unreachable the bridge falls back to stdout, or to a local
failover log file if the connection drops later.

## Project layout

```
book-gui/
  apps/
    bridge/            Fastify: pm-api-gwy market-data uplink, session books, WS fan-out
    web/               React frontend (Vite)
  packages/
    book-types/        Bridge <-> browser frame types
    lalf-client/       LALF producer client for pm-log-srv (copy of terminal-gui's)
  Dockerfile           Single-container production image
  docker-compose.yml   Compose wrapper around Dockerfile
  Makefile             Full local and container lifecycle targets
```

## Quick start

### Container

```bash
export EDUMATCHER_DATA_DIR=~/.local/share/edumatcher
make up     # detects podman or docker, builds image, starts on http://localhost:8094
make down   # stop and remove
```

**The read-only API key is looked up for you.** `make up` reads
`PM_BOOK_API_KEY` — the credential with `gateway_id: null` — out of the
deployed configuration at `$EDUMATCHER_DATA_DIR/ref_data/engine_config.json`,
exactly as `terminal-gui` does. A `PM_BOOK_API_KEY` already in the environment
always wins (`make up PM_BOOK_API_KEY=key-readonly-...`). Unlike
`terminal-gui`, the key is mandatory here, so with no key to be found
`make up` stops with an explanation instead of starting a viewer that can
show nothing. It warns when the key belongs to a gateway instance on a
different port than `API_GATEWAY_URL` points at.

The container needs network access to `pm-api-gwy`. `API_GATEWAY_URL` and
`LOG_SRV_HOST` default to `host.docker.internal`, which Docker Desktop
provides; on bare Linux Docker the Makefile adds `docker-compose.linux.yml`
(the `host-gateway` mapping); on Podman use `host.containers.internal` if
needed.

### Development server

```bash
make install   # npm ci from the lockfile
PM_BOOK_API_KEY=key-readonly-... make dev   # bridge on 5194, Vite on 8194
```

Open **http://127.0.0.1:8194**. Run `make help` for the full target list.

## Using it

- `/` opens the last book you viewed (else the first listed symbol);
  `/book/<SYMBOL>` opens a specific one, so every book has a URL.
- **`s` or `F1`** opens the symbol picker, as in `pm-viewer`: type to narrow
  by prefix, ↑/↓ to move, Enter to switch, Esc to close — or click.
- The cog opens the settings: font size (XS–XXL, Chrome and Safari only),
  **Max levels** (`Fit` fills the screen, like `pm-viewer`; 10/20/50 cap it,
  like `--depth`), and **Zebra rows** (`--zebra-lines`). The sun/moon button
  switches between the dark and light theme. All of these persist per browser.
- The footer says how many of each side's levels are on screen, so a
  truncated ladder is never silent, and how long ago the last book arrived.
- Times, the clock and the date are in the exchange session timezone that
  `pm-stats` records, as in `pm-viewer`.

## Environment variables

| Variable                                                                     | Default                                        | Description                                                             |
| ---------------------------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------- |
| `HOST` / `PORT`                                                              | `127.0.0.1` / `5194` (dev), `8094` (container) | Bridge bind address                                                     |
| `CORS_ORIGIN`                                                                | `*`                                            | CORS allow-list; restrict to your site origin in production             |
| `STATIC_DIR`                                                                 | _(unset)_                                      | Serve a built frontend from here (single-container mode)                |
| `MAX_WS_CLIENTS`                                                             | `200`                                          | Browser-tab cap                                                         |
| `WS_HEARTBEAT_SEC`                                                           | `5`                                            | `bridge_status` cadence to every tab                                    |
| `WS_PING_SEC` / `WS_PING_MAX_MISSED`                                         | `10` / `2`                                     | Reaping of half-open tabs                                               |
| `WS_MAX_BUFFERED_BYTES`                                                      | `5000000`                                      | A tab whose outbound buffer exceeds this is closed                      |
| `API_GATEWAY_URL`                                                            | `http://127.0.0.1:8081`                        | `pm-api-gwy` base URL; the market-data WebSocket URL is derived from it |
| `PM_BOOK_API_KEY`                                                            | _(required)_                                   | Read-only (`gateway_id: null`) key of that instance                     |
| `UPSTREAM_PING_SEC` / `UPSTREAM_PING_MAX_MISSED`                             | `10` / `3`                                     | Liveness of the upstream WebSocket                                      |
| `UPSTREAM_DOWN_AFTER_SEC`                                                    | `30`                                           | How long `RECONNECTING` lasts before it is reported `DOWN`              |
| `TAPE_MAX`                                                                   | `500`                                          | Trades kept per watched symbol                                          |
| `LOG_SRV_ENABLED`                                                            | `true`                                         | `false` skips even the startup probe                                    |
| `LOG_SRV_HOST` / `LOG_SRV_PORT`                                              | `127.0.0.1` / `5600`                           | `pm-log-srv` address                                                    |
| `LOG_SRV_CLIENT_ID`                                                          | `pm-book-bridge`                               | LALF client name                                                        |
| `LOG_CONNECT_TIMEOUT_SEC` / `LOG_FAILOVER_TIMEOUT_SEC` / `LOG_QUEUE_MAXSIZE` | `0.5` / `30` / `2000`                          | As in `terminal-gui`                                                    |
| `LOG_FAILOVER_DIR`                                                           | `<data dir>/logs`                              | Where the post-failover log file goes                                   |

The container's `docker-compose.yml` additionally reads `BOOK_GUI_PORT`
(host-side port mapping, default `8094`).

## Startup sequence

1. Start `pm-engine`, `pm-stats` and `pm-api-gwy` (the `dashboards` instance).
2. Optionally start `pm-log-srv`.
3. Start this GUI: `make up` (container) or `make dev` (development).

## Other Makefile targets

| Target                    | Description                                                                                                                   |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `build` / `build-debug`   | Production build of all workspaces / frontend with sourcemaps                                                                 |
| `typecheck` / `lint`      | Type-check every workspace                                                                                                    |
| `test`                    | Run the Vitest suite (bridge end-to-end against a fake `pm-api-gwy`, the whole web app against a fake bridge, and unit tests) |
| `format`                  | Format source with Prettier                                                                                                   |
| `dev-web` / `dev-bridge`  | Only the Vite dev server / only the bridge                                                                                    |
| `cbuild`                  | Build the container image without starting it                                                                                 |
| `restart` / `logs` / `ps` | Container stack lifecycle                                                                                                     |
| `cdist`                   | Container image + exported tarball in `dist/`                                                                                 |
| `clean` / `distclean`     | Remove build artifacts / also `node_modules` and the lockfile                                                                 |

The version in the top bar comes from `apps/web/src/version.json`, which
`scripts/mkbld.sh` writes for every GUI at release time.
