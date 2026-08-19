# EduMatcher Market Data Terminal (`pm-terminal`)

A read-only, credential-free Bloomberg-style viewer for the EduMatcher
exchange. Structured the same way as `log-gui`: an `apps/*` + `packages/*`
npm workspace, a small first-party Node/Fastify backend alongside a
Vite/React frontend, Zustand for client state.

**Dependencies:** `pm-md-gwy` must be reachable for live market data (CALF
TCP, default port `5570`) — without it the UI renders its disconnected
state. `pm-api-gwy` is needed for historical REST reads (default
`http://127.0.0.1:8080`) using a read-only API key. `pm-log-srv` is
optional; if unreachable the bridge falls back to stdout, or to a local
failover log file if the connection drops later.

## Project layout

```
terminal-gui/
  apps/
    bridge/            Fastify: CALF TCP uplink + WS fan-out + history proxy
    web/                React frontend (Vite)
  packages/
    calf-protocol/      CALF wire grammar (TS port of md_gateway/protocol.py)
    lalf-client/         LALF producer client for pm-log-srv
    terminal-types/       Types shared by web + bridge
  Dockerfile            Single-container production image
  docker-compose.yml     Compose wrapper around Dockerfile
  Makefile               Full local and container lifecycle targets
```

## Quick start

### Container

```bash
make up     # detects podman or docker, builds image, starts on http://localhost:8090
make down   # stop and remove
```


If you are behind a proxy (or firewall) you need to use `make proxy-up` instead of `make up` to build and run the container. This target will set the HTTP_PROXY and HTTPS_PROXY environment variables for the build and run steps. See the `make help` output for more details. It asumes the two environment variables `http_proxy` and `https_proxy` are set in your shell. If they are not set, the Makefile will default to using `http://host.containers.internal:9000` for both.


The container needs network access to `pm-md-gwy`'s CALF port and
`pm-api-gwy`; see the comments in `docker-compose.yml` for the `*_HOST`
variables to override on Podman or non-Docker-Desktop setups.

**`host.docker.internal` resolution:** the `*_HOST` defaults reference
`host.docker.internal` to reach processes on the host machine. Docker
Desktop (macOS/Windows) injects this name automatically. On bare Linux with
plain Docker it requires an `extra_hosts` entry using the `host-gateway`
pseudo-address, which Podman does not support. To keep a single base
`docker-compose.yml` that works everywhere, that entry lives in a separate
`docker-compose.linux.yml` overlay — the Makefile appends it automatically
when it detects `docker` on Linux. On Podman the name `host.containers.internal`
serves the same purpose; override `CALF_HOST`, `API_GATEWAY_URL`, and
`LOG_SRV_HOST` to point there if needed.

### Development server

```bash
make install   # npm ci from lockfile
make dev       # bridge on port 5190, Vite dev server on port 8190
```

Open **http://127.0.0.1:8190**. Run `make help` for the full target list.

## Environment variables

| Variable                        | Default                 | Description                                                                          |
| ---------------------------------- | -------------------------- | ---------------------------------------------------------------------------------------- |
| `HOST` / `PORT`                     | `127.0.0.1` / `5190` (dev), `8090` (container) | Bridge bind address                                                     |
| `CORS_ORIGIN`                       | `*`                          | CORS allow-list; restrict to your site origin in production                               |
| `STATIC_DIR`                        | _(unset)_                    | Serve a built frontend from here (single-container mode)                                  |
| `MAX_WS_CLIENTS`                    | `200`                        | Browser-tab cap                                                                            |
| `CALF_HOST` / `CALF_PORT`           | `127.0.0.1` / `5570`          | `pm-md-gwy` address                                                                        |
| `CALF_CLIENT_ID`                    | `pm-terminal-bridge`          | `HELLO.CLIENT` identifier sent to the gateway                                              |
| `CALF_PING_INTERVAL_SEC`            | `60`                          | Keepalive cadence — the gateway's idle timer only resets on inbound client bytes, so a bridge that merely listens needs to ping or it is disconnected after the gateway's idle timeout (default 300s) |
| `INDEX_IDS`                         | _(empty)_                    | Comma-separated index ids to subscribe to (`SUB\|CH=INDEX`); CALF has no "list indexes" request |
| `API_GATEWAY_URL`                   | `http://127.0.0.1:8080`       | `pm-api-gwy` base URL for historical REST reads                                            |
| `PM_TERMINAL_API_KEY`               | _(empty)_                    | Read-only (`gateway_id: null`) API key, history reads only                                 |
| `LOG_SRV_ENABLED`                   | `true`                        | `false` skips even the startup probe                                                       |
| `LOG_SRV_HOST` / `LOG_SRV_PORT`     | `127.0.0.1` / `5600`           | `pm-log-srv` address                                                                       |
| `LOG_CONNECT_TIMEOUT_SEC`           | `0.5`                         | Startup probe and each reconnect attempt                                                   |
| `LOG_FAILOVER_TIMEOUT_SEC`          | `30`                          | Grace window before the one-way switch to file logging                                     |
| `LOG_QUEUE_MAXSIZE`                 | `2000`                        | Bounded backlog while reconnecting                                                         |
| `LOG_FAILOVER_DIR`                  | `<data dir>/logs`              | Where the post-failover log file goes                                                      |
| `EDUMATCHER_DATA_DIR`               | _(auto-detected)_             | Overrides the data directory `LOG_FAILOVER_DIR` defaults from                              |

The container's `docker-compose.yml` additionally reads `TERMINAL_GUI_PORT`
(host-side port mapping, default `8090`) from the shell environment. The
`PORT` default above (`5190`) applies only when running the bridge directly
via `make dev`/`tsx`; the container always sets `PORT=8090` explicitly via
its Dockerfile, so the two never conflict.

## Startup sequence

1. Start `pm-md-gwy` (required for any live data).
2. Start `pm-api-gwy` (required for historical reads and the read-only API
   key used by this GUI).
3. Optionally start `pm-log-srv` — this GUI degrades to stdout/file logging
   without it, it does not block startup.
4. Start this GUI: `make up` (container) or `make dev` (development).

## Other Makefile targets

| Target        | Description                                                          |
| -------------- | ---------------------------------------------------------------------- |
| `build`         | Type-check + production build of all workspaces                        |
| `build-debug`   | Frontend build with sourcemaps, unminified                             |
| `typecheck`     | Type-check every workspace                                             |
| `test`          | Run test suite (Vitest)                                                |
| `lint`          | Alias for `typecheck`                                                  |
| `format`        | Format source with Prettier                                            |
| `dev-web`       | Only the web dev server (Vite)                                         |
| `dev-bridge`    | Only the Fastify bridge (CALF uplink + WS + history proxy)             |
| `cnt-build`     | Build the container image via compose without starting it              |
| `proxy-up`      | Start the container stack through a local dev proxy                    |
| `restart`       | Restart the container stack                                            |
| `logs`          | Follow container logs                                                  |
| `ps`            | Show container stack status                                            |
| `dist`          | Build a distributable: container image + exported OCI tarball in `dist/` |
| `clean`         | Remove local build artifacts and `dist/`                               |

## Other relevant information

**Theme:** dark by default — the working default for a trading screen —
with a full light palette for bright rooms and projectors. Both are
CSS-variable sets swapped by a `.dark` class on `<html>`, so the same
Tailwind class names render either. Amber is the accent (trading-floor
convention, legible on both a near-black lobby display and a bright
monitor); green and red are reserved exclusively for price direction.
Density (Lobby / Standard / Dense) and theme both persist to
`localStorage`; neither is a mode — every route and data point stays
reachable at any setting.

**Statelessness:** unlike `log-gui`, the bridge holds no durable state of
its own beyond in-memory CALF bookkeeping. The only volume in
`docker-compose.yml` is for the LALF failover log, written only when
`pm-log-srv` is unreachable.
