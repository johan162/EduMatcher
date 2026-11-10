# EduMatcher — Clearing GUI: Participant Obligations and Release 1.0 Design

Version: 1.0.0-design

Date: 2026-11-09

Status: **Design and repository audit.** `clearing-gui` and the clearing REST
surface described here are not implemented. This document separates shipped
behaviour from required release-1.0 work. Code is the authority where this
document, older designs, and comments disagree.

## 1. Purpose and release boundary

`pm-clearing` already maintains a durable, gateway-scoped post-trade ledger.
The release-1.0 clearing client is a **read-only operations and participant
reporting application** over that ledger and the existing end-of-day (EOD)
settlement ledger. It answers the questions the shipped system can answer:

- What position, realized P&L, unrealized P&L, and marked exposure does each
  participant gateway currently have?
- Which retained executions created that position?
- Has clearing observed a feed gap, session close, or gateway lifecycle event
  that affects confidence in the displayed record?
- What was each participant's close snapshot and daily realized P&L?
- What EOD settlement amount and running balance has `pm-eod` recorded?
- For a market maker, what quote obligation settings are currently resolved
  for its symbols?

This is deliberately narrower than a collateral or margin system. The current
repository has no margin configuration, margin calculation, margin snapshot,
credit limit, account registry, client-account order field, or account-aware
clearing key. A GUI or REST adapter cannot derive those facts safely. Margin,
client accounts, and pre-trade enforcement are therefore outside the 1.0
release and have explicit prerequisites in §13.

## 2. Audited current state

| Component | Shipped behaviour | 1.0 consequence |
|---|---|---|
| `pm-clearing` | Ingests `trade.executed`; persists raw events, latest `(gateway_id, symbol)` positions, daily summaries, session events, gateway sessions, and close snapshots in `clearing.db`. | The source data for position, P&L, exposure, trade, close, session, and lifecycle views exists. |
| Clearing writer | Flushes at 100 trades or after five seconds. It deduplicates on durable trade ID and records an observed `GAP` event when a trade-ID sequence jumps. | The GUI must show data freshness and GAP alarms. It must not label its state as real time or complete without qualification. |
| `pm-eod` | Calculates change in close-to-close cumulative P&L, records a zero-sum daily settlement in `eod.db`, and derives balances from roster opening balances plus settlements. | Settlement and balance are available source facts, but only at gateway level. The GUI needs an API read model for them. |
| `pm-api-gwy` | Exposes the caller's engine positions and enriches each row with clearing realized P&L for session, month-to-date, and year-to-date. | This is useful participant data but is not a clearing API and cannot power an operator view. |
| `pm-clearing-cli` | Already queries clearing gateways, positions, P&L, daily rows, trades, exposure, symbols, dates, close snapshots, sessions, EOD markers, health, and reconciliation. | Its read-only SQLite queries are the implementation source for the new typed REST routes. |
| Market-maker obligations | The engine enforces configured maximum spread and minimum quote quantity when the resolved policy enables it. `/api/v1/symbols` returns these resolved fields to the requesting trading gateway. | Release 1.0 can display configuration and the existing enforcement inputs. It cannot claim quote-presence or re-quote compliance analytics. |
| `trader-gui` | Uses a role-aware React/TypeScript SPA directly against `pm-api-gwy`, with React Router, TanStack Query, Zustand, Zod, shadcn/Radix, Tailwind, and a same-origin `/api` proxy for production. | `clearing-gui` follows this architecture and visual/application conventions. |
| `terminal-gui` | Uses a Fastify bridge only because browsers cannot speak its raw TCP CALF uplink. Credentials for its optional history proxy stay server-side. | A clearing bridge is not justified: clearing data will be REST from `pm-api-gwy`, as it is for `trader-gui`. |

### 2.1 Identity and scope

A **participant** is a configured gateway identity. The configured roles are
`TRADER`, `MARKET_MAKER`, and `ADMIN`. Current positions, snapshots, daily
summaries, and settlement keys have the gateway as their account dimension.
There is no participant-to-many-gateway hierarchy and no client subaccount.
The clearing client must therefore use **participant gateway** consistently in
UI labels and API fields; it must not call gateway IDs brokers, funds, or
client accounts.

`eod_settlement.account` currently contains either a gateway ID or the reserved
`EXCHANGE` rounding account. It does not represent a client account.

### 2.2 Money, marks, and history

`trade.executed.price` arrives as display money, but clearing converts it to
integer ticks. `trade_events`, positions, daily summaries, and close snapshots
persist `tick_decimals` with the tick-unit amounts. The REST API must return
that precision for every money-bearing row and normalize each row to display
currency before presenting or aggregating it. Raw P&L or notional ticks from
different symbols must never be summed.

Current positions are the latest marked state. `pm-clearing` marks all open
holders of a symbol on new trades and applies EOD last-price or bid/ask-midpoint
marks when present. The durable history is:

- raw execution events, retained for 90 days by default;
- per-symbol, per-gateway daily summaries, retained after raw-event pruning;
- one close snapshot per participant/symbol for each closing session;
- session events and gateway connection records.

There is no sampled intraday position/P&L history. Release 1.0 charts must use
daily close snapshots only. An intraday equity or P&L chart would require a new
durable sample series and is not a valid 1.0 display.

## 3. What “participant obligations” mean in 1.0

The term has three distinct code-supported meanings. The UI must keep them
separate rather than folding them into a single risk score.

| Obligation view | Source and evidence | 1.0 presentation |
|---|---|---|
| Post-trade position and P&L | `gateway_symbol_positions`, `gateway_daily_summary`, `position_close_snapshot`, and `trade_events` in `clearing/store.py` | Positions, exposure, daily P&L, retained trade audit, and close history. |
| Daily settlement | `eod/settle.py` computes a gateway's close-to-close P&L; `eod/ledger.py` records a daily minor-unit amount and derives balance from opening balance plus amounts. | Settlement amount, per-symbol settlement detail, settlement-run status, and running balance. |
| Market-maker quote obligation | `engine/config_loader.py` resolves `enforce_mm_obligation`, `mm_max_spread_ticks`, and `mm_min_qty`; `engine/main.py` applies the enabled spread/quantity checks. | Read-only settings table for the authenticated MM's symbols. |

The richer `MarketMakerObligation` model also names presence percentage and
re-quote delay fields, but the configuration policy used by quote enforcement
contains only enablement, maximum spread, and minimum quantity. No persisted
quote-presence series or compliance calculation was found. Those metrics are
not release-1.0 obligations.

A settlement amount is a mark-to-market transfer, not evidence of collateral,
initial margin, maintenance margin, buying power, a margin call, or payment
completion. The UI must label it **EOD settlement amount** and **derived
running balance**, not cash, equity, or margin.

## 4. Data-source and capability matrix

| View/data | Authoritative source | Existing gateway REST exposure | 1.0 API work | Freshness / retention |
|---|---|---|---|---|
| Caller's realized P&L periods | `clearing.db` daily summary | Partial: `GET /api/v1/positions` only | Keep current enrichment; clearing routes add full detail | May lag fills by the five-second clearing flush. |
| Current positions and P&L | `gateway_symbol_positions` | None | New `GET /clearing/positions` and participant detail | Latest committed flush; no point-in-time intraday history. |
| Marked exposure | Current position rows, scaled per row | None | New `GET /clearing/exposure` | Latest committed flush. |
| Retained executions | `trade_events` | None | New `GET /clearing/trades` | Default raw-event retention: 90 days. |
| Daily activity and realized P&L | `gateway_daily_summary` | None | New `GET /clearing/daily` | Durable beyond raw-event retention. |
| Close-time positions/P&L | `position_close_snapshot` | None | New `GET /clearing/close-snapshots` | One row per closing participant/symbol/date. |
| Feed, close, and lifecycle evidence | `session_events`, `gateway_sessions` | None | New event and session routes | Durable; event timestamps are clearing-observed ingest times. |
| Reconciliation | Clearing raw-event versus summary query | None | New `GET /clearing/reconciliation` | Reconciliation can only inspect retained raw events. |
| Clearing freshness | Clearing DB health query | None | New `GET /clearing/health` | Includes latest trade/flush timestamps and row counts, not process liveness. |
| EOD settlement and balance | `eod.db`, opening roster data | None | New settlement and balance routes | Exists after `pm-eod` has run; balance is derived, not stored. |
| MM configuration | Engine resolved symbols response | `GET /api/v1/symbols`, requester scoped | Reuse that endpoint in MM self-view; no new clearing aggregate | Current engine configuration. |

## 5. Release-1.0 REST API

### 5.1 Placement and access

Add a read-only `routers/clearing.py` to `pm-api-gwy` and register it in the
same application that registers orders, reference, market, history, admin,
bootstrap, and WebSocket routers today. Use the existing `/api/v1` versioning,
authentication, error envelope, pagination limits, and typed response-model
patterns.

Do not add a separately exposed clearing process, and do not allow the browser
to open `clearing.db` or `eod.db` directly. The API owns SQLite read-only
connections and validates all filters before query execution.

Visibility must be enforced at the API boundary:

| Authenticated role | Read scope |
|---|---|
| `ADMIN` | Venue-wide clearing and EOD data, including `EXCHANGE` settlement row. |
| `TRADER` | Its own `gateway_id` only. A caller-supplied `gateway` filter must be rejected or ignored in favour of its authenticated ID. |
| `MARKET_MAKER` | Its own `gateway_id` only, plus its existing requester-scoped symbol obligation metadata. |
| Read-only key without a gateway identity | No clearing route in 1.0. |

There is no code-supported broker/client scope to authorize. That scope must
not be introduced as a UI-only convention.

### 5.2 Route inventory

All routes below are proposed release-1.0 additions. None exists at the time
of this audit. List rows return `count`, apply a bounded `limit`, and use
cursor pagination where raw trades or events can exceed the response limit.
Dates are `YYYY-MM-DD` in the clearing session timezone.

| Route | Scope | Backing query/data | Required response information |
|---|---|---|---|
| `GET /clearing/summary` | ADMIN | position totals, health, current GAP events, EOD run state | Participant count, open-position count, normalized aggregate P&L where meaningful, latest flush/trade timestamps, active GAP count, last EOD run status. Do not expose a fake venue-wide net notional across symbols. |
| `GET /clearing/participants` | ADMIN | `query_gateways` plus positions/exposure | Gateway ID, realized/unrealized/total P&L, open-position count, timestamp of latest position update. |
| `GET /clearing/participants/{gateway_id}` | ADMIN or self | positions, exposure, daily/close summary | Gateway ID, current P&L totals, latest position update, and links/data for its positions, settlement, and lifecycle tabs. |
| `GET /clearing/positions?gateway=&symbol=` | ADMIN or self | `query_positions` | Gateway ID, symbol, signed quantity, average cost, mark, `tick_decimals`, realized/unrealized P&L, buy/sell quantities and notionals, last trade and update timestamps. |
| `GET /clearing/exposure?gateway=&symbol=&sort=` | ADMIN or self | `query_exposure` | Per-row normalized gross/net notional and P&L, plus source tick fields/precision where audit display requires them. |
| `GET /clearing/trades?gateway=&symbol=&date=&from=&to=` | ADMIN or self | `query_trades` | Execution ID, exchange and ingest timestamps, date, symbol, quantity, display price plus precision, buy/sell gateway IDs subject to scope, order IDs, aggressor side, match type, and audit message ID when stored. |
| `GET /clearing/daily?gateway=&symbol=&from=&to=` | ADMIN or self | `query_daily` | Date, gateway, symbol, traded quantities/notionals, net amount, realized P&L, end position/average cost/unrealized P&L, precision and update timestamp. |
| `GET /clearing/symbols?date=&from=&to=` | ADMIN | `query_symbols` | Symbol activity totals, realized P&L, current aggregate open quantity, and precision. No claim of gross open interest until the API explicitly computes long and short quantities. |
| `GET /clearing/close-snapshots?gateway=&symbol=&from=&to=` | ADMIN or self | `query_close_snapshots` | Close date, gateway, symbol, position, cumulative realized/unrealized P&L, mark and precision. |
| `GET /clearing/session-events?type=&from=&to=` | ADMIN | `query_session_events` | Event type (`EOD`, `PHASE`, `GAP`), clearing-observed timestamp/date, and typed payload. GAP payload includes the observed missing-trade count. |
| `GET /clearing/gateway-sessions?gateway=&from=&to=&connected_only=` | ADMIN or self | `query_sessions` | Gateway ID, connect/disconnect timestamps, and disconnect reason. |
| `GET /clearing/reconciliation?gateway=&symbol=&from=&to=` | ADMIN | `query_reconcile` | Discrepancy rows and explicit retained-raw-data limitation. An empty list means no discrepancy in the queried retained data, not proof of a complete venue history. |
| `GET /clearing/health` | ADMIN | `query_health` plus process health check if available | DB row counts, WAL mode, latest trade timestamp, latest flush timestamp, and a separately named process-liveness result. |
| `GET /clearing/settlements?date=&from=&to=&gateway=` | ADMIN or self | new read-only `eod.db` query | Date, gateway account, daily `amount_minor`, display amount, per-symbol detail, and EOD run status. |
| `GET /clearing/balances?as_of=&gateway=` | ADMIN or self | `eod.ledger.balances` plus roster openings | Gateway account, opening balance, summed settlement amount, derived balance, and as-of date. |

`query_trades` currently does not select `match_type` and `msg_id`, despite
those columns being persisted. The 1.0 API work must extend its typed query
and response rather than silently omitting available audit information.

The present `query_health` inspects database state only. The existing
`pm-clearing-cli health` socket proves receive-loop liveness. If an API health
response presents process liveness, it must query that health interface with a
bounded timeout and report database availability separately. A successful
SQLite read alone is not proof that the clearing subscriber is alive.

### 5.3 EOD read model

No REST route currently reads `eod.db`. The new routes need small, typed,
read-only EOD query helpers, not reuse of CLI text output. `GET
/clearing/settlements` is the machine-readable statement view for 1.0. A PDF,
CSV export, or new `/statements/{date}/{gateway}` endpoint is not required to
ship the GUI and must not be specified as if a statement serialization exists.

The response must preserve these EOD semantics:

- `amount_minor` is an integer in 2-decimal display-currency minor units;
- positive means the exchange owes the gateway, and negative means the gateway
  owes the exchange;
- per-symbol detail is the unrounded display-currency calculation;
- `EXCHANGE` is the rounding residual account and is visible only to ADMIN;
- a balance is calculated from the configured opening balance and settlement
  rows. It is not a ledger column; and
- a settlement run can be `ok`, `failed`, or `report-failed`.

## 6. Clearing GUI architecture

Create `web-apps/clearing-gui` with the `trader-gui` monorepo layout:

```
clearing-gui/
  apps/
    web/       React/TypeScript SPA
    serve/     static server with optional same-origin /api proxy
  Dockerfile
  docker-compose.yml
  Makefile
  .env.example
```

Use the existing Trading GUI technology choices: React, TypeScript, Vite,
React Router, shadcn/Radix, Tailwind, TanStack Query, Zustand, React Hook Form
with Zod, the established chart libraries, and Vitest/React Testing Library.
Reuse the existing application-shell conventions: login via `GET /api/v1/status`,
role-derived landing page, `RoleGuard`, command/help patterns, loading/empty/
error states, and a same-origin `/api` production proxy.

The app has no bus connection, direct SQLite connection, or clearing-specific
WebSocket in 1.0. Poll current-state queries every five seconds only after the
REST API is implemented. Daily, close, and EOD data should use normal query
cache invalidation after the poll detects a later flush/EOD run; it should not
be fetched at the current-state cadence.

The terminal GUI's bridge architecture is intentionally not reused. Its bridge
exists for a raw TCP live-data protocol. A clearing SPA can use the established
HTTP/API-key flow of `trader-gui`; adding a bridge would create another
credential, deployment, and health surface without an identified protocol
need.

## 7. Screens and information design

### 7.1 Role landing pages and navigation

| Role | Landing page | Permitted navigation |
|---|---|---|
| `ADMIN` | Clearing Overview | Overview, Participants, Symbols, Events, Reconciliation, EOD Settlement, Gateway Sessions. |
| `TRADER` | My Clearing | My positions, exposure, retained trades, daily/close history, my EOD settlement and balance. |
| `MARKET_MAKER` | My Clearing | The trader self-view plus My Quote Obligations. |

A route that receives a gateway ID must run through the API scope check even
when the navigation hides that route. Hiding an admin link is not authorization.

### 7.2 Clearing Overview (ADMIN)

The overview is an operational dashboard, not a margin dashboard. It contains:

- latest clearing flush and trade timestamps, database/process health, and the
  five-second committed-data qualifier;
- an unmistakable GAP alarm with observed sequence interval and missing count;
- participant table with current P&L, open position count, and latest update;
- recent `PHASE` and `EOD` events;
- latest EOD run status and the daily zero-sum settlement result; and
- a link to reconciliation discrepancies.

Avoid tiles for total equity, margin requirement, buying power, warning counts,
or open interest. None is currently calculated or stored. Do not sum position
notionals across symbols with different `tick_decimals` into a venue amount.

### 7.3 Participant and My Clearing

A participant page is scoped to one gateway and uses tabs or panels for:

1. **Current positions** — signed quantity, average cost, mark, realized and
   unrealized P&L, gross/net exposure, and update time.
2. **Trades** — retained execution audit, with date/symbol filters and clearly
   labelled exchange time versus clearing ingest time.
3. **Daily and close history** — daily summary table and a daily close chart
   assembled from close snapshots. The chart is labelled close-to-close, not
   intraday.
4. **EOD settlement** — daily settlement amount, balance calculation inputs,
   per-symbol detail, and run state.
5. **Gateway sessions** — connect/disconnect history, where the role allows it.

The participant page must show the raw-data retention window when users filter
trades. It must distinguish unavailable clearing data from a genuine zero: for
example, an API/database failure is an error state, while an empty position
array is a zero-position state.

### 7.4 Symbols, events, reconciliation, and MM obligations

- **Symbols (ADMIN):** activity and current aggregate net quantity by symbol.
  It is a venue activity/exposure index, not an open-interest or concentration
  page until long/short aggregation is implemented and exposed.
- **Events (ADMIN):** filterable `GAP`, `PHASE`, and `EOD` event feed. Event
  timestamps reflect when clearing observed an event, as documented by the
  clearing process.
- **Reconciliation (ADMIN):** filters for gateway/symbol/date and a plain
  description of what raw-vs-summary reconciliation can prove within retained
  trade history.
- **My Quote Obligations (MARKET_MAKER):** one row per symbol showing the
  already resolved `enforce_mm_obligation`, maximum spread ticks, and minimum
  quantity. The copy must say these are configured enforcement parameters; it
  must not imply an observed compliance rate.

## 8. UI data contracts and formatting rules

The frontend API client should define Zod-validated TypeScript contracts for
every new route. Each money rendering helper accepts a tick value and
`tick_decimals`; it normalizes an individual row before format or aggregation.
Settlement values use `amount_minor` rather than clearing tick units and need a
separate minor-unit formatter.

Every table supports explicit filtering, sort direction, a visible applied
scope, bounded pagination, skeleton loading, empty state, retryable error
state, and accessible keyboard focus. The trade audit table must make its
retention date and result count visible. Any CSV export added later must export
the API response's explicit units and precision; it must not scrape formatted
screen values.

## 9. Release-1.0 implementation order and acceptance gates

| Package | Scope | Required evidence before completion |
|---|---|---|
| CL-API-1 | Typed clearing read routes over `clearing.db`; query additions for persisted audit fields; role/scope enforcement. | Route tests prove ADMIN venue access, TRADER/MM self-only access, validation of filters/limits, display normalization, and unavailable/locked DB error handling. |
| CL-API-2 | Typed EOD settlement/balance routes over `eod.db`; health/liveness composition. | Tests prove minor-unit signs, `EXCHANGE` visibility, opening-plus-settlement balance derivation, EOD run states, and separately reported DB versus process health. |
| CL-GUI-1 | `clearing-gui` shell, authentication, role guard, API client, query state, and production `/api` proxy. | Typecheck, component tests for login/role redirects/scope error states, and production proxy smoke test. |
| CL-GUI-2 | ADMIN overview, participant detail, positions, exposure, trades, daily/close history, events, sessions, reconciliation, and EOD screens. | Component tests cover money precision, dates, retention messaging, GAP visibility, no-data/error distinction, and API-backed filters. |
| CL-GUI-3 | Participant self-view and MM settings view. | Tests prove role navigation and absence of unsupported margin/compliance claims. |
| CL-DOC-1 | API reference, deployment/configuration, and user guide updated from the implemented route schemas. | Docs list each shipped route, scopes, units, freshness, retention, and known limitations. |

Release 1.0 is blocked until every 1.0 screen gets all of its data from a
shipped, authenticated route. The CLI is not a browser backend. A screen that
needs a missing route must remain out of the release rather than query SQLite
from the frontend or fabricate a value from unrelated engine data.

## 10. Explicit non-goals for release 1.0

- Margin, collateral, equity, margin-call, requirement, buying-power, and
  credit-limit calculations or labels.
- Client accounts, broker omnibus views, account-level authorization, or
  account-specific EOD settlement.
- Pre-trade clearing/risk enforcement, kill-switch automation, or a clearing
  write path.
- Intraday equity/P&L history and sparklines that imply an unpersisted history.
- Open-interest/concentration claims that need long/short aggregate data.
- Market-maker quote presence, re-quote delay, or compliance-rate analytics.
- Clearing REST WebSocket push. Five-second REST polling matches the writer's
  normal maximum flush interval; push needs a new authoritative event contract.

## 11. Operational limitations shown to users

The GUI must expose, not conceal, these limitations:

1. **Commit lag:** a fill can take up to the clearing flush interval to appear.
2. **Feed completeness:** a GAP event means clearing observed an ID jump on its
   PUB/SUB feed. Absence of a GAP does not prove transport completeness.
3. **Retention:** raw execution audit is pruned after the configured window;
   aggregate/daily/close data remains.
4. **Session timing:** clearing's session and gateway lifecycle timestamps are
   observation timestamps, not engine event timestamps.
5. **Settlement timing:** EOD settlement/balance exists only after `pm-eod`
   succeeds. A current clearing P&L is not a settlement result.
6. **Unit safety:** positions and P&L are symbol-specific tick values until
   normalized with their supplied precision; cross-symbol raw sums are invalid.

## 12. Code references used for this design

- `src/edumatcher/clearing/main.py` — ingestion, five-second/100-trade flush,
  trade conversion, GAP recording, EOD marks, close snapshots, and lifecycle
  observation.
- `src/edumatcher/clearing/store.py` — clearing schema, retention, aggregate
  views, close/session tables, and the CLI's read-only query surface.
- `src/edumatcher/clearing/ledger.py` — current gateway/symbol position and
  mark-to-market behaviour.
- `src/edumatcher/clearing/cli.py` — currently implemented operational read
  commands and filter vocabulary.
- `src/edumatcher/eod/settle.py` and `src/edumatcher/eod/ledger.py` —
  close-to-close settlement arithmetic, minor-unit ledger, balance derivation,
  zero-sum protection, and run statuses.
- `src/edumatcher/api_gateway/main.py` and
  `src/edumatcher/api_gateway/routers/reference.py` — current router registry,
  authentication path, and the only existing clearing-db REST enrichment.
- `src/edumatcher/engine/config_loader.py`, `src/edumatcher/engine/main.py`,
  and `src/edumatcher/models/mm_obligation.py` — participant roles and actual
  versus modelled market-maker obligation fields.
- `web-apps/trader-gui/README.md` and `web-apps/trader-gui/apps/web/src/App.tsx`
  — GUI stack, same-origin proxy, authentication, role routing, and app-shell
  conventions.
- `web-apps/terminal-gui/apps/bridge/src/server.ts` — the specific raw-TCP
  reason the terminal uses a bridge, which clearing does not share.

## 13. Post-1.0 prerequisites: margin and client accounts

These items are intentionally not a feature commitment. They record the
minimum source-of-truth work required before a later design can describe a
margin or client-account UI as factual.

### 13.1 Margin requirements

A margin view needs, at minimum:

- an authoritative configuration and validation path for initial and
  maintenance requirements, warning thresholds, and any instrument multiplier;
- a documented mark and currency model;
- a durable calculation/snapshot schema and status-transition event model;
- a calculation service with formula and rounding tests; and
- a clear decision whether the state is monitor-only or participates in
  pre-trade enforcement.

`SymbolConfig` currently has price precision but no multiplier field, so a
formula that uses multipliers cannot be implemented from current symbol data.
Opening balances in the current EOD roster are gateway metadata, not collateral
data. Neither should be reinterpreted by a GUI.

### 13.2 Client accounts

Account-level clearing requires a coherent end-to-end change, not database
columns alone:

- an account registry and validation authority;
- an immutable account field through every order ingress and lifecycle path;
- account ownership on the authoritative `trade.executed` event;
- account-aware order, self-match-prevention, clearing-ledger, close-snapshot,
  EOD-settlement, and authorization keys; and
- migration/rebuild and protocol compatibility plans for REST, ALF, BALF, drop
  copy, bots, and simulators.

The current `trade.executed` contract identifies buy/sell gateway IDs but has
no account ID. Existing clearing and settlement primary keys are gateway/symbol
or gateway/date oriented. Adding a REST field cannot recover account ownership
for already emitted trades. Any future account design must start at that
execution contract and revisit every downstream identity key.
