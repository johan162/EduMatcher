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

## Quick start

```bash
# From this directory
make install    # npm install (all workspaces)
make dev        # Vite dev server → http://localhost:5173
```

Open `http://localhost:5173`, enter an API key from your
`api_gateway_config.yaml`, and click **Connect**.

---

## Development commands

| Command          | Description                                      |
| ---------------- | ------------------------------------------------ |
| `make dev`       | Start Vite dev server with hot-reload on `:5173` |
| `make build`     | Typecheck + production build to `apps/web/dist/` |
| `make typecheck` | TypeScript type-checking only                    |
| `make test`      | Run Vitest test suite                            |
| `make format`    | Prettier formatting                              |
| `make clean`     | Remove `dist/` and `node_modules/`               |

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
        hooks/             # useRole, useWsEvent, useFlash, …
        lib/               # formatters, validators (Zod), priceUtils, schedule, bootstrap
        types/             # Core TypeScript types (Appendix A)
        router/            # RoleGuard
        components/        # layout/, market/, shared/
        pages/             # Route-level page stubs
      test/                # Vitest unit tests
  test/
    setup-dom.ts           # Vitest global setup
  Makefile
  .env.example
```

---

## Environment variables

Copy `.env.example` to `.env` and adjust:

| Variable                      | Default              | Description                                       |
| ----------------------------- | -------------------- | ------------------------------------------------- |
| `VITE_API_BASE`               | _(empty)_            | Base URL for pm-api-gwy REST API                  |
| `VITE_WS_BASE`                | _(empty)_            | Base URL for WebSocket connections                |
| `VITE_APP_TITLE`              | `EduMatcher Trading` | Browser tab title                                 |
| `VITE_MAX_OVERVIEW_SYMBOLS`   | `250`                | Max symbols in broad market-data subscription     |
| `VITE_MAX_FOCUS_SYMBOLS`      | `25`                 | Max symbols in focused depth/auction subscription |
| `VITE_FLASH_DURATION_MS`      | `500`                | Price flash animation duration (ms)               |
| `VITE_WS_RECONNECT_MAX_DELAY` | `30000`              | Reconnect backoff cap (ms)                        |

The Vite dev-server proxy (`/api → localhost:8080`) avoids CORS issues during
local development, so `VITE_API_BASE` and `VITE_WS_BASE` can be left empty.

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

---

## Implementation status

Built incrementally against §23 of the design document.

| Phase | Deliverable                                                                                                                                                                      | Status  |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| 1     | Scaffold, routing, `apiFetch`, `useAuthStore`, login + role detection                                                                                                            | ✅ done |
| 2     | `ManagedSocket` / `WebSocketManager`, one market-data socket with broad + focus subscription items, seq-gap resume, book/session/halt stores, top-bar health + clock + countdown | ✅ done |
| 3     | Market Overview table                                                                                                                                                            | ⬜ next |
| 4–17  | Symbol detail, workspace, ticket, blotter, MM, admin, help, polish                                                                                                               | ⬜      |

---

## Design reference

Full specification: `docs-design/EduMatcher-Trading-GUI.md` (v1.11.2)

Backend capability matrix (which ADMIN endpoints are available now vs blocked):
see §6 of that document.
