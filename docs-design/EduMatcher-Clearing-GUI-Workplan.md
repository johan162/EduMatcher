# EduMatcher — Clearing GUI Release 1.0 Workplan

Companion design: [EduMatcher-Clearing-GUI.md](EduMatcher-Clearing-GUI.md)

Status: **Planned.** No work package (WP) below has started. The ordered plan
ships the read-only clearing client defined in the companion design, without
introducing margin, client accounts, or a clearing write path.

Started: 2026-11-09

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express its externally observable behaviour,
   using generated message models and realistic SQLite fixtures rather than
   hand-written lookalike payloads.
2. Run the focused test command and record the expected failure. The test must
   fail because the required behaviour is absent, not because of an import,
   syntax, fixture, or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add boundary, authorization, unit/precision, unavailable-store, and
   regression cases discovered during implementation.
5. Run the WP's focused tests and its affected package suite. Do not start the
   next WP with a known failing test.

Tests are not backfilled after an implementation. A finding discovered while
working a WP becomes a failing regression test before its fix is written.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 0 | CG0 | Contract fixtures, API test harness, and scope-policy test seam | — | 1 d | ☐ | |
| 1 | CG1 | Clearing current-state read API: participants, positions, exposure, daily, closes, symbols, trades | CG0 | 2 d | ☐ | |
| 2 | CG2 | Clearing operational-evidence API: events, gateway sessions, reconciliation, DB/process health | CG0, CG1 | 1.5 d | ☐ | |
| 3 | CG3 | EOD read API: settlements, derived balances, and run status | CG0 | 1.5 d | ☐ | |
| 4 | CG4 | API integration and reference: route schemas, query bounds, role matrix, and documented units | CG1–CG3 | 1 d | ☐ | |
| 5 | CG5 | `clearing-gui` foundation: workspace, auth, role routes, typed client, shell, proxy | CG4 | 2 d | ☐ | |
| 6 | CG6 | Participant self-service screens: current state, trade audit, daily/close history | CG5, CG1 | 2 d | ☐ | |
| 7 | CG7 | Operator screens: overview, participant drill-down, symbols, events, sessions, reconciliation | CG5, CG1, CG2 | 2.5 d | ☐ | |
| 8 | CG8 | EOD and market-maker screens: settlements/balances and resolved MM settings | CG5, CG3 | 1.5 d | ☐ | |
| 9 | CG9 | Release hardening: end-to-end checks, accessibility, performance bounds, deployment and user docs | CG4–CG8 | 2 d | ☐ | |

Suggested critical path: **CG0 → CG1 → CG4 → CG5 → CG6 → CG7 → CG9**.
CG2 and CG3 can proceed after CG0, but this plan schedules CG2 after CG1 so
operator UI responses can reuse the established clearing-route conventions.
CG3 can be implemented in parallel with CG1 or CG2 if separate ownership is
available. CG8 must wait for both the GUI foundation and EOD API.

Estimated sequential effort: approximately 15 days, excluding review time,
found findings, and deployment-environment investigation.

## 1. Scope and source-of-truth constraints

The workplan implements only behaviour supported by current stores and engine
contracts:

- Clearing identity is `gateway_id`; there are no client or broker subaccounts.
- `clearing.db` holds raw trades, gateway/symbol position state, daily
  summaries, close snapshots, session events, gateway sessions, and query
  helpers already used by `pm-clearing-cli`.
- `eod.db` holds gateway-or-`EXCHANGE` settlement rows, EOD run records, and
  derives balance from the roster opening balance plus settlement amounts.
- Clearing prices, P&L, and notionals are tick-unit values paired with
  `tick_decimals`. EOD amounts use 2-decimal `amount_minor`. The two formats
  must remain separate in contracts and UI helpers.
- `pm-api-gwy` currently has no clearing router. Its only clearing integration
  enriches the caller's `/positions` response with realized P&L periods.
- Authentication roles are `ADMIN`, `TRADER`, and `MARKET_MAKER`. The release
  API scopes ADMIN to venue data and TRADER/MM to their own gateway only.
- The terminal bridge is not a template for clearing. It exists to bridge raw
  TCP CALF; clearing will use the existing Trading GUI's HTTP/API-key pattern.

The following are excluded from all WPs: margin/equity/requirement computation,
client accounts, credit checks, pre-trade enforcement, clearing write routes,
intraday P&L history, and MM presence/re-quote compliance analytics.

## 2. Shared test data and execution conventions

CG0 establishes the reusable test fixtures; subsequent WPs extend them rather
than rebuilding isolated SQLite databases. Fixtures should represent:

- two participant gateways with both long and short positions in multiple
  symbols and differing `tick_decimals`;
- a retained raw trade, a daily summary, and close snapshots across at least
  two dates;
- `GAP`, `PHASE`, and `EOD` session events plus connected and disconnected
  gateway sessions;
- an EOD settlement date containing both gateway rows and the `EXCHANGE`
  rounding row, a roster opening balance, and an EOD run status; and
- API keys for ADMIN, TRADER, MARKET_MAKER, and a read-only identity with no
  `gateway_id`.

Use the repository's Python test runner for API/service tests and the existing
`trader-gui` Vitest/React Testing Library patterns for the new web app. Tests
must construct trades from the generated contract where applicable and use
real read-only SQLite connections. No browser test may receive a filesystem
path to a clearing or EOD database.


## 3 Route inventory

All routes below are proposed additions. None exists at the present time. 
List rows return `count`, apply a bounded `limit`, and use
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

### 3.3 EOD read model

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


## 4. Work packages

### CG0 — Contract fixtures, API test harness, and scope-policy test seam

**Purpose.** Create the smallest reusable testing foundation that can express
the release-1.0 read contract and verify that authorization is enforced on the
server, not by hidden UI links.

**Depends on:** —

**Test-first workstep.** Add failing behavioural tests at the API-gateway auth
test seam for clearing scope resolution. The tests assert that an ADMIN receives
venue scope, a TRADER/MM receives only its own gateway scope, a supplied foreign
gateway is rejected, and a read-only key is denied. The initial failures must
demonstrate that this policy is absent, not a fixture/import problem. These
tests become green when CG0's scope resolver exists and enforces the policy.

**Implementation worksteps.**

1. Locate and reuse the API-gateway application fixture, auth helpers, and
   configuration override pattern already used by router tests.
2. Add deterministic temporary `clearing.db`, `eod.db`, and roster fixtures
   based on the real schema/query helpers. Seed them through production store
   helpers or explicit test-only SQL that matches the shipped schema.
3. Add test credentials representing ADMIN, TRADER, MARKET_MAKER, and
   unaffiliated read-only access.
4. Introduce a small shared clearing-route scope resolver/test seam. Its API
   receives the authenticated session and requested gateway and yields either
   venue scope, the caller's gateway scope, or a typed authorization error.
   It must not read a client-provided gateway before deciding the caller's
   allowed scope.
5. Add only the test support and scope policy in this WP. CG1 starts its own
   failing route tests after this foundation is green.

**Exit criteria.**

- The test fixture can open both databases read-only through the same paths the
  gateway will use.
- Tests prove the scope resolver's ADMIN, TRADER, MARKET_MAKER, foreign-gateway,
  and read-only outcomes.
- All CG0 tests, including the initially failing scope-policy cases, now pass.
- Fixture data covers cross-symbol precision, EOD rounding, and at least one
  GAP event.

**Performance impact.** Test-only. The fixtures must stay small and
per-test isolated so they do not lengthen the API suite materially. The scope
resolver performs constant-time session checks and creates no database load.

---

### CG1 — Clearing current-state read API

**Purpose.** Expose the existing clearing ledger data needed for participant
and current-state screens through authenticated, typed, read-only REST routes.

**Depends on:** CG0

**Test-first workstep.** Unmark/activate CG0's route test, then add failing
route tests for `participants`, `positions`, `exposure`, `trades`, `daily`,
`close-snapshots`, and `symbols`. The tests must assert response schemas,
role scope, filter behaviour, supplied `tick_decimals`, bounded result counts,
and preservation of trade audit fields. They fail until the router and handlers
exist.

**Implementation worksteps.**

1. Add `api_gateway/routers/clearing.py` and register it in the existing
   `pm-api-gwy` application under the existing `/api/v1` prefix.
2. Define typed response models and query parameters. Reuse date validation,
   authentication dependencies, response envelopes, and bounded-limit patterns
   already present in the API gateway.
3. Open `clearing.db` read-only per request or through the repository's safe
   read helper. Return a clear service-unavailable response for missing or
   locked databases; never silently transform this into an empty ledger.
4. Build handlers from existing `clearing.store` query helpers. Extend
   `query_trades` and its response type to select and expose persisted
   `match_type` and `msg_id`.
5. Apply the shared scope resolver to every gateway-bearing route. For a
   TRADER/MM request, server-side scope overrides an absent gateway filter and
   rejects a different requested gateway.
6. Normalize money only at the response/UI presentation boundary. Preserve
   raw tick values with `tick_decimals`; do not aggregate raw cross-symbol
   values into a single unqualified number.
7. Provide `summary` and participant-detail responses only from data that is
   actually stored. They may report P&L and counts but not equity, margin,
   buying power, or long/short open interest.

**Exit criteria.**

- Authenticated routes exist for the current-state data inventory in the
  clearing design: summary, participants/detail, positions, exposure, trades,
  daily rows, close snapshots, and symbols.
- API tests pass for ADMIN venue scope, TRADER/MM self scope, unaffiliated
  read-only denial, valid filters, invalid dates/sorts/limits, missing/locked
  database, and a no-results response.
- Tests prove that a trade response contains its stored audit `match_type` and
  `msg_id` and all price/P&L-bearing data carries precision/units.
- Tests prove that no cross-symbol tick total is emitted as a display-currency
  total without row-wise normalization.
- Existing API gateway and clearing test suites pass.

**Performance impact.** Current positions and participant totals query small
aggregate tables and are appropriate for five-second polling with a bounded
limit. Trades can be large, so date/gateway/symbol indexes and a strict limit
are mandatory; no unbounded trade export route is introduced. SQLite reads run
off the async event loop where the gateway's existing patterns require it.

---

### CG2 — Clearing operational-evidence API

**Purpose.** Provide the evidence an operator needs to judge completeness,
lifecycle, and reconciliation instead of presenting the ledger as infallible.

**Depends on:** CG0, CG1

**Test-first workstep.** Add failing ADMIN route tests for session events,
gateway sessions, reconciliation, and health. Include a test in which SQLite
is readable but the clearing receive-loop health probe does not answer; it must
report database state and process liveness separately. Add self-scope tests for
gateway-session access and denial tests for participant access to venue-wide
events, health, and reconciliation.

**Implementation worksteps.**

1. Add typed handlers for `session-events`, `gateway-sessions`, and
   `reconciliation`, backed by their existing clearing query helpers.
2. Decode event payloads into an explicit API representation. Retain the raw
   payload only where the response contract documents it; expose GAP sequence
   bounds/missing count as typed fields when present.
3. Restrict session-event, reconciliation, and health views to ADMIN. Scope
   gateway sessions to the caller for TRADER/MM.
4. Add a clearing health response that names database availability/state and
   receive-loop liveness as separate fields. Use the existing clearing health
   interface with a short bounded timeout; a failed liveness probe must not
   make the SQLite facts disappear.
5. Document in handler descriptions and response fields that event timestamps
   are clearing-observed times and reconciliation is limited to retained raw
   trade data.

**Exit criteria.**

- The four operational routes exist with typed, bounded, filtered responses.
- Tests pass for GAP event content, phase/EOD event filtering, connected-only
  gateway sessions, reconciliation discrepancy/no-discrepancy, and both health
  dimensions.
- Tests prove that a non-ADMIN cannot read venue-wide operational evidence.
- API descriptions communicate the retention and observation-time limits.

**Performance impact.** Event/session lists are indexed and bounded. The
health probe adds at most one short local request per health call, so it must
not run on every participant-table refresh. Reconciliation can scan retained
raw trades; it remains an explicit operator action with date/filter bounds,
not a dashboard polling query.

---

### CG3 — EOD read API

**Purpose.** Expose the implemented daily settlement ledger and derived gateway
balances without reinterpreting settlement as margin or cash collateral.

**Depends on:** CG0

**Test-first workstep.** Add failing tests for `GET /api/v1/clearing/settlements`
and `GET /api/v1/clearing/balances`. The tests cover minor-unit formatting data,
positive/negative signs, per-symbol detail, an opening balance plus multiple
settlement rows, an EOD run status, and ADMIN-only visibility of `EXCHANGE`.
Self-service tests must fail if a caller can supply another gateway ID.

**Implementation worksteps.**

1. Add explicit read-only EOD query helpers rather than parsing CLI text.
   Reuse `eod.ledger` semantics for settlement dates, details, balances, and
   opening balances.
2. Define response models that preserve raw `amount_minor`, display amount,
   account/gateway ID, detail values, as-of date, and EOD run status.
3. Enforce the shared API scope. `EXCHANGE` is omitted outside ADMIN venue
   scope, even if a participant guesses the account name.
4. Treat a missing EOD database or absent settlement date as distinct states:
   unavailable service versus valid empty/no-settlement result.
5. Add route descriptions stating that balance is derived and that settlement
   is close-to-close P&L transfer, not collateral or margin.

**Exit criteria.**

- Settlement and balance routes are read-only, typed, scoped, and documented.
- Tests pass for minor-unit conversion inputs, signs, rounding account access,
  per-symbol detail, computed balance, as-of handling, run statuses, empty
  dates, and unavailable EOD store behaviour.
- No endpoint calls a CLI formatter or labels a settlement/balance result as
  equity, cash collateral, or margin.

**Performance impact.** EOD data is small and changes only when `pm-eod` runs.
Balance calculation scans settlement rows up to the requested date; cache
results in the client by as-of date and require an explicit bound if the ledger
becomes large. This route is not part of five-second current-state polling.

---

### CG4 — API integration and reference contract

**Purpose.** Freeze a coherent, implementable release-1.0 API contract before
the browser client depends on it.

**Depends on:** CG1–CG3

**Test-first workstep.** Add a failing OpenAPI/route-integration test that
asserts all release-1.0 clearing routes are registered beneath `/api/v1`, each
has a response model and documented authorization response, and no clearing
route is writable. Add failing contract tests for the role matrix and the
separate tick/minor-unit fields expected by consumers.

**Implementation worksteps.**

1. Complete API descriptions, parameter constraints, example/error responses,
   and response model annotations for CG1–CG3 routes.
2. Add or update the API gateway reference and clearing user documentation from
   the implemented schemas, not an independently maintained route list.
3. Confirm that all list endpoints have bounded limits and stable ordering;
   define the continuation parameter only where a route needs pagination.
4. Record the five-second clearing flush qualifier, raw-event retention,
   session observation timestamps, and reconciliation limitations in API docs.
5. Add a compatibility check that the existing `/positions` P&L enrichment is
   unchanged. The new API adds detail; it does not alter current trading-client
   behaviour.

**Exit criteria.**

- The generated OpenAPI document and user/API references agree on every
  release-1.0 clearing route, scope, unit, freshness, and retention limit.
- Integration tests pass for registration, read-only method set, role matrix,
  schema validation, and unchanged existing `/positions` behaviour.
- A browser consumer can generate or hand-maintain typed models solely from the
  released API contract.

**Performance impact.** Documentation and contract tests add no runtime cost.
Route/limit review prevents an accidental unbounded query becoming a UI polling
load. OpenAPI generation runs only in test/build workflows.

---

### CG5 — `clearing-gui` foundation

**Purpose.** Establish a role-aware, deployable web client using the proven
`trader-gui` composition before building clearing screens.

**Depends on:** CG4

**Test-first workstep.** Create failing component tests for login/status
resolution, role-specific landing redirects, `RoleGuard` behaviour, an API
client that validates a clearing response, and a protected route's loading,
empty, API-error, and forbidden states. The first tests fail because
`clearing-gui` does not exist.

**Implementation worksteps.**

1. Create `web-apps/clearing-gui` with `apps/web` and `apps/serve`, Dockerfile,
   compose wrapper, Makefile, and `.env.example` matching the Trading GUI's
   ownership and build/deploy layout.
2. Use React, TypeScript, Vite, React Router, shadcn/Radix, Tailwind, TanStack
   Query, Zustand, Zod, and the existing test tooling. Reuse conventions, not
   source files that would couple the two applications.
3. Implement login through `GET /api/v1/status`, role store, role landing
   routes, application shell, error boundary, connection status, and common
   table/filter/pagination primitives.
4. Add a typed `apiFetch` layer and Zod response parsers for the frozen CG4
   contract. Parsing failure is an explicit API-contract error, never a blank
   table.
5. Implement a same-origin `/api` proxy in the static server and Vite dev
   proxy. The GUI has no direct SQLite, bus, or clearing-health socket access.
6. Add shared formatters that require `tick_decimals` for clearing money and
   use a separate `amount_minor` formatter for EOD data.

**Exit criteria.**

- The app builds, type-checks, and serves through development and production
  proxy paths.
- Component tests pass for login, role landing, route guard, response parsing,
  loading, empty, error, and forbidden states.
- The browser communicates only with `/api/v1` and never receives database
  paths, direct bus credentials, or a process-health endpoint address.
- Shared formatting tests reject attempts to use a tick value without
  precision or an EOD minor-unit value as a clearing tick value.

**Performance impact.** This WP adds no high-frequency subscriptions. TanStack
Query cache keys must include the authenticated scope and filters to prevent
cross-participant display. Bundle size should remain close to the Trading GUI
baseline; use route-level lazy loading before dashboard libraries are added.

---

### CG6 — Participant self-service screens

**Purpose.** Deliver the participant view: factual current state and audit
history for the authenticated gateway.

**Depends on:** CG5, CG1

**Test-first workstep.** Add failing React tests for the My Clearing page:
self-scoped position/exposure rows; trade filtering with retention text;
daily/close-history rendering; precision-correct money cells; and an API error
that differs from a true zero-position empty state. Include a test ensuring no
participant page renders an unsupported margin, equity, or buying-power tile.

**Implementation worksteps.**

1. Add self-only routes for Current Positions, Exposure, Trades, and
   Daily/Close History. Use the server-provided scope rather than a user-editable
   gateway selector.
2. Build TanStack Query hooks from CG4 types with query keys including filters,
   date ranges, and pagination continuation where applicable.
3. Display exchange trade timestamp and clearing ingest timestamp distinctly.
   Surface retained trade range/limit beside the audit table.
4. Render daily close history only from close snapshots and label charts
   `close-to-close`; do not create an intraday line from current snapshots.
5. Apply shared unit formatters row by row and show the supplied precision in
   an audit/detail view when useful.
6. Implement accessible filters, stable table sorting, row drill-downs,
   skeletons, empty states, retry, and forbidden handling.

**Exit criteria.**

- TRADER and MARKET_MAKER self-service routes render only their own API data.
- Tests pass for precision formatting, signed quantities, filters, retention
  disclaimer, close-to-close chart labelling, true-zero versus unavailable
  data, and absence of unsupported risk values.
- Browser network tests prove the page uses CG1 routes and never includes a
  caller-selected foreign gateway ID.

**Performance impact.** Poll positions/exposure at no faster than five seconds,
matching clearing's normal flush interval. Trade and history requests are
filter-driven and paginated, not polled. Daily/close responses should cache by
date range and only revalidate when current-state freshness changes.

---

### CG7 — Operator screens

**Purpose.** Deliver the ADMIN operations workflow: venue state, participant
drill-down, operational evidence, and reconciliation.

**Depends on:** CG5, CG1, CG2

**Test-first workstep.** Add failing component/integration tests for the
Clearing Overview's freshness qualifier and GAP alarm, participant drill-down,
event/session filters, health dimensions, and reconciliation limitation text.
Add a route-guard test proving a non-ADMIN cannot navigate to or load these
views, even by entering a URL directly.

**Implementation worksteps.**

1. Implement the ADMIN Clearing Overview from `summary` and `health`, showing
   latest trade/flush time, database state, process liveness, recent EOD state,
   and GAP evidence.
2. Add participant list and drill-down routes that compose CG1 current state
   with CG2 session evidence while preserving API scope and table limits.
3. Add Symbols view as activity/current aggregate net quantity only. Do not
   title or imply it is an open-interest or concentration report.
4. Add Events, Gateway Sessions, and Reconciliation views with explicit
   filters, duration/retention qualifiers, and deep links to a participant
   where the API response permits it.
5. Make reconciliation an explicit user action with date bounds. An empty list
   must render “no discrepancy in the queried retained data”, not “ledger
   verified”.
6. Apply route guard, unauthorized-state handling, and accessible status
   badges/announcements for GAP or unhealthy process results.

**Exit criteria.**

- ADMIN can operate every release-1.0 venue-wide clearing screen from the UI.
- Tests pass for GAP visibility, separate health dimensions, event/session
  filters, reconciliation wording, participant drill-down, direct-URL role
  denial, and symbol-page terminology.
- No operator screen fabricates venue-wide exposure, equity, margin,
  open-interest, or compliance measurements absent from its API response.

**Performance impact.** Overview polls only small current summary/health
responses at the five-second cadence. Events/sessions/reconciliation are
bounded, user-filtered queries. The reconciliation screen must never be
mounted as an auto-refreshing dashboard query because its raw-trade comparison
can be expensive.

---

### CG8 — EOD and market-maker screens

**Purpose.** Complete the remaining participant-obligation views supported by
existing code: EOD settlement/balance and resolved MM configuration.

**Depends on:** CG5, CG3

**Test-first workstep.** Add failing component tests for settlement signs and
minor-unit display, derived-balance inputs, EOD run status, ADMIN-only
`EXCHANGE` visibility, and the MM settings table. Add a negative assertion
that the MM screen does not render a presence percentage, re-quote SLA, or
compliance score as observed fact.

**Implementation worksteps.**

1. Add self-service EOD Settlement and Balance views, plus ADMIN venue and
   participant settlement views, using CG3 routes and the minor-unit formatter.
2. Display opening balance, cumulative settlement effect, derived balance,
   per-symbol detail, date/as-of filter, and run status as separate values.
3. Display `EXCHANGE` only in ADMIN venue scope and label it as the rounding
   residual account.
4. For MARKET_MAKER, call the existing requester-scoped `/api/v1/symbols`
   endpoint and display only `enforce_mm_obligation`, maximum spread ticks,
   and minimum quantity.
5. Use explanatory copy that settlement is not margin/collateral and MM data
   is configured enforcement input, not observed compliance.

**Exit criteria.**

- EOD screens show correctly signed/displayed minor-unit values, balances, and
  run states for authorized users.
- Tests pass for role visibility of `EXCHANGE`, self-scope, date handling,
  MM settings fields, and all negative unsupported-claim assertions.
- The MM screen retains the existing `/symbols` endpoint's requester scope and
  does not request a venue-wide MM data route.

**Performance impact.** EOD data is cacheable by date/as-of date and needs no
current-state polling. `/symbols` is a bounded reference call; refetch it on
login/config refresh rather than on each render. The screens add negligible
load to clearing.db.

---

### CG9 — Release hardening and documentation

**Purpose.** Verify that the assembled release is usable, secure, supportable,
and honest about its operational limits.

**Depends on:** CG4–CG8

**Test-first workstep.** Add failing end-to-end smoke tests for ADMIN,
TRADER, and MARKET_MAKER journeys against seeded clearing/EOD data. Add failing
accessibility checks for role navigation, tables, filters, status badges, and
error states. Add a performance test that fails if a dashboard causes
unbounded trade/reconciliation requests or polls static EOD/history routes at
the five-second current-state cadence.

**Implementation worksteps.**

1. Run browser journeys for login, role landing, self view, ADMIN drill-down,
   GAP/event evidence, reconciliation, EOD settlement, and MM settings.
2. Verify all API and browser failures have actionable states: auth denial,
   missing/locked clearing/EOD database, unavailable clearing liveness,
   invalid filter, no data, and stale/flush-lag qualifier.
3. Run keyboard-only navigation and automated accessibility checks. Ensure
   status badges have textual alternatives and tables remain usable without
   colour alone.
4. Measure representative API queries on a realistic retained-trade database.
   Record limits, response size, p50/p95 latency, and database/query plan for
   current polling versus explicit audit/reconciliation actions.
5. Add deploy/runbook documentation: required `pm-clearing`, `pm-eod`, and
   `pm-api-gwy` configuration; GUI environment variables; health diagnosis;
   role credentials; units; retention; and known non-goals.
6. Cross-check the release against `EduMatcher-Clearing-GUI.md`. Remove or
   defer any screen/control whose required authenticated API route is not
   shipped.

**Exit criteria.**

- All release journeys and accessibility tests pass for each role.
- Performance tests/measurements prove five-second polling uses only bounded
  current-state endpoints; no automatic reconciliation or raw-history sweep
  occurs.
- API, GUI, deployment, and user docs name every shipped route and disclose
  scope, units, freshness, retention, GAP meaning, settlement semantics, and
  non-goals.
- The release checklist contains no unresolved high-severity finding and no
  screen depending on a CLI, direct SQLite access, or a proposed-only API.

**Performance impact.** This WP sets rather than guesses performance limits.
The critical runtime protection is request discipline: small bounded current
queries may poll; raw audit, EOD history, and reconciliation remain cached or
explicitly user-triggered. Bundled frontend size and initial route load should
be measured and documented before release.

## 5. Findings

Populate this section only while implementing the workplan. Every confirmed
finding needs an ID, evidence, impact, owning WP, and a test-first disposition.
A finding is closed only when a regression test that previously failed now
passes.

| ID | Found in WP | Observation and evidence | Impact | Classification | Test-first action | Status |
|---|---|---|---|---|---|---|
| — | — | _No findings recorded yet._ | — | — | — | — |

Classification: **implementation defect**, **contract ambiguity**,
**data-quality/observability gap**, **performance constraint**,
**documentation defect**, or **test defect**.

When a finding expands the release scope, add a new WP to the Status table,
state its dependency, and preserve the original WP's exit criteria. Do not
silently fold unplanned capability such as margin or client accounts into a
clearing-GUI WP.

## 6. Release checklist

Before declaring the client ready for release 1.0, confirm:

- [ ] Every Status-table WP is ☑, or any deferred WP is explicitly removed from
  the release scope and all dependent UI routes are absent.
- [ ] Every WP began with its stated failing functional test and has focused
  and affected-suite evidence of passing tests.
- [ ] The API has no unauthenticated or cross-gateway clearing data leak.
- [ ] The GUI never accesses SQLite, the clearing bus, or the clearing health
  socket directly.
- [ ] Tick-unit and minor-unit values are never mixed or aggregated without
  their declared conversion.
- [ ] GAP, clearing flush lag, retention, observation timestamps, and EOD
  settlement limitations are visible to relevant users.
- [ ] No shipped label or calculation claims margin, client account, collateral,
  intraday P&L history, open interest, or MM compliance without a new
  authoritative implementation and corresponding WP.
- [ ] Deployment, API, and user documentation were verified against running
  route schemas and browser journeys.
