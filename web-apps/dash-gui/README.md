# EduMatcher Operator Dashboard (`pm-dash`)

A Grafana-style dashboard of the whole exchange: every process's health,
trading activity, participants, order books and gateways, live and over
time. Structured the same way as `book-gui`: an `apps/*` + `packages/*` npm
workspace, a small Node/Fastify bridge alongside a Vite/React frontend,
Zustand for client state.

The design, and the reasons behind it, are in
[`docs-design/EduMatcher-Operator-Dashboard.md`](../../docs-design/EduMatcher-Operator-Dashboard.md).

> **Status:** scaffold (WP-C1). The bridge serves the app, greets each tab
> on `/ws` and answers `/api/bridge/status`; the pm-monitor uplink and
> history routes arrive in WP-C2, the dashboard itself in WP-D1–D4.

**Dependencies:** `pm-monitor` is required — the bridge subscribes to its PUB
socket (`monitor.pub_port`, default 5611) for the 1 Hz `health.snapshot` and
the `health.event` stream, and reads its `metrics.db` read-only for history.
No API key or credential of any kind is involved. `pm-log-srv` is optional;
if unreachable the bridge falls back to stdout, or to a local failover log
file if the connection drops later.

## Project layout

```
dash-gui/
  apps/
    bridge/            Fastify: pm-monitor uplink, WS fan-out, metrics.db history
    web/               React frontend (Vite)
  packages/
    dash-types/        Bridge <-> browser frame types, shared by both apps
    lalf-client/       The bridge's own logging to pm-log-srv (LALF)
```

## Quick start

### Container

```bash
export EDUMATCHER_DATA_DIR=~/.local/share/edumatcher   # where metrics.db lives
make up          # builds the image and starts it on http://localhost:8095
make logs        # follow the bridge's output
make down
```

The data directory is mounted read-only at `/backend-data`. pm-monitor binds
`127.0.0.1` by default; for the container to reach it, open it with
`EDUMATCHER_GATEWAY_BIND_HOST=0.0.0.0` (or `monitor.bind_address`) on the
backend, and set `MONITOR_HOST` if it is not on this host.

### Development server

```bash
make install
make dev         # bridge on 127.0.0.1:5195, Vite on http://localhost:8195
```

Vite proxies `/api` and `/ws` to the bridge, so open the Vite URL.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `5195` | Bridge bind address (the container uses `0.0.0.0:8095`) |
| `MONITOR_HOST` | `127.0.0.1` | Where pm-monitor's PUB socket is reachable (`monitor.host`) |
| `MONITOR_PUB_PORT` | `5611` | `monitor.pub_port` |
| `MONITOR_DOWN_AFTER_SEC` | `3` | No snapshot for this long → pm-monitor shown DOWN |
| `METRICS_DB_PATH` | `<data dir>/metrics.db` | pm-monitor's history, opened read-only |
| `EDUMATCHER_DATA_DIR` | `src/data` in a checkout | The data directory, as the Python processes resolve it |
| `CORS_ORIGIN` | `*` | Restrict when exposed beyond localhost |
| `STATIC_DIR` | unset | Built web app to serve (set in the container) |
| `MAX_WS_CLIENTS` | `200` | Tabs beyond this are refused with 1013 |
| `WS_PING_SEC` / `WS_PING_MAX_MISSED` | `10` / `2` | Reaping of half-open tabs |
| `WS_MAX_BUFFERED_BYTES` | `5000000` | A tab whose outbound buffer exceeds this is closed |
| `LOG_SRV_ENABLED` / `LOG_SRV_HOST` / `LOG_SRV_PORT` | `true` / `127.0.0.1` / `5600` | The bridge's own logging to pm-log-srv |
| `LOG_FAILOVER_DIR` | `<data dir>/logs` | Local log file when pm-log-srv drops |

## Ports

| What | Port |
|---|---|
| Container web | `8095` |
| Dev web (Vite) | `8195` |
| Dev bridge | `5195` |
| pm-monitor PULL / PUB | `5610` / `5611` |

## Other Makefile targets

`make help` lists them all: `typecheck`, `test`, `build`, `cbuild` (image
only), `cdist` (image + OCI tarball in `dist/`), and the `ghcr-*` /
`cpush` publishing targets shared by every EduMatcher GUI.
