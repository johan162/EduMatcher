# EduMatcher Trading GUI (`pm-trading-ui`)

A graphical trading terminal for the EduMatcher exchange simulator, with
three role-aware personas:

| Role             | Landing screen    | Access                                           |
| ----------------- | ------------------- | --------------------------------------------------- |
| **TRADER**         | Trading Workspace     | Order entry, blotter, fills, positions               |
| **MARKET_MAKER**   | Quote Management       | Two-sided quote management, positions                |
| **ADMIN**           | System Dashboard        | Session control, gateway management, risk, monitor log |

**Dependencies:** `pm-api-gwy` must be running and reachable (REST +
WebSocket, default `http://localhost:8080`). This is the GUI's only backend
dependency — there is no direct connection to any other `pm-*` process, and
no separate bridge process (see Project layout).

## Project layout

```
trader-gui/
  apps/
    web/                    React/TypeScript SPA (pm-trading-ui)
      src/
        api/                 apiFetch + typed endpoint helpers
        ws/                  ManagedSocket, WebSocketManager, subscriptions, seq tracking
        store/               Zustand stores (auth, session, book, halt, …)
        queries/             TanStack Query hooks
        hooks/               useRole, useWsEvent, useFlash, useConnectionHealth, …
        lib/                 formatters, validators (Zod), priceUtils, schedule, bootstrap
        types/               Core TypeScript types
        router/              RoleGuard
        components/          layout/, market/, shared/, notifications/, help/, command/
        pages/               Route-level page components
      test/                  Vitest component + unit tests
    serve/                   pm-trading-ui-serve static file server
      serve.ts               Zero-extra-dependency Node http server (SPA fallback + optional /api proxy)
  test/
    setup-dom.ts             Vitest global setup
  Dockerfile                 Single-container production image
  docker-compose.yml         Compose wrapper around Dockerfile
  Makefile                   Full local and container lifecycle targets
  .env.example                Copy to .env and adjust for local development
```

## Quick start

### Container

```bash
make up     # detects podman or docker, builds image, starts on http://localhost:8093
make down   # stop and remove
```

The container's static server proxies `/api/*` (REST + WebSocket upgrades)
to `pm-api-gwy` on the same port; see `API_PROXY_TARGET` below and the
comments in `docker-compose.yml`.

### Development server

```bash
make install   # npm install
make dev       # Vite dev server with hot-reload on :8193
```

Open **http://localhost:8193**. The dev server proxies all `/api/*`
requests to `localhost:8080` automatically, so `VITE_API_BASE` and
`VITE_WS_BASE` can be left empty. Enter an API key from your
`engine_config.yaml` and click **Connect** (see "Logging in" below). Run
`make help` for the full target list.

### Serving a production build without a container

```bash
make build      # typecheck + vite build → apps/web/dist/
make serve      # serve apps/web/dist/ via pm-trading-ui-serve, on :8093
```

## Environment variables

**Development (Vite, from `.env.example` — copy to `.env`):**

| Variable                        | Default                | Description                                       |
| ----------------------------------- | ------------------------- | ------------------------------------------------------ |
| `VITE_API_BASE`                      | _(empty)_                   | Base URL for `pm-api-gwy` REST API; leave empty to use the dev proxy |
| `VITE_WS_BASE`                       | _(empty)_                   | Base URL for WebSocket connections; leave empty to use the dev proxy |
| `VITE_APP_TITLE`                     | `EduMatcher Trading`         | Browser tab title                                       |
| `VITE_MAX_OVERVIEW_SYMBOLS`          | `250`                        | Max symbols in the broad market-data subscription        |
| `VITE_MAX_FOCUS_SYMBOLS`             | `25`                         | Max symbols in the focused depth/auction subscription     |
| `VITE_CHART_HISTORY_TICKS`           | `1000`                       | Historical ticks fetched for intraday charts               |
| `VITE_FLASH_DURATION_MS`             | `500`                        | Price flash animation duration, in ms                      |
| `VITE_MARKET_THROTTLE_MS`            | `250`                        | How often Market Overview re-derives rows from the book store |
| `VITE_WS_RECONNECT_MAX_DELAY`        | `30000`                      | Reconnect backoff cap, in ms                                |
| `VITE_NOTIFICATION_BUFFER`           | `500`                        | Max entries retained in the Notification / Event Center     |

**Production server (`pm-trading-ui-serve` / container):**

| Variable            | Default               | Description                                       |
| --------------------- | ------------------------ | ------------------------------------------------------ |
| `HOST`                 | `0.0.0.0`                  | Bind address                                             |
| `PORT`                  | `8093`                     | Listen port                                                |
| `STATIC_DIR`            | `apps/web/dist/`            | Path to the built SPA (absolute or CWD-relative)           |
| `API_PROXY_TARGET`      | _(unset — `/api/*` returns 503)_ | Forward `/api/*` to this URL, e.g. `http://localhost:8080` |

Run `npm run pm-trading-ui-serve -- --help` for the same reference, rendered
from the code that reads it.

## Startup sequence

1. Start the EduMatcher engine and `pm-api-gwy`.
2. Start this GUI: `make up` (container), `make dev` (development), or
   `make serve` after `make build` (production build without a container).
3. Open the app, enter an API key from `engine_config.yaml`, and click
   **Connect** — see "Logging in" below for where to find keys.

## Other Makefile targets

| Target        | Description                                                          |
| -------------- | ---------------------------------------------------------------------- |
| `build-debug`   | Frontend build with source maps, no typecheck                          |
| `typecheck`     | Type-check across all workspaces                                       |
| `test`          | Run Vitest test suite                                                  |
| `lint`          | Alias for `typecheck`                                                  |
| `format`        | Format source with Prettier                                            |
| `cnt-build`     | Build the container image via compose without starting it              |
| `proxy-up`      | Start the container stack through a local dev proxy                    |
| `restart`       | Restart the container stack                                            |
| `logs`          | Follow container logs                                                  |
| `ps`            | Show container stack status                                            |
| `dist`          | Build a distributable: container image + exported OCI tarball in `dist/` |
| `clean`         | Remove `apps/web/dist/`, `node_modules/`, and `apps/web/node_modules/` |

## Other relevant information

### Logging in

The trading GUI has no user database of its own. It authenticates against
`pm-api-gwy` using API keys defined in `engine_config.yaml` and loaded by
the gateway at startup. When you enter an API key and click **Connect**,
the app calls `GET /api/v1/status`; the gateway validates the key and
returns the `gateway_role` (`TRADER`, `MARKET_MAKER`, or `ADMIN`) the key is
bound to, and the app routes you to that role's landing screen.

API keys live under `api_gateways.<name>.credentials` in
`engine_config.yaml`. Each entry maps an API key to a `gateway_id`, which in
turn resolves to a role under `gateways.alf`:

```yaml
api_gateways:
  desk:
    host: 127.0.0.1
    port: 8080
    credentials:
      - api_key: key-trader-demo       # ← use this in the login form
        gateway_id: TRADER01           # ← maps to gateways.alf id TRADER01
        description: Demo trading client
      - api_key: key-mm-demo
        gateway_id: MM01               # role: MARKET_MAKER
      - api_key: key-admin-demo
        gateway_id: OPS01              # role: ADMIN
      - api_key: key-readonly
        gateway_id: null               # no engine identity → read-only REST access

gateways:
  alf:
    - id: TRADER01
      role: TRADER
    - id: MM01
      role: MARKET_MAKER
    - id: OPS01
      role: ADMIN
```

`engine_config.yaml` lives in the EduMatcher session data directory —
`~/.local/share/edumatcher/ref_data/engine_config.yaml` by default, or
`$EDUMATCHER_DATA_DIR/ref_data/engine_config.yaml` if that variable is set.
If you used `pm-setup` to initialise the session directory, a sample config
with placeholder keys is already there; edit credentials under
`api_gateways.desk.credentials` and restart `pm-api-gwy` for changes to take
effect. Keep one credential per persona in your config to switch roles
quickly by reconnecting with a different key.

### `/api/*` in production

The SPA calls `pm-api-gwy` at the same origin under `/api/v1/`. In
development the Vite proxy handles this transparently. In production,
either put a reverse proxy (nginx/Caddy/Traefik) in front that routes
`/api/*` → `pm-api-gwy` and `/` → `pm-trading-ui-serve` (leave
`API_PROXY_TARGET` unset), or set `API_PROXY_TARGET` and let
`pm-trading-ui-serve` forward `/api/*` directly — simpler for a
single-machine deployment, no extra infrastructure needed.

### Tech stack

| Concern       | Library                           |
| --------------- | ------------------------------------ |
| Framework        | React 19 + TypeScript 5               |
| Build             | Vite 6                                |
| Routing           | React Router v7                       |
| Components        | shadcn/ui (Radix UI primitives)        |
| Styling           | Tailwind CSS v3                        |
| Server state      | TanStack Query v5                      |
| Client state      | Zustand v5                             |
| Forms             | React Hook Form 7 + Zod 3               |
| Charts            | TradingView Lightweight Charts v5       |
| Analytics         | Recharts 2                             |
| Notifications     | Sonner                                  |
| Keyboard          | react-hotkeys-hook 4                    |
| Icons             | Lucide React                            |
| Tests             | Vitest + React Testing Library          |
| Serve             | Node built-in `http` (no extras)        |
