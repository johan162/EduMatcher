# EduMatcher Trading GUI (`pm-trading-ui`)

A graphical trading terminal for the [EduMatcher](../README.md) exchange simulator.

Provides three role-aware personas:

| Role             | Landing screen    | Access                                           |
| ---------------- | ----------------- | ------------------------------------------------ |
| **TRADER**       | Trading Workspace | Order entry, blotter, fills, positions           |
| **MARKET_MAKER** | Quote Management  | Two-sided quote management, positions            |
| **ADMIN**        | System Dashboard  | Session control, gateway mgmt, risk, monitor log |

Connects exclusively to `pm-api-gwy` (REST + WebSocket). No backend changes
required for TRADER or MARKET\_MAKER; the ADMIN surface uses additional endpoints
documented in `docs-design/EduMatcher-Trading-GUI.md §6`.

---

## Prerequisites

- **Node.js** ≥ 22 (LTS)
- **pm-api-gwy** running on `localhost:8080` (or adjust `VITE_API_BASE`)

---

## Quick start (development)

```bash
# From this directory (trader-gui/)
make install    # npm install (all workspaces)
make dev        # Vite dev server → http://localhost:5173
```

Open `http://localhost:5173`, enter an API key from your
`api_gateway_config.yaml`, and click **Connect**.

The dev server proxies all `/api/*` requests to `localhost:8080` automatically,
so `VITE_API_BASE` and `VITE_WS_BASE` can be left empty.

---

## Serving the production build

### 1. Build

```bash
make build      # typecheck + vite build → apps/web/dist/
```

### 2. Serve with `pm-trading-ui-serve`

```bash
make serve
# or
npm run pm-trading-ui-serve
```

This starts the built-in static file server on `http://localhost:4173`.

The server:
- Serves `apps/web/dist/` with correct MIME types.
- Applies `Cache-Control: immutable` to hashed Vite asset bundles and
  `no-cache` to `index.html` so browsers pick up new deploys immediately.
- Falls back every unknown `GET` path to `index.html` so React Router
  handles client-side navigation.
- Optionally proxies `/api/*` to `pm-api-gwy` when `API_PROXY_TARGET` is set.

**Environment variables for `pm-trading-ui-serve`:**

| Variable           | Default                   | Description                               |
| ------------------ | ------------------------- | ----------------------------------------- |
| `HOST`             | `0.0.0.0`                 | Bind address                              |
| `PORT`             | `4173`                    | Listen port                               |
| `STATIC_DIR`       | `apps/web/dist/`          | Path to the built SPA (absolute or CWD-relative) |
| `API_PROXY_TARGET` | _(unset — returns 503)_   | Forward `/api/*` to this URL, e.g. `http://localhost:8080` |

**Examples:**

```bash
# Custom port, proxy API to a remote gateway
PORT=8088 API_PROXY_TARGET=http://my-exchange:8080 npm run pm-trading-ui-serve

# Serve a dist/ built elsewhere
STATIC_DIR=/opt/pm-trading-ui/dist npm run pm-trading-ui-serve

# Print full help
npm run pm-trading-ui-serve -- --help
```

> **Note on `/api/*` in production:** the SPA calls `pm-api-gwy` at the same
> origin under `/api/v1/`. In development the Vite proxy handles this
> transparently. In production you have two options:
>
> 1. **Same-origin reverse proxy** (recommended): put nginx/Caddy/Traefik in
>    front, route `/api/*` → `pm-api-gwy` and `/` → `pm-trading-ui-serve`.
>    Leave `API_PROXY_TARGET` unset.
> 2. **Built-in proxy** (simple deployments): set `API_PROXY_TARGET` and let
>    `pm-trading-ui-serve` forward `/api/*` directly. No extra infrastructure
>    needed for a single-machine setup.

### Pass `--help` to see all options

```bash
npm run pm-trading-ui-serve -- --help
```

---

## Logging in

### How authentication works

The trading GUI does not have its own user database. It authenticates against
`pm-api-gwy` using **API keys** that are defined in `engine_config.yaml` and
loaded by the gateway at startup.

When you enter an API key and click **Connect**, the app calls `GET /api/v1/status`.
The gateway validates the key and returns the `gateway_role` (`TRADER`,
`MARKET_MAKER`, or `ADMIN`) that the key is bound to. The app then routes you
to the correct landing screen for that role.

### Where to find API keys

API keys are defined under `api_gateways.<name>.credentials` in
`engine_config.yaml`. Each entry maps an API key to a gateway session identity
(`gateway_id`) which in turn determines the role:

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
```

The `gateway_id` references an entry under `gateways.alf` where the `role` is
defined:

```yaml
gateways:
  alf:
    - id: TRADER01
      role: TRADER
    - id: MM01
      role: MARKET_MAKER
    - id: OPS01
      role: ADMIN
```

### Finding the config file

`engine_config.yaml` lives in your EduMatcher session data directory.
The default location is `~/.local/share/edumatcher/ref_data/engine_config.yaml`.
You can override it with the `EDUMATCHER_DATA_DIR` environment variable:

```bash
# Default location
cat ~/.local/share/edumatcher/ref_data/engine_config.yaml

# Custom location
cat $EDUMATCHER_DATA_DIR/ref_data/engine_config.yaml
```

If you used `pm-setup` to initialise the session directory, a sample config
with placeholder API keys is already there. Open it in any text editor, add or
change credentials under `api_gateways.desk.credentials`, and restart
`pm-api-gwy` for the changes to take effect.

### Step-by-step

1. Start the engine and `pm-api-gwy` (see the main EduMatcher README).
2. Open the trading GUI (`make dev` for dev, or `make serve` for the
   production build).
3. Open `engine_config.yaml` and find an `api_key` value under
   `api_gateways.<name>.credentials`.
4. Paste the key into the **API Key** field on the login page and click
   **Connect**.
5. The app reads the role from `GET /api/v1/status` and navigates you to the
   role landing screen (TRADER → Trading Workspace, MARKET\_MAKER → Quote
   Management, ADMIN → System Dashboard).

> **Tip:** keep one credential per persona in your config so you can quickly
> switch roles by reconnecting with a different key.

---

## Development commands

| Command          | Description                                         |
| ---------------- | --------------------------------------------------- |
| `make dev`       | Start Vite dev server with hot-reload on `:5173`    |
| `make build`     | Typecheck + production build to `apps/web/dist/`    |
| `make serve`     | Serve `apps/web/dist/` via `pm-trading-ui-serve`    |
| `make typecheck` | TypeScript type-checking only                       |
| `make test`      | Run Vitest test suite                               |
| `make format`    | Prettier formatting                                 |
| `make clean`     | Remove `dist/` and `node_modules/`                  |

---

## Project structure

```
trader-gui/
  apps/
    web/                   # React/TypeScript SPA (pm-trading-ui)
      src/
        api/               # apiFetch + typed endpoint helpers
        ws/                # ManagedSocket, WebSocketManager, subscriptions, seq tracking
        store/             # Zustand stores (auth, session, book, halt, …)
        queries/           # TanStack Query hooks
        hooks/             # useRole, useWsEvent, useFlash, useConnectionHealth, …
        lib/               # formatters, validators (Zod), priceUtils, schedule, bootstrap
        types/             # Core TypeScript types (Appendix A)
        router/            # RoleGuard
        components/        # layout/, market/, shared/, notifications/, help/, command/
        pages/             # Route-level page components
      test/                # Vitest component + unit tests
    serve/                 # pm-trading-ui-serve static file server
      serve.ts             # Zero-extra-dep Node http server (SPA fallback + optional /api proxy)
  test/
    setup-dom.ts           # Vitest global setup
  Makefile
  .env.example             # Copy to .env and adjust for local development
```

---

## Environment variables

Copy `.env.example` to `.env` in the `trader-gui/` directory and adjust.
The full list is documented in `.env.example`; the most commonly changed values:

| Variable                      | Default              | Description                                       |
| ----------------------------- | -------------------- | ------------------------------------------------- |
| `VITE_API_BASE`               | _(empty)_            | Base URL for pm-api-gwy REST API                  |
| `VITE_WS_BASE`                | _(empty)_            | Base URL for WebSocket connections                |
| `VITE_APP_TITLE`              | `EduMatcher Trading` | Browser tab title                                 |
| `VITE_MAX_OVERVIEW_SYMBOLS`   | `250`                | Max symbols in broad market-data subscription     |
| `VITE_MAX_FOCUS_SYMBOLS`      | `25`                 | Max symbols in focused depth/auction subscription |
| `VITE_FLASH_DURATION_MS`      | `500`                | Price flash animation duration (ms)               |
| `VITE_WS_RECONNECT_MAX_DELAY` | `30000`              | Reconnect backoff cap (ms)                        |

---

## Tech stack

| Concern       | Library                           |
| ------------- | --------------------------------- |
| Framework     | React 19 + TypeScript 5           |
| Build         | Vite 6                            |
| Routing       | React Router v7                   |
| Components    | shadcn/ui (Radix UI primitives)   |
| Styling       | Tailwind CSS v3                   |
| Server state  | TanStack Query v5                 |
| Client state  | Zustand v5                        |
| Forms         | React Hook Form 7 + Zod 3         |
| Charts        | TradingView Lightweight Charts v5 |
| Analytics     | Recharts 2                        |
| Notifications | Sonner                            |
| Keyboard      | react-hotkeys-hook 4              |
| Icons         | Lucide React                      |
| Tests         | Vitest + React Testing Library    |
| Serve         | Node built-in `http` (no extras)  |

---

## Implementation status

All 17 phases complete. Built incrementally against §23 of the design document
(`docs-design/EduMatcher-Trading-GUI.md`, currently v1.11.13).

| Phase | Deliverable                                                                                                                                                                        | Status  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| 1     | Scaffold, routing, `apiFetch`, `useAuthStore`, login + role detection                                                                                                              | ✅ done |
| 2     | `ManagedSocket` / `WebSocketManager`, one market-data socket with broad + focus subscription items, seq-gap resume, book/session/halt stores, top-bar health + clock + countdown   | ✅ done |
| 3     | Market Overview table with FlashCell, `GET /symbols`, `GET /history/daily` for change %, auction + halt badges                                                                     | ✅ done |
| 4     | Symbol Detail right panel: Chart, Depth (click-to-trade), Trades tape, Stats, Auction tab                                                                                          | ✅ done |
| 5     | Trading Workspace: 4-quadrant layout bound to the active symbol                                                                                                                    | ✅ done |
| 6     | TRADER Order Ticket: all 8 single-leg types, Zod validation, TIF phase restrictions, dual BUY/SELL + `B`/`S`, auction banner                                                       | ✅ done |
| 7     | TRADER Active Orders Blotter: TanStack Table, WS updates, Amend, Cancel-Replace, cancel, Order Detail drawer                                                                       | ✅ done |
| 8     | OCO/Combo entry + group rows/badges + group cancel; Trade History; Position Panel + Flatten / Flatten All                                                                          | ✅ done |
| 9     | MARKET_MAKER: Quote card grid, New Quote form, fill alerts, bootstrap + quotes/legs fill indicators                                                                                 | ✅ done |
| 10    | Notification / Event Center + bell; power-user mode (undo-toast + always-confirm); Watchlist                                                                                       | ✅ done |
| 11    | Admin API client, System Dashboard, `/admin/monitor` WS + store, Monitor Log Viewer + cross-gateway order drill-down                                                               | ✅ done |
| 12    | ADMIN Session Control, Gateway Management (Kick), Kill Switch — symbol / by-gateway / global                                                                                       | ✅ done |
| 13    | ADMIN Risk Control (read-only), Circuit Breaker Management (functional level selector), Symbol Management (read-only), Index Admin                                                  | ✅ done |
| 14    | Help drawer (`Ctrl+/`), field tooltips on the Order Ticket, shortcut reference dialog (`?`)                                                                                        | ✅ done |
| 15    | Command palette (`Ctrl+K`), global shortcuts (`Ctrl+.`, `Ctrl+L`, `F3`, `F4`, `Ctrl+Shift+F`, `Ctrl+Enter`)                                                                       | ✅ done |
| 16    | Error boundary (per-route, SPA chrome stays live), connection banner (reconnecting/disconnected), loading skeletons + reusable empty state                                         | ✅ done |
| 17    | `pm-trading-ui-serve`: production static file server with SPA fallback, immutable asset caching, optional `/api/*` proxy, `HOST`/`PORT`/`STATIC_DIR` env vars, graceful shutdown  | ✅ done |

---

## Design reference

Full specification: `docs-design/EduMatcher-Trading-GUI.md` (v1.11.13)

Backend capability matrix (which ADMIN endpoints exist vs blocked):
see §6 of that document.
