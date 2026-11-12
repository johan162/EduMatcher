# EduMatcher Clearing GUI (`pm-clearing-ui`)

A read-only browser client over the clearing and end-of-day settlement data
that `pm-clearing` and `pm-eod` record. It talks to one service only,
`pm-api-gwy`, through its `/api/v1/clearing` routes; the gateway opens
`clearing.db` and `eod.db` read-only and enforces who may see what.

| Role | Lands on | Sees |
|---|---|---|
| `ADMIN` | Clearing Overview | The venue: overview, participants and drill-down, symbols, events, gateway sessions, reconciliation, EOD settlement |
| `TRADER` | My Positions | Its own gateway: positions and exposure, retained trades, daily and close history, EOD settlement and balance, gateway sessions |
| `MARKET_MAKER` | My Positions | The trader views plus My Quote Obligations (its configured obligation settings) |

A read-only API key has no clearing data and cannot log in.

There is no margin, equity, collateral, buying power or open interest
anywhere: nothing in the system computes them, and the GUI does not invent
them. See [the design](../../docs-design/EduMatcher-Clearing-GUI.md) and the
REST reference's Clearing chapter for the contract.

## Layout

```
clearing-gui/
  apps/
    web/      React + TypeScript SPA (Vite, React Router, TanStack Query,
              Zustand, Zod, Tailwind, Radix tabs, Recharts)
      src/api/        apiFetch (REST client), schemas (Zod, the contract),
                      queries (TanStack hooks and the polling policy)
      src/lib/        money (ticks vs minor units), time
      src/components/ layout (shell, top bar, sidebar), shared (states,
                      table, filters), views (tables reused by participant
                      and ADMIN screens), help (top-bar help drawer)
      src/pages/      me/ (participant), admin/ (ADMIN), LoginPage
      test/           Vitest + React Testing Library suites
    serve/    pm-clearing-ui-serve: static server with the /api proxy
  Dockerfile, docker-compose.yml, docker-compose.linux.yml, Makefile, .env.example
```

## Getting started

Node.js 22 or newer.

```bash
make install        # npm ci
make dev            # Vite on http://localhost:8196, /api proxied to localhost:8080
make test           # Vitest (unit, component and contract suites)
make typecheck
make build          # apps/web/dist
API_PROXY_TARGET=http://localhost:8080 make serve   # production build on :8096
make up             # container on :8096 (CLEARING_GUI_PORT to change the host port)
```

`pm-api-gwy` must run with `clearing_db` (and, for the settlement screens,
`eod_db`) pointing at the files `pm-clearing` and `pm-eod` write. Log in with
the API key of a trading gateway, or an ADMIN gateway.

## Environment

| Variable | Where | Default | Meaning |
|---|---|---|---|
| `API_PROXY_TARGET` | `serve`, container | unset (compose: `http://host.docker.internal:8080`) | Where `/api/*` is forwarded. Unset: `/api/*` answers 503 with an explanation |
| `HOST` / `PORT` | `serve`, container | `0.0.0.0` / `8096` | Listener |
| `STATIC_DIR` | `serve` | `apps/web/dist` | The built SPA |
| `CLEARING_GUI_PORT` | compose | `8096` | Host port published for the container |

`npm run serve -- --help` prints the server's own list.

## How the data is shown

- **Units.** Clearing money is in ticks of each symbol's `tick_decimals`; every
  row value is formatted from its `*_ticks` field with that row's precision
  (`lib/money.ts` refuses a tick value without it). Cross-symbol totals come
  from the API already converted per row. EOD settlement amounts are a
  separate unit, minor units (`*_minor`, 2 decimals), with their own
  formatter; the schema brands the two so they cannot be mixed.
- **Freshness.** pm-clearing commits fills in batches (5 s at most by default),
  so current-state screens refresh every 5 s and say when the data was last
  committed. History, trades, events and settlement are fetched on demand
  and cached; health every 30 s; reconciliation only when you press Run.
- **Errors are not zeros.** A refused request (403), an unavailable ledger
  (503 `CLEARING_DB` / `EOD_DB`), a reply that does not match the contract,
  or an unreachable gateway each show as an error with its reason. An empty
  table always means there is nothing to show.
- **Retention and observation.** Raw trades are kept for a retention window
  (90 days by default; the trade screen shows from which day). Session and
  gateway-session times are when clearing observed them. A GAP means clearing
  saw trade ids jump; no GAP does not prove the feed was complete.

## Tests

`test/contract.test.ts` parses every clearing example of the released
contract (`spec/rest/openapi.json`) with the GUI's schemas and checks that
the field sets agree, so a contract change fails here first. The other suites
cover units, the API client, login and role routing, every screen's states,
accessibility (axe) and request discipline (what is polled, what is not).
The browser end-to-end journeys run from the Python suite
(`tests/test_clearing_gui_e2e.py`, `make test-e2e` in the repository root).
