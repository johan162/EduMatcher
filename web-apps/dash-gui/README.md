# EduMatcher Operator Dashboard (`pm-dash`)

A Grafana-style dashboard of the whole exchange: every process's health,
trading activity, participants, order books and gateways, live and over
time. Structured the same way as `book-gui`: an `apps/*` + `packages/*` npm
workspace, a small Node/Fastify bridge alongside a Vite/React frontend,
Zustand for client state.

The design, and the reasons behind it, are in
[`docs-design/EduMatcher-Operator-Dashboard.md`](../../docs-design/EduMatcher-Operator-Dashboard.md).

> **Status:** the bridge is complete (WP-C2): live snapshots and events on
> `/ws`, history over REST. The shell is in (WP-D1): top bar with the
> exchange status, session, time range (`?from=now-1h`), history refresh,
> theme and settings, and the banner while data is not live. The
> widget library is in (WP-D2): `/widgets` shows every widget with
> synthetic data, in either theme. The dashboard rows arrive in WP-D3–D4.
> `make test-e2e` (repo root) checks the built page in headless Chrome
> against a real exchange.

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

## Bridge interface

`/ws` (WebSocket): `hello` (version, pm-monitor UP/DOWN, session timezone),
then the latest `snapshot` when pm-monitor is up, then every `snapshot`
(1 Hz), `event` and `monitor_state` as they come. Snapshot and event
payloads are pm-monitor's `health.snapshot` / `health.event`, unchanged
(snake_case; `packages/dash-types/src/health.ts`, pinned to
`spec/messages/health.yaml` by `tests/test_dash_types_mirror.py`). A tab
that does not read is cut off rather than buffered for.

REST (history from `metrics.db`, read-only; ranges at most 7 days):

| Endpoint | Returns |
|---|---|
| `GET /api/series?name=&label=&source=&from=&to=` (or `range=5m\|15m\|1h\|6h\|24h\|7d`) | One series, at most 1000 points; from the 10 s samples, or from the minute roll-up when that holds older data in the range than the 10 s samples still have. `source=` is required when several processes record the name |
| `GET /api/series/multi?name=&labels=a,b&source=&range=` | Several labels of one metric (all of them when `labels=` is left out, at most 50) |
| `GET /api/rate?name=&label=&source=&range=&bucket=1m\|1h` | Counter increments per bucket, summed over sources (and labels when none is given) |
| `GET /api/daily?name=&label=&source=&days=30` | Daily totals for the latest trading dates |
| `GET /api/events?range=&kind=&limit=` or `?after_seq=` | The event log; `after_seq` is how a reconnecting tab catches up |
| `GET /api/bridge/status` | Uplink state (and whether pm-monitor is reachable at all), counts, session timezone, `metrics.db` health, tabs, logging |

A bad parameter (or one given twice) is a 400 `{error, message}`; an unknown
label or source a 404; a `metrics.db` that is missing or cannot be read a 503.
The bridge follows the file at `METRICS_DB_PATH`, so one replaced under it
(`pm-opctl-cli clear --all`) is picked up without a restart.

**Times.** Everything on the wire is UTC: a request gives epoch ms or
ISO-8601 with `Z` or an offset (a time without a zone is refused), a
response gives epoch ms. Buckets start on the exchange's session clock
(`exchange.session_timezone`; with pm-monitor down, the zone it pinned in
`metrics.db`), so an hourly bar is an hour of the exchange's day. The web
app shows every time in the session timezone, never the browser's — through
`apps/web/src/lib/time.ts` only, which a test enforces.

In the container, history is unavailable (503) while pm-monitor is stopped:
a clean stop removes `metrics.db-wal`/`-shm`, and through the read-only mount
SQLite cannot recreate them. It returns as soon as pm-monitor runs.

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
