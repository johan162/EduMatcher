# EduMatcher — Clearing GUI Release 1.0 Workplan

Companion design: [EduMatcher-Clearing-GUI.md](EduMatcher-Clearing-GUI.md)

Status: **In progress.** All work packages done (CG0–CG4 2026-11-10, CG5–CG9 2026-11-11), uncommitted. Release checklist §6 below. The ordered plan
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
| 0 | CG0 | Contract fixtures, API test harness, and scope-policy test seam | — | 1 d | ☑ | 2026-11-10 |
| 1 | CG1 | Clearing current-state read API: participants, positions, exposure, daily, closes, symbols, trades | CG0 | 2 d | ☑ | 2026-11-10 |
| 2 | CG2 | Clearing operational-evidence API: events, gateway sessions, reconciliation, DB/process health | CG0, CG1 | 1.5 d | ☑ | 2026-11-10 |
| 3 | CG3 | EOD read API: settlements, derived balances, and run status | CG0 | 1.5 d | ☑ | 2026-11-10 |
| 4 | CG4 | API integration and reference: route schemas, query bounds, role matrix, and documented units | CG1–CG3 | 1 d | ☑ | 2026-11-10 |
| 5 | CG5 | `clearing-gui` foundation: workspace, auth, role routes, typed client, shell, proxy | CG4 | 2 d | ☑ | 2026-11-11 |
| 6 | CG6 | Participant self-service screens: current state, trade audit, daily/close history | CG5, CG1 | 2 d | ☑ | 2026-11-11 |
| 7 | CG7 | Operator screens: overview, participant drill-down, symbols, events, sessions, reconciliation | CG5, CG1, CG2 | 2.5 d | ☑ | 2026-11-11 |
| 8 | CG8 | EOD and market-maker screens: settlements/balances and resolved MM settings | CG5, CG3 | 1.5 d | ☑ | 2026-11-11 |
| 9 | CG9 | Release hardening: end-to-end checks, accessibility, performance bounds, deployment and user docs | CG4–CG8 | 2 d | ☑ | 2026-11-11 |

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

All routes below are implemented (CG1–CG3, frozen in CG4, 2026-11-10); the
normative contract is the "Clearing" chapter of
`docs/books/protocols-and-clients/part-2-specifications/060-rest-and-websocket.md`
and `spec/rest/openapi.json`, which supersede this table where they differ.
List rows return `count` and `has_more` and apply a bounded `limit`; only
`trades` needed cursor pagination.

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

**Done 2026-11-10.** First run: 11 failing (`NotImplementedError` from the
stubbed resolver/read-only opener, `TypeError` for the absent `eod_db`), 5
fixture-shape tests passing; then all 16 green; full suite and `make _check`
clean.

- `tests/clearing_api_fixture.py` builds `clearing.db` by feeding generated
  `TradeExecuted` messages (with envelopes, so `msg_id` is stored), session
  phases, gateway connect/bye and `system.eod` through the real
  `ClearingProcess` dispatch at a patched clearing clock; `eod.db` is settled
  from those snapshots by pm-eod's own `settle_date`/`record_day`, with one
  hand-added `EXCHANGE` rounding cent on the second day (real snapshots cancel
  exactly). `make_clearing_app` wires the real app with ADMIN (OPS01), TRADER
  (TRADER01), MARKET_MAKER (MM01) and read-only keys.
- `api_gateway/clearing_scope.py`: `clearing_scope(request, session,
  requested)` → `ClearingScope(caller, admin, gateway)`. Role from
  `engine.resolve_role` (an unanswered lookup is `TRADER`: fails closed);
  foreign gateway → `403 SCOPE_DENIED` (new registry code; audited as
  `ROLE_DENIED`); read-only → `403 READ_ONLY`.
- `eod.ledger.open_ledger_readonly` (never creates the file).
- New config key `api_gateways.<name>.eod_db` (default `data/eod.db`);
  `ApiGatewayConfig.eod_roster` derives `ref_data/roster.yaml` beside it,
  as `pm-eod --datapath` does. Mirrored in the verifier, config-gen comments
  and config-gui (types, zod, defaults, codec, Gateways tab).
- Decision: the clearing health address is **not** a config key; it is the
  env-derived `CLEARING_HEALTH_ADDR` that `pm-clearing-cli health` pings.

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
   buying power, or long/short open interest. *(Amended by D8, §9.1, 2026-11-26:
   `/clearing/symbols` reports each symbol's long and short totals.)*

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

**Done 2026-11-10.** First run: 33 failing, all on the absent routes (`404`
against a route-less stub router); then green, plus the contract suites
(layout, error codes, OpenAPI examples, spec tables) and the full suite.

- `api_gateway/routers/clearing.py` (tag `clearing`, `/api/v1/clearing`):
  `summary`, `participants`, `participants/{gateway_id}`, `positions`,
  `exposure`, `trades`, `daily`, `close-snapshots`, `symbols`. Response
  models in `responses.py` (Clearing section); examples in `openapi_docs.py`.
- Units decision: every row money column is `<name>_ticks` (as stored) +
  `<name>` (display, the row's own precision) beside `tick_decimals` — the
  `/book` `price`/`price_ticks` convention. Cross-symbol totals
  (`participants`, `summary`) are display-currency sums only, computed per
  row in SQL (`store.query_participants`).
- Lists: `{"<plural>", "count", "has_more"}` with `limit` 1-5000 (query run
  with `limit + 1`). Only `trades` is cursor-paginated (`next_cursor`/`after`
  over `(ts_ns, ingest_ts_ns, id)`); it also reports `retained_from`
  (`store.query_retained_from`).
- `store.query_trades` now selects `match_type`, `msg_id` and takes `after`.
  A participant's trade rows null the counterparty's gateway and order id.
- `503 CLEARING_DB` for a missing, locked (busy timeout `_BUSY_TIMEOUT_MS`)
  or unreadable ledger; the message never carries the path. `400` for a bad
  date, `from > to`, `limit`, `sort` or cursor. `summary` reads `eod.db`
  optionally: `eod_db_available: false` instead of failing.
- Summary GAP semantics: `session_date` = latest `trade_date` in
  `session_events`; `gap_count` = GAP rows on it; `latest_gap` = newest ever.
- Log-ledger entries for the two new WARNING sites; normative spec chapter
  "Clearing" in `060-rest-and-websocket.md`.

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

**Done 2026-11-10.** First run: 19 failing on the absent routes; one test
defect (expected event order ignored that a GAP is stamped with the trade
after it) fixed in the test; then green with the full suite and checks.

- `session-events` (ADMIN): `type` (case-insensitive, unknown → `400`),
  `from`/`to`, bounded. Each row has exactly one of `phase` / `gap` / `eod`;
  the stored JSON is not exposed. Store order gained an `id DESC` tie-break.
- `gateway-sessions` (scoped): `from`/`to` are trading days **in the session
  timezone** (`store.query_sessions` gained exact `from_ns`/`to_ns`; its
  `from_date`/`to_date` still compare the UTC date for the CLI);
  `connected_only`.
- `reconciliation` (ADMIN): `from` and `to` are **required** (an explicit,
  bounded operator action); rows carry `tick_decimals` (added to
  `store.query_reconcile`) and `*_ticks`/display notionals; the range is
  clamped to `retained_from` and the reply names the window compared
  (`compared_from`/`compared_to`, `null` when nothing is left to compare).
- `health` (ADMIN): always `200` with `database` (available/detail, journal
  mode, row counts, latest trade/flush) and `process` (alive/detail from a
  0.5 s ping of `CLEARING_HEALTH_ADDR`, run concurrently with the DB read).
  `query_health`'s `db_path` is dropped; no address is returned.

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

**Done 2026-11-10.** First run: 20 failing on the absent routes; then green
with the full suite and checks.

- `eod.ledger`: read-only `query_settlements` (account filter,
  `include_exchange`), `query_runs`, `last_settled_on_or_before`; balances
  reuse `ledger.balances`, openings `roster.load_roster`.
- `settlements` (scoped): rows `trade_date, account, amount_minor, amount`
  (decimal string via `report.fmt_minor`), `detail` (per-symbol unrounded
  decimal strings), `run_status`; plus `runs` for the date range (failed
  days without rows included). Participants get runs **without** `steps`
  (operator messages); `EXCHANGE` is filtered in SQL for non-ADMIN and
  naming it is `SCOPE_DENIED`.
- `balances` (scoped): `opening_balance_minor` (roster), 
  `settlement_total_minor`, `balance_minor` with decimal-string twins,
  `as_of`, `last_settled_date`. A gateway on neither roster nor ledger gets
  zeros (true zero).
- `503 EOD_DB` for a missing/unreadable `eod.db` **or** a malformed roster
  (the roster error names a file path, so it is logged, not returned); a
  missing roster is an empty roster, as in pm-eod. A date pm-eod has not
  settled is an empty list.

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

**Done 2026-11-10.** `tests/test_api_gateway_clearing_contract.py` first ran
7 failing: the operator guide, participant guide and four configuration
references did not name the routes / `eod_db` (genuine), and one test defect
(a phrase split by a docstring line break; whitespace now normalised). The
registration, read-only, authorization-docs, role-matrix, unit and bound
tests passed at once because CG1–CG3 had been built against the same
conventions — recorded here rather than claimed as red-first.

- Contract test: exactly the 15 routes, `GET` only (other methods `405` with
  `Allow: GET`), each with a `$ref` 200 model, `401`, and a `403` listing
  `READ_ONLY` plus its role/scope code; role matrix ADMIN/TRADER/MM/read-only
  /no key through the app; every `*_ticks` has `tick_decimals` and a display
  twin; `*_minor` schemas carry no ticks and have a decimal-string twin; no
  margin/equity/collateral/buying-power/open-interest field; every growing
  list has `limit` 1..5000; reconciliation range required; tag and route
  descriptions state flush lag, retention, observation time, the
  reconciliation and settlement limits; `/positions` row pinned and its
  period query run against the fixture ledger.
- Stable order of every list (store `ORDER BY` reviewed; ties broken on the
  key): participants by gateway; positions gateway/symbol; exposure measure
  then gateway/symbol; daily and close snapshots date desc/gateway/symbol
  (the primary key); symbols by symbol; events `ts_ns, id`; sessions
  `connected_at_ns, gateway_id` (the key); settlements date desc/account
  (the key); reconciliation date/side/gateway/symbol. Only `trades` needs a
  continuation parameter; `balances` is bounded by the roster and ledger
  accounts and has no `limit`.
- Docs: spec `060-rest-and-websocket.md` (Clearing chapter, index, common
  error codes, auth bullet), operator guide `050-api-gateway.md` (config,
  route table, operating limits, key classes), participant guide
  `010-positions-and-pnl.md` ("Your clearing record over REST"), config
  references (`005`, `010`, `030`), process reference `--clearing-db`, zsh
  completion; `make openapi`, `make docs-site` (no warnings on these pages).
  `make -C docs docs-check` reports one pre-existing, unrelated problem
  (`040-log-server.md`: `pm-log-cli ledger check --package`).

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

**Done 2026-11-11.** First run, against stub modules (so nothing failed on
an import): 38 failing on absent behaviour; then green, with typecheck,
build, the repository's GUI port and deployment tests and the full Python
suite.

- `web-apps/clearing-gui` (`pm-clearing-ui`), number N=6 in the port scheme:
  container 8096, Vite 8196 proxying `/api` to `localhost:8080`; no dev
  backend. `apps/serve/serve.ts` is trader-gui's static server minus the
  WebSocket upgrade proxy (the GUI opens no socket), plus a 400 for a
  malformed URL escape (it threw inside the handler and ended the process;
  trader-gui's copy was fixed the same way afterwards).
- `api/apiFetch.ts` validates every body with Zod (`api/schemas.ts`): a
  mismatch is `ContractError`, a 401 logs out, no answer is `NetworkError`
  (and the top bar's connection badge says so). `api/queries.ts` holds every
  hook and the request policy (5 s current state, 30 s health, cached
  history/EOD, reconciliation on demand), keys `["clearing", caller, route,
  params]`.
- `lib/money.ts`: `Ticks` and `Minor` are branded types the schemas apply to
  `*_ticks` / `*_minor`; `formatTicks` refuses a missing/invalid precision,
  `formatMinor` is exact integer arithmetic.
- `test/contract.test.ts` parses every clearing example of
  `spec/rest/openapi.json` with the GUI's schemas and compares field sets and
  required-ness: the browser's typed models come from the released contract
  (CG4 exit criterion).
- Login via `GET /api/v1/status` (key in memory only), role landing
  (ADMIN → `/overview`, TRADER/MM → `/me/positions`), `RoleGuard`, lazy
  routes, error boundary, `QueryState` (loading / error / forbidden /
  contract / unreachable / empty), sortable accessible `DataTable`, filter
  forms. Deployment wiring the repository enforces for a new GUI: the five
  compose files, docker Makefile lists and `dev-env`, `edumatcher.sh`, the
  GHCR workflow matrices, `mkghrelease.sh`, `mkbld.sh` (version.json),
  `.env*.example`, `web-apps/Makefile` and README.

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

**Done 2026-11-11.** `test/myClearing.test.tsx`: 12 failing against the
CG5 page shells, then green.

- Shared views (`components/views/`), reused by the ADMIN drill-down with a
  fixed `gateway`: `PositionsView` (positions + exposure, 5 s, freshness
  line "committed by clearing at … up to 5 s"), `TradesView` (infinite
  query, "Load more" with the server cursor, retention line, exchange time
  and clearing ingest as separate columns), `HistoryView` (daily rows,
  close snapshots, a close-to-close chart lazy-loaded with Recharts, and a
  "Closes by day" table where each close sums its rows after converting each
  with its own precision).
- Money cells only through `columns.tsx` `tickColumn` (row precision, sort in
  display currency). Participant pages never send `gateway` (tested on every
  request).
- History is never polled: `useHistoryRevalidation` polls the small
  positions response and invalidates daily/close queries only when the
  newest position write moves (tested both ways with fake timers).

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

**Done 2026-11-11.** `test/admin.test.tsx`: 18 failing (the navigation test
already passed from CG5), then green after one wording fix (proper plurals
in the GAP alarm).

- Overview: freshness and flush qualifier, a `role="alert"` GAP alarm
  (count, missing trades, id interval, run, time, and the "no gap does not
  prove completeness" caveat -- also shown when there is no gap), stat tiles
  limited to counts and venue P&L in display currency, last EOD run (or
  "EOD ledger unavailable"), Health panel with database and process as two
  lines, participants table with drill-down links, recent session events.
  Summary/participants 5 s, health 30 s, events once (tested with fake
  timers).
- Participant drill-down `/participants/:id/*` with tabs Positions, Trades,
  History, Settlement (CG8), Sessions -- every request carries `gateway`.
- Symbol Activity (titled and explained as not open interest), Events (type
  filter, payload in words), Gateway Sessions (gateway and connected-only
  filters; the participant's `/me/sessions` uses the same view without
  `gateway`), Reconciliation (Run with required dates, never refetched,
  "Compared X to Y; raw trades are kept from Z", "No discrepancy in the
  queried retained data", "Nothing was compared" when the range predates
  retention).

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

**Done 2026-11-11.** `test/eod.test.tsx`: 12 failing against the shells,
then green.

- `components/views/SettlementView.tsx` in three modes: `self`
  (`/me/settlement`, no `gateway`), `gateway` (the drill-down's Settlement
  tab) and `venue` (`/eod`: account and date filters, every account,
  `EXCHANGE` shown as "rounding residual account", balances table, runs
  with their steps). Amounts only through `formatMinor` (`Minor`-branded
  fields); direction in words ("Exchange owes you" / "You owe the
  exchange"); per-symbol unrounded parts; run status badge; the derived
  balance as opening + settlements-to-date + derived balance with an as-of
  filter; "not margin, collateral or a completed payment" copy. Cached,
  never polled.
- `/me/obligations` (MARKET_MAKER) reads only the requester-scoped
  `GET /api/v1/symbols` (cached for the session): obligation Enforced / Not
  enforced / Not configured (absent fields), max spread as ticks and display
  price, min quantity; copy "configured enforcement parameters … not a
  measure of how you quoted"; no presence, re-quote or compliance figure
  (tested).

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

**Done 2026-11-11.**

- *Request discipline* (`test/requests.test.tsx`): every one of 17 screens,
  left open for a fake minute, repeats only bounded current-state routes at
  no more than one per 5 s, requests every other route once, never calls
  reconciliation, and pages trades at 200. Passed at once: the policy was
  built into `api/queries.ts` in CG5 (recorded rather than claimed red-first).
- *Accessibility* (`test/a11y.test.tsx`): axe-core on 13 screens with data
  loaded (`color-contrast` off: jsdom cannot paint), keyboard sorting with
  `aria-sort`, statuses in text. First run found F12 and F13; fixed.
- *Browser journeys* (`tests/test_clearing_gui_e2e.py`, `-m e2e`): the real
  gateway app (uvicorn, fixture venue, fake engine) behind the production
  build and `serve.ts`, headless Chrome: ADMIN (GAP alarm, both health
  lines, drill-down with 4-decimal marks, reconciliation, EXCHANGE row),
  TRADER (positions, masked counterparty, retention, derived balance, a typed
  ADMIN URL turned away), MARKET_MAKER (obligation settings), unknown key;
  every request same-origin. 4 passed first run; `make test-e2e` 35 passed.
- *Measurements* (`tools/clearing_api_bench.py`, 180 000 trades / 90 days /
  40 gateways / 20 symbols, in-process): polled reads 3–4 ms and ≤10 kB per
  participant (unfiltered ADMIN positions 383 kB / 28 ms, which no screen
  requests); health 52 ms (bench ping timeout); trade page 186 ms → 9.5 ms
  after the F2 index; daily rows 19–45 ms / 585 kB per 1 000; symbols 93 ms;
  reconciliation 0.12 s (7 days) / 1.2 s (90 days), on Run only. Query plans
  for the trade query now `SCAN … USING INDEX ix_trade_events_ts`, no sort.
- *Bundle*: initial load 408 kB (126 kB gzip: React, router, query, Zod);
  Recharts 402 kB only with the history screens; every page its own chunk
  (≤ 8 kB). trader-gui ships 1.26 MB of JavaScript.
- *Docs*: Participant Guide "Clearing GUI" (new), Operator's Guide runbook
  "Clearing GUI" (new: prerequisites, start, ADMIN screens, diagnosis table,
  measured load, non-goals), and every GUI/port enumeration in the
  quick-start, installation, container walkthrough, running-the-exchange,
  AI-traders and development chapters; `web-apps/README.md`, the app's
  README; `make -C docs nav`, `docs-check` clean, `make docs-site` clean.

## 5. Findings

Populate this section only while implementing the workplan. Every confirmed
finding needs an ID, evidence, impact, owning WP, and a test-first disposition.
A finding is closed only when a regression test that previously failed now
passes.

| ID | Found in WP | Observation and evidence | Impact | Classification | Test-first action | Status |
|---|---|---|---|---|---|---|
| F1 | CG1 | `query_trades` ordered by `ts_ns DESC, ingest_ts_ns DESC` has no total order, so a keyset cursor could repeat/skip prints sharing a timestamp (auctions). First fix (`ts_ns, id`) broke the existing CL-L3 test (newest ingest first for equal `ts_ns`). | Duplicate or missing trades across pages. | implementation defect | CL-L3 test failed; key is now `(ts_ns, ingest_ts_ns, id)`; new `test_after_continues_inside_one_timestamp`. | closed |
| F2 | CG1 | The store's optional-filter form (`:gateway IS NULL OR …`) lets SQLite skip the gateway/date indexes on `trade_events`; `ORDER BY ts_ns` has no index. | Trade pages on a large retained table may scan it. Bounded by `limit`, not by cost. | performance constraint | CG9 bench: `SCAN trade_events` + `TEMP B-TREE` on every page (186 ms at 180k trades). `test_a_page_reads_the_sort_index_not_the_whole_table` failed; new `ix_trade_events_ts(ts_ns, ingest_ts_ns, id)` (schema docs regenerated): 9.5 ms. | closed |
| F3 | CG1 | `symbols.open_net_qty` sums signed positions of all gateways; every buy has a seller, so it is identically 0 in this venue. | The design's "current aggregate open quantity" carries no information. | contract ambiguity | Documented as "not open interest; zero while every holder is a gateway" in model and spec; `test_symbols_is_admin_only_activity` pins 0. | closed (documented) |
| F4 | CG2 | The `EOD` session-event payload stores `eod_marks` as ticks without `tick_decimals`. | Exposing them would break the "precision on every money value" rule. | data-quality/observability gap | Not exposed: `eod: {symbols_count, marked_symbols}`; closing marks with precision are in `close-snapshots`. `test_session_events_decode_each_payload`. | closed |
| F5 | CG2 | `query_sessions` filters `from`/`to` on the connect time's **UTC** date (`date(…,'unixepoch')`), while the API's dates are session-timezone trading days. | Wrong rows for a non-UTC venue near midnight. | contract ambiguity | Exact ns bounds from session-timezone midnights; `test_the_connect_day_is_the_session_timezone_day` (Honolulu copy of the fixture) would select nothing under the UTC filter. | closed |
| F6 | CG4 review | `/clearing/summary` (the five-second overview poll) called `query_health`, i.e. `COUNT(*)` and `MAX(ts_ns)` over all of `trade_events`, which has no `ts_ns` index. | Every poll scans the raw-trade table; cost grows with the 90-day retention. | performance constraint | `test_the_polled_summary_never_reads_the_raw_trade_table` (SQL trace) failed; summary now uses `store.query_freshness` over `gateway_symbol_positions` (newest `last_trade_ts_ns`, latest `updated_ts_ns`); `/health` keeps the full facts. | closed |
| F7 | CG4 review | A blank filter (`?gateway=%20`, `?symbol=`) became `""`: a participant got `SCOPE_DENIED … not `, an ADMIN an empty list. | Spurious refusal / false empty result. | implementation defect | `test_a_blank_filter_is_no_filter` failed; blank is now no filter in `clearing_scope` and `_upper`. | closed |
| F8 | CG4 review | `participants/{gateway_id}` built `links` without URL-encoding the gateway id. | A gateway id with `&` or a space yields a wrong link. | implementation defect | `test_participant_links_are_url_encoded` failed; `quote(…, safe='')`. | closed |
| F9 | CG4 review | `query_reconcile` (shared with `pm-clearing-cli reconcile`) compares raw `quantity * price` in each trade's own ticks with daily rows that K6 rescales to the latest precision. | After a symbol's `tick_decimals` changes, its days report false notional discrepancies. Pre-existing; the API now at least returns `tick_decimals` per row. | data-quality/observability gap | Not fixed here (no tick-precision change in 1.0 scope); revisit with K6 if precision changes become an operator action. CG13: K6 converts rather than rejects, so it is reachable; `test_clearing_reconcile_precision.py` failed (4 of 5), raw trades are now converted to the daily row's precision. | closed (CG13) |
| F10 | CG5 | Epoch-nanosecond fields (~1.8e18) exceed JavaScript's safe-integer range: zod 4's `.int()` rejected every real timestamp, and `JSON.parse` rounds them by a few hundred ns. | Every response with a `*_ns` field would have been a contract error in the browser. | contract ambiguity | Contract test failed on the documented examples; `*_ns` are now `nanos` (a plain number), documented as display-only, never compared for equality. | closed |
| F11 | CG5 | FastAPI renders `openapi.json` with `exclude_none`, so example fields whose value is `null` vanish from the published examples (e.g. `/positions`' TSLA row, a participant's masked counterparty), while the wire carries them as `null`. | A client generated from the examples would treat nullable-required fields as optional. | documentation defect | GUI contract test restores the omitted `null`s for nullable fields only (`test/helpers.tsx` `withNulls`) and still checks required-ness against the schema; the published examples themselves are unchanged (all routes, pre-existing). CG11: `test_published_success_examples_keep_their_null_fields` failed on 43 responses; `restore_example_nulls` copies them back; `withNulls` removed. | closed (CG11) |
| F12 | CG9 | axe: the login page had no landmark (its form sat outside `<main>`). | Screen-reader users could not jump to the page's content. | implementation defect | a11y test failed; the page is a `<main>`. | closed |
| F13 | CG9 | axe: the settlement screen had two forms both labelled "Filters" (`landmark-unique`). | Two identical landmarks; a screen reader cannot tell them apart. | implementation defect | a11y test failed; `FilterForm` takes a `label` ("Balance date", "Settlement filters"). | closed |
| F14 | CG5–9 review | Every read used `placeholderData: keepPreviousData`, so changing a gateway filter (Gateway Sessions, EOD account) kept the previous gateway's rows on screen under the new filter until the new reply came. | Brief cross-participant display -- what CG5 says query keys must prevent. | implementation defect | `F14` in `test/review.test.tsx` failed (after F14b); no placeholder data, a new filter shows a skeleton. | closed |
| F14b | CG5–9 review | The test `stubApi` JSON-encoded a handler's promise as `{}` instead of awaiting it, so a "pending" reply was really a contract error and hid the F14 leak. | A test could pass for the wrong reason. | test defect | helper awaits handler results; F14 then failed as it should. | closed |
| F15 | CG5–9 review | Logging out (button or 401) left every cached response of the previous login in the query cache. | Another person at the same tab could be shown, or the memory could hold, the previous participant's data. | implementation defect | `F15` failed; `useClearCacheOnLogout` in App.tsx clears the cache whenever the key goes. | closed |
| F16 | CG5–9 review | A 2xx reply that is not JSON (a proxy serving index.html for /api) threw a raw `SyntaxError`. | An unhelpful error instead of the contract-error explanation. | implementation defect | `F16` failed; `ContractError("the reply is not JSON")`. | closed |
| F17 | CG5–9 review | Run with an unchanged reconciliation range showed the cached result and compared nothing. | An operator re-checking after a fix would see stale results. | implementation defect | `F17` failed; an identical range refetches. | closed |
| F18 | CG5–9 review | The Overview alarm required both `gap_count > 0` and `latest_gap`. | A counted gap without detail would read "no feed gap". | implementation defect | `F18` failed; the alarm keys on `gap_count` alone. | closed |
| F19 | CG5–9 review | The `EXCHANGE` rounding row read "Exchange owes the gateway". | Misleading wording for the residual account. | implementation defect | `F19` failed; its direction is "rounding residual". | closed |
| F20 | CG5–9 review | A value rounding to zero from below showed as "-0.00". | Noise that reads as a loss. | implementation defect | `F20` failed; rounded zero is shown unsigned. | closed |

Classification: **implementation defect**, **contract ambiguity**,
**data-quality/observability gap**, **performance constraint**,
**documentation defect**, or **test defect**.

When a finding expands the release scope, add a new WP to the Status table,
state its dependency, and preserve the original WP's exit criteria. Do not
silently fold unplanned capability such as margin or client accounts into a
clearing-GUI WP.

### 5.1 Holistic review of CG0–CG4 (2026-11-10)

Read end to end after CG4: router, scope resolver, store/ledger query
changes, models, examples and docs. Checked in particular: scope is resolved
from the session before any client-supplied gateway is read, and every
gateway-bearing route goes through it; `EXCHANGE` is filtered in SQL for
non-ADMIN and refused when named; a participant's trades never carry the
counterparty; no response carries a file path or socket address; every
store failure is a 503 (never an empty list) and every empty list is a real
zero; tick and minor units never meet in one schema; every growing list is
bounded with a total order; only `/health` pings the process, `/summary`
reads only aggregate tables. Findings F6–F9 above came out of it; F6–F8
were fixed test-first, F9 is pre-existing and left open.

Limits carried into CG5–CG9: `/health` costs one ≤0.5 s ping per call and
`/reconciliation` a raw-trade scan of its range — neither belongs on a
five-second poll; `/clearing/trades` pages need the F2 query-plan check on a
realistic database (CG9 step 4).

### 5.2 Holistic review of CG5–CG9 (2026-11-11)

Every new and changed file re-read: the web app (API client, schemas, query
policy, shared components, every view and page), the static server, the
Python fixture, e2e test, bench tool and index, the deployment files and the
documentation. Checked in particular: no screen can show one gateway's data
under another's name or login (F14, F15); every failure mode reaches the
user as a named error, never as an empty table (F16); explicit operator
actions really run (F17); unit handling (ticks per row, minor units apart,
no "-0.00", F20) and wording (F18, F19). F14–F20 were fixed test-first;
`test/review.test.tsx` holds them. trader-gui's static server shared the
decode crash fixed in clearing-gui's copy (CG5 notes); fixed there too, with
the same request test in `apps/serve/test/serve.test.ts`.

## 6. Release checklist

Before declaring the client ready for release 1.0, confirm:

- [x] Every Status-table WP is ☑, or any deferred WP is explicitly removed from
  the release scope and all dependent UI routes are absent.
- [x] Every WP began with its stated failing functional test and has focused
  and affected-suite evidence of passing tests. (Exceptions recorded in the WP
  notes: CG4's contract and CG9's request-discipline tests passed at once.)
- [x] The API has no unauthenticated or cross-gateway clearing data leak.
- [x] The GUI never accesses SQLite, the clearing bus, or the clearing health
  socket directly.
- [x] Tick-unit and minor-unit values are never mixed or aggregated without
  their declared conversion.
- [x] GAP, clearing flush lag, retention, observation timestamps, and EOD
  settlement limitations are visible to relevant users.
- [x] No shipped label or calculation claims margin, client account, collateral,
  intraday P&L history, open interest, or MM compliance without a new
  authoritative implementation and corresponding WP.
- [x] Deployment, API, and user documentation were verified against running
  route schemas and browser journeys.

## 7. Suggested follow-up work packages

Proposed 2026-11-11 from findings F1–F20. Two findings are still open (F9,
F11). The fixed implementation defects were then checked for the same
defect class elsewhere. Each class was looked for in code, not assumed; every
WP still starts with the failing test that proves the defect before it is
fixed. Nothing here is release-1.0 scope for the clearing GUI itself.

**Priority** is by potential impact:

- **P1 — High:** one participant's data could be shown to another, or
  positions or money could be shown wrong.
- **P2 — Medium:** wrong or misleading results under specific but reachable
  conditions, or a published contract that misleads client authors.
- **P3 — Low:** diagnostics quality, cosmetic output, accessibility hardening.

Checked and **not** found elsewhere (no WP):

- F1 class: every keyset cursor in `stats/query.py` has a total order
  (`seq`, `rowid` or `symbol` tie-breaker).
- F8 class: no other router builds links from ids.
- F14 class: no other GUI uses `keepPreviousData` / `placeholderData`.

| # | WP | Prio | From | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|---|
| 10 | CG10 | P1 | F15 (F14) | trader-gui: per-login query cache — no cached response survives a logout | — | 0.5 d | ☑ | 2026-11-11 |
| 11 | CG11 | P2 | F11 | Published OpenAPI examples keep `null` fields | — | 1 d | ☑ | 2026-11-11 |
| 12 | CG12 | P2 | F5 | `pm-clearing-cli sessions`: session-timezone days, not UTC dates | — | 0.5 d | ☑ | 2026-11-11 |
| 13 | CG13 | P2 | F9 | Reconciliation correct across a `tick_decimals` change | K6 decision | 1 d | ☑ | 2026-11-11 |
| 14 | CG14 | P3 | F16 | Non-JSON success replies named in every GUI API client | — | 0.5 d | ☐ | |
| 15 | CG15 | P3 | F7 | Blank (whitespace) filters are no filter on the history routes | — | 0.25 d | ☐ | |
| 16 | CG16 | P3 | F20 | trader-gui: no "-0.00" for values that round to zero | — | 0.25 d | ☑ | 2026-11-11 |
| 17 | CG17 | P3 | F12, F13 | axe accessibility checks for trader-gui | — | 1 d | ☐ | |

Suggested order: CG10 first (the only P1), then CG11–CG13, then the P3s in
any order.

### CG10 — trader-gui: per-login query cache (P1)

- **Defect class:** F15 (cache survives logout), with F14 (rows shown under
  the wrong identity).
- **Evidence:** caller-specific queries in
  `web-apps/trader-gui/apps/web/src/queries/index.ts` have keys without the
  caller: `["positions"]` (fresh for 30 s), `["history/fills", params]`,
  `["quotes/bootstrap"]`, `["quotes/legs"]`, `["history/daily", …]`.
  `logout()` (`store/useAuthStore.ts`) clears no query cache. Only the order
  store is cleared (`hooks/useOrderStream.ts`).
- **Impact:** if a user logs out and another logs in on the same tab within
  the stale time, the second user's position panel can show the first
  user's positions as fresh data, with no refetch. On shared classroom
  machines this is reachable.
- **First failing test:** log in as gateway A with positions, log out, log in
  as B, and assert A's rows never render.
- **Fix:** the clearing-gui pattern — clear the query cache whenever the key
  goes (`useClearCacheOnLogout` in clearing-gui `App.tsx`). log-gui and
  terminal-gui also use TanStack Query; check them for the same pattern and
  fix only where it is present.
- **Exit:** the test passes, and the trader-gui suite and typecheck are green.
- **Done 2026-11-11.** `test/logoutCache.test.tsx` renders the real `App`
  (only the WebSocket manager and the HTTP transport are stubbed): A's
  positions, Logout, B logs in, opens Positions. It failed with A's AAPL row
  shown to B. Fix: `hooks/useClearCacheOnLogout.ts`, mounted in `App.tsx`,
  clears the query cache whenever the key goes (button, 401, dead WS key all
  go through `logout()`). log-gui and terminal-gui have no login, so no
  per-caller cache: the pattern is not present there. trader-gui: 554 tests,
  typecheck green.

### CG11 — Published OpenAPI examples keep `null` fields (P2)

- **Finding:** F11 (open). FastAPI renders `spec/rest/openapi.json` with
  `exclude_none`, so example fields whose value is `null` are missing,
  although the wire carries them.
- **Impact:** bot authors writing clients from the published contract may
  treat nullable required fields as optional. This affects all routes, not
  only clearing.
- **First failing test:** a Python contract test that every example
  validates against its response schema with all required fields present.
- **Fix:** render examples without `exclude_none`. Find the mechanism in
  FastAPI first; do not guess. Then run `make openapi`, and remove the
  `withNulls` workaround from clearing-gui's `test/helpers.tsx`.
- **Exit:** the test passes, the contract snapshot is regenerated, and the
  GUI contract test passes without `withNulls`.
- **Done 2026-11-11.** Mechanism: `fastapi.openapi.utils.get_openapi` ends
  with `jsonable_encoder(OpenAPI(**output), by_alias=True, exclude_none=True)`
  (FastAPI 0.162), which strips `None` recursively, inside example values
  too. Rendering the whole document without `exclude_none` would add `null`
  for every unset OpenAPI field, so only the examples are restored:
  `openapi_docs.restore_example_nulls` (called from `main.py`'s `openapi()`
  after `drop_stock_validation_error`) copies every response's `example` /
  `examples` from the route's own `responses=`. Note FastAPI 0.162 nests
  included routers (`_IncludedRouter`), so routes are walked with
  `fastapi.routing.iter_route_contexts`, as `get_openapi` does. First failing
  test: `test_published_success_examples_keep_their_null_fields` (published
  2xx example validates against the response model and equals the route's
  own) — 43 responses lost fields, e.g. `AmendAccepted`, `OrderList`.
  `make openapi`: +240 lines, only `null` fields. clearing-gui: `withNulls`
  removed, 162 tests and typecheck green. Not covered: request-body
  `examples` in component schemas (`json_schema_extra`) would lose `null`s
  the same way; none has one today.

### CG12 — `pm-clearing-cli sessions`: session-timezone days (P2)

- **Defect class:** F5. It was fixed only in the API, which passes exact ns
  bounds.
- **Evidence:** `clearing/store.py` `query_sessions` still filters
  `from_date`/`to_date` on the connect time's UTC date. `clearing/cli.py`
  (`sessions`) passes those, and the `connect_date` column is the UTC date.
- **Impact:** for a non-UTC venue, connections near midnight land on the
  wrong day in the CLI.
- **First failing test:** the Honolulu fixture case from
  `test_the_connect_day_is_the_session_timezone_day`, run through the CLI.
- **Fix:** the CLI resolves trading days to ns bounds in the session
  timezone, as the API does. Remove the UTC-date parameters (no backwards
  compatibility).
- **Exit:** the CLI and API select the same rows; operator-guide CLI text
  checked.
- **Done 2026-11-11.** `test_the_cli_selects_the_same_connect_days_as_the_api`
  (in `test_api_gateway_clearing_evidence.py`, Honolulu copy of the fixture,
  both cases) failed: the CLI listed 3 sessions where the API listed none.
  Fix: one helper, `clearing.query.day_bounds_ns` (session-timezone
  midnights, upper bound exclusive), used by the API and the CLI; the API's
  private `_day_start_ns` is gone. `store.query_sessions` lost
  `from_date`/`to_date` and its UTC `connect_date` column; the CLI now fills
  `connect_date` as the connect's session-timezone day. `--from`/`--to` help,
  shell completion and the participant guide's CLI table updated (the
  operator guide only links there).

### CG13 — Reconciliation across a `tick_decimals` change (P2)

- **Finding:** F9 (open, predates this plan).
- **Evidence:** `query_reconcile` compares raw `quantity * price` in each
  trade's own ticks with daily rows that K6 rescales to the latest precision.
- **Impact:** false notional discrepancies for every retained day before a
  precision change, in the CLI, the API and the GUI's Reconciliation screen.
  An operator may chase errors that do not exist. Reachable only when a
  symbol's `tick_decimals` is changed between sessions.
- **First step:** decide with the K6 owner whether a precision change is a
  supported operator action. If it is not, record that and close F9 as
  "not reachable".
- **First failing test:** trades at 2 decimals, a change to 4, then
  reconcile; assert no discrepancy.
- **Fix:** rescale each raw trade to the daily row's precision before
  comparing.
- **Exit:** the test passes, and `pm-clearing-cli reconcile` agrees with the
  API.
- **Done 2026-11-11.** Decision: K6 already settled it — a precision change
  is *converted*, not rejected ("conversion is preferred as it keeps the
  venue running", K6 step 3), so it is a supported path and F9 is reachable.
  Narrower than F9 said: the upsert converts a stored daily row only when a
  trade at the new precision lands on the *same* trading day, so only the day
  of the change was wrong, not every earlier day. `test_clearing_reconcile_precision.py`
  writes the ledger through `ClearingProcess` (AAPL 2→4 and MSFT 4→2 decimals
  within one day, one flush per trade); store, CLI and API failed. Fix in
  `query_reconcile`: raw trades are summed per precision and each sum is
  converted to the daily row's precision (rounded once, as the upsert does;
  a key without a daily row uses its finest precision); a real loss is still
  reported, in the row's precision. Limit: a precision *decrease* of values
  the coarser precision cannot represent rounds the daily row, and when old
  trades were split across a flush and a pending batch the two roundings can
  differ from one by a tick — reported as a discrepancy.

### CG14 — Non-JSON success replies in every GUI API client (P3)

- **Defect class:** F16.
- **Evidence:** a bare `res.json()` on 2xx in
  `trader-gui/apps/web/src/api/apiFetch.ts`,
  `config-gui/apps/web/src/api/client.ts`, `log-gui/apps/web/src/lib/api.ts`,
  `terminal-gui/apps/web/src/lib/api.ts` and
  `dash-gui/apps/web/src/lib/api.ts`.
- **Impact:** a misrouted proxy that serves `index.html` for `/api` surfaces
  as a raw `SyntaxError` instead of a named error.
- **First failing test:** in each GUI, a 200 `text/html` reply; assert the
  error names it.
- **Fix:** catch the parse error and throw that client's own error type with
  "the reply is not JSON".
- **Exit:** each GUI's suite is green.

### CG15 — Blank filters on the history routes (P3)

- **Defect class:** F7.
- **Evidence:** `api_gateway/routers/history.py` uses
  `symbol.upper() if symbol else None` (and the same for `index_id`):
  `?symbol=%20` stays a filter on `" "`.
- **Impact:** a false empty list instead of the unfiltered result.
- **First failing test:** `?symbol=%20` returns the same rows as no filter.
- **Fix:** strip, then treat empty as no filter, as `clearing_scope` does.
  Sweep the other routers with the same test.
- **Exit:** the test passes and `make openapi` is unchanged.

### CG16 — trader-gui "-0.00" (P3)

- **Defect class:** F20.
- **Evidence:** `trader-gui/apps/web/src/lib/formatters.ts` `formatPrice`
  and `formatSignedPrice` use `toFixed`, and `(-0.001).toFixed(2)` is
  `"-0.00"`.
- **Impact:** a P&L that rounds to zero reads as a loss.
- **First failing test:** both functions with `-0.001` at 2 decimals give
  `"0.00"`.
- **Fix:** the rounded-zero check in clearing-gui's `lib/money.ts` `fixed`.
- **Exit:** the trader-gui suite is green.
- **Done 2026-11-11.** Tests in `formatters.test.ts` (`-0.001`, `-0` for
  both, `+0.001` for the signed one) failed with "-0.00"; a private `fixed`
  in `formatters.ts` shows a rounded zero unsigned, and `formatSignedPrice`
  signs on the rounded text. Sibling `formatChangePct` ("-0.00%") was outside
  the WP: For-Later ToDo L002.

### CG17 — axe checks for trader-gui (P3)

- **Defect class:** F12, F13. Only clearing-gui has axe tests; both its
  defects were found only by running axe.
- **Scope:** trader-gui's login page and main trading screens (the
  participant-facing GUI), using the same `axe-core` + jsdom setup as
  clearing-gui's `test/a11y.test.tsx`.
- **First failing test:** whatever axe reports. Each violation found
  becomes a finding here and is fixed test-first.
- **Exit:** no axe violations on the covered screens.

## 8. Usability round (2026-11-26)

The list of clearing-gui improvements (paging, header tooltips, sorting,
a drawer for the participant detail, searchable filters, a better Overview),
assessed against the code and extended where the same problem shows up on
screens the list did not name. Client-side only: every WP uses endpoints that
exist today. No backwards compatibility: replaced components and routes are
removed, not kept beside the new ones.

### 8.1 Findings from the assessment

- **Sorting already exists, but is invisible.** Every `DataTable` column with
  a `sortValue` sorts on a header click, which is almost all of them, but only
  the active column shows an arrow. Unsorted headers look like plain text.
- **Tooltips are optional, so most are missing.** `Column.title` exists, but
  about two thirds of the columns have none. `Stat` has no tooltip at all.
- **No paging.** Every list endpoint returns up to 1 000 rows plus `has_more`
  (`MoreRows`), so client-side paging over the fetched rows is cheap. The
  exception is Trades: a 200-row server cursor with "Load more", where a
  header sort only orders the rows loaded so far, which is misleading.
- **Times are UTC everywhere** (`lib/time.ts`), with the comment "the GUI is
  not told the venue's session timezone". It can be: `GET /api/v1/session`
  carries `session_timezone`. terminal-gui, dash-gui and log-gui already show
  the session zone. EOD runs' "Finished (UTC)" is a raw string column.
- **The participant detail is a page**; every other GUI drills down in a
  right-hand drawer. It has 5 sub-tabs, tables of 12 columns and a chart, so
  dash-gui's 44 rem drawer is too narrow for it.
- **Positions and Exposure repeat 5 columns** (symbol, net qty, mark,
  realized, unrealized) as two tables on one tab.
- **Free-text Gateway/Symbol/Account filters** on Reconciliation, Trades,
  History, Gateway Sessions and EOD: a typo gives an empty table that looks
  like "no data".
- **The Overview's Participants table** is the Participants screen again.
- **Gateway ids elsewhere are dead text:** Trades buyer/seller,
  Reconciliation, Gateway Sessions, EOD account.

### 8.2 Decisions 

| # | Question | Decision |
|---|---|---|
| D1 | Which clock? | The venue session timezone, on every timestamp: date + time + zone abbreviation. Not browser-local, no toggle. |
| D2 | Trades paging | The pager follows the server's newest-first order and fetches the next server page when Next needs it. Header sorting is switched off on these tables; the order is stated above them. |
| D3 | Participant detail | A wide drawer (about 90% of the main area). The URL stays `/participants/:gatewayId[/tab]`, so deep links and browser Back work; Escape and × close it. This replaces the "Back" button idea. |
| D4 | Overview content | Remove the Participants table. Add *Needs attention*, *Phase + staleness* and *EOD/settlement lag*. |
| D5 | Positions vs Exposure | Merge into one Positions table (also on My Positions). |
| D6 | Page sizes | 10 / 30 / 50 / 100 / All, as dash-gui's `TablePager`; one remembered choice for all tables. |

"Sorts loaded rows only" (D2's other option) was rejected in favour of
switching the sort off: a half-sort that looks like a full one is the defect
being removed.

### 8.3 Work packages

Suggested order is the table order: CG18 is the foundation the others use.

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 18 | CG18 | Shared table: pager, sort affordance, required tooltips; `Stat` tooltip | — | 1 d | ☑ | 2026-11-26 |
| 19 | CG19 | Venue session timezone on every timestamp | — | 0.5 d | ☑ | 2026-11-26 |
| 20 | CG20 | Every table: tooltip texts, paging; Trades pager; Positions + Exposure merged | CG18 | 1.5 d | ☑ | 2026-11-26 |
| 21 | CG21 | Participant detail in a wide drawer; row click; gateway ids open it | CG18 | 1.5 d | ☑ | 2026-11-26 |
| 22 | CG22 | Searchable Gateway / Symbol / Account filters | — | 1 d | ☑ | 2026-11-26 |
| 23 | CG23 | New Overview: needs attention, phase + staleness, EOD lag | CG18, CG19, CG21 | 1 d | ☑ | 2026-11-26 |
| 24 | CG24 | Help drawer and the operator/participant guide chapters | CG18–CG23 | 0.5 d | ☑ | 2026-11-26 |

Every WP is test-first in clearing-gui's vitest suite
(`web-apps/clearing-gui/apps/web/test/`) and exits with the suite, the
typecheck and `a11y.test.tsx` green.

### CG18 — Shared table: pager, sort affordance, required tooltips

- **Goal:** one `DataTable` that every table gets the new behaviour from, so
  CG20 is mostly data (texts) rather than code.
- **Pager:** port dash-gui's `TablePager` + `pagination()` into
  `components/shared/`, with `PAGE_SIZES = [10, 30, 50, 100, 0]` (0 = All).
  The page size is one persisted preference (a small zustand store with
  `persist`, as `useFontSizeStore`; storage failures fall back to the
  default). Default 30. The page index is per table: it is clamped, not
  reset, when the 5 s poll changes the row count, and goes back to the first
  page when the sort or the rows' filter changes. No pager is drawn when the
  rows fit the smallest page (10); not "when they fit on one page", because
  with "All" chosen every table fits one page and the choice could no
  longer be undone.
- **Sort affordance:** every sortable header shows a faint ↕ icon, and the
  active one ↑/↓ as today. A column without `sortValue` shows none.
  `DataTable` gets a `sortable={false}` switch for the Trades tables (D2).
- **Tooltips:** a new optional `Stat.title`. Headers and tiles with a
  tooltip get a dotted underline. CG20 then makes `Column.title` and
  `Stat.title` required, so the compiler lists any it missed.
  The tooltip stays the native `title`, as in the other GUIs; the full text is
  also the header's accessible description.
- **Pagination row:** "Rows 31–60 of 214" left, `TablePager` right; with
  `has_more`, the existing `MoreRows` note stays under it ("of the first
  1 000").
- **First failing tests:** a 25-row table at page size 10 shows 3 pages and
  rows 11–20 on page 2; a poll that drops rows below page 3 clamps to the last
  page; a new sort returns to page 1; the size choice survives a remount;
  every sortable header has the sort icon.
- **Exit:** tests green; every existing table shows the pager and the sort
  icons with no screen code changed.
- **Done 2026-11-26.** `test/dataTable.test.tsx` (13 tests) failed first
  (no page-size store, no pager). New: `store/usePageSizeStore.ts`
  (`PAGE_SIZES`, `DEFAULT_PAGE_SIZE = 30`, localStorage key
  `clearing-page-size`) and `components/shared/TablePager.tsx` (dash-gui's
  pager plus "Rows a–b of n", in a `nav` named "<caption> pages" so two
  tables on one screen have distinct landmarks). `DataTable`: paging,
  `SortIcon` (faint ↕ on unsorted sortable headers, ↑/↓ on the active one),
  `sortable={false}`, dotted underline on headers with a `title`. `Stat`:
  optional `title` on its label. A filter change needs no code: a new filter
  is a new query key, `QueryState` shows the skeleton, and the table remounts
  on page 1 — the Events screen test proves it. Until CG20, the Trades tables
  page their loaded rows and still have "Load more" under the pager. Suite
  177 tests (was 164), typecheck and production build green; axe unchanged.

### CG19 — Venue session timezone on every timestamp

- **Goal (D1):** every time reads e.g. `2026-11-26 09:00:01 CET`.
- **Source:** `GET /api/v1/session` once after login (`staleTime: Infinity`),
  `session_timezone` into the formatters. The endpoint asks the engine and can
  time out; until it answers, or when it fails, times stay in UTC and keep
  their "UTC" label, so a time is never shown in an unnamed zone.
- **Code:** `lib/time.ts` `formatNs`/`formatClock` take the zone
  (`Intl.DateTimeFormat` with `timeZone`, `timeZoneName: "short"`);
  `formatClock` is replaced by `formatNs` wherever a date is missing today
  (the Overview line, `FreshnessNote`). EOD runs' `finished_at` (ISO string)
  is parsed and shown the same way; the header loses "(UTC)". Update the
  module comment.
- **First failing tests:** with `Europe/Stockholm`, a winter and a summer ns
  value format with CET / CEST and the right date across midnight UTC; a
  failed `/session` gives the UTC form; the Overview freshness line contains
  a date.
- **Exit:** no `UTC` literal left outside the fallback.
- **Done 2026-11-26.** `test/time.test.ts` (7) and `test/timeZone.test.tsx`
  (5) failed first. `lib/time.ts` is now `formatNs(ns, zone)` and
  `formatIso(iso, zone)`; `formatClock` is gone (every time has its date).
  The zone name comes from en-GB, or from en-US when en-GB gives only an
  offset: CET/CEST, EDT, HST — and "GMT+9" for Tokyo, which has no
  abbreviation in either locale. An unknown zone falls back to labelled UTC.
  The zone flows `GET /api/v1/session` → `useVenueTimeZone` (in a new
  `SignedInShell` inside `AppShell`, so it is asked for only when signed in,
  once per login) → `useVenueTimeZoneStore` → `<Time>` / `useFormatNs`
  (`components/shared/Time.tsx`), which re-render when the zone arrives.
  `SessionInfo` schema added to `ROUTE_SCHEMAS`, so the contract test holds it
  to the published `Session` model; CG23 reads its `state`. The EOD runs
  column is "Finished" and sorts by instant. `eod.test.tsx`'s Obligations
  test now leaves out the shell's session request when checking that the page
  reads only `/symbols`. Existing tests without a `/session` stub keep their
  UTC assertions, which is the fallback working. Suite 191 (was 177),
  typecheck and build green.

### CG20 — Every table: tooltip texts, paging, Trades pager, merged Positions

- **Tables covered:** Participants; Symbols; Events; Gateway Sessions;
  Reconciliation; EOD derived balances, settlements and EOD runs; the
  participant views (Positions, Trades, History's three tables, Settlement,
  Sessions), which the participant's own "My …" pages share; MM Quote
  Obligations; Overview's recent events (plus an "All events →" link to
  Events).
- **Tooltip texts:** one sentence each, saying what the value is and where it
  comes from, in the vocabulary of the participant guide's clearing chapter
  (e.g. "Mark — last trade price, or the end-of-day mark when the session is
  closed"). `Stat` tiles likewise, on the Overview and the participant
  totals.
- **Merged Positions (D5):** one table — Symbol, Net qty, Avg cost, Mark,
  Net notional, Gross notional, Realized, Unrealized, Total P&L, Bought,
  Sold, Bought value, Sold value, Last trade, Updated — joined on
  gateway/symbol from `/positions` and `/exposure`. The Exposure panel and its
  columns are removed. If the two replies disagree on the key set (they are
  separate polls), a row missing from `/exposure` shows dashes in the
  notional columns, never another row's values.
- **Trades (D2):** `useTrades` keeps its cursor. The pager's "All" means
  "everything loaded"; Next past the loaded rows calls `fetchNextPage` and
  shows the page when it arrives; the last page is known only when the cursor
  ends, so the count reads "Rows 401–430 of 430+" until then. `sortable={false}`
  and the text "Newest first, as the exchange printed them" above the table.
  "Load more" is removed.
- **First failing tests:** a table-driven test that renders each screen with
  fixture rows and asserts every `th` has a non-empty title; the merged
  Positions table with an exposure row missing; Trades Next past 200 loaded
  rows triggers the second request and shows row 201.
- **Exit:** `Column.title` and `Stat.title` are required and the build is
  green.
- **Done 2026-11-26.** First failing: `test/tooltips.test.tsx` (17 screens
  plus a Reconciliation run: every `columnheader` and `[data-stat-label]`
  has a non-empty title), the merged-Positions and Trades-pager tests in
  `myClearing.test.tsx`, and the "All events →" link in `admin.test.tsx`.
  `Column.title` and `Stat.title` are required; the column builders take the
  title as a required argument; texts follow the published contract's field
  descriptions.
  **Deviation (merged Positions):** not joined with `/exposure`. The API's
  exposure query is pure arithmetic on the same ledger row
  (`store.query_exposure`: `net_qty * mark_price`, `ABS(...)`,
  `realized + unrealized`), so the table derives net/gross notional and total
  P&L from each position row in its own ticks (`netNotional` in
  `PositionsView.tsx`). Same numbers, no two polls to line up, one 5 s
  request fewer; the "row missing from `/exposure`" case cannot arise. No
  mark → dashes, not zeros (tested). `useExposure` and its test stubs are
  removed; the `Exposure` schema stays for the contract test.
  **Trades:** `DataTable` takes `more: {available, loading, load}`; Next past
  the loaded rows sets the requested page, an effect keyed on that need calls
  `fetchNextPage` once, and the page shows when it lands (the CG18 clamp holds
  the view on the last loaded page meanwhile). Counts read "Rows 1–100 of
  200+", "Page 1/2+"; Next is off while loading. `sortable={false}`, the order
  is stated above the table, "Load more" is gone.
  Also: the Overview's custom "Last EOD run" tile got its tooltip; the help
  drawer's "positions and exposure" now says "positions at their marks".
  Suite 213 (was 191), typecheck and build green.

### CG21 — Participant detail in a wide drawer

- **Goal (D3):** the Participants list stays visible and live behind the
  detail; the detail is reachable by URL.
- **Routing:** `/participants/:gatewayId/*` renders `ParticipantsPage` with
  the drawer open over it, instead of a separate page.
  `ParticipantDetailPage` becomes `ParticipantDrawer`; its sub-tab routes are
  unchanged. Closing navigates to `/participants`.
- **Drawer:** the dash-gui `Drawer` pattern (non-modal `aside`, focus to the
  title on open, Escape and × close), positioned in the main area under the
  top bar, width `min(90%, 110rem)`. Header: "Participant", the gateway id,
  the six totals tiles, then the sub-tabs. Body scrolls; wide tables scroll
  horizontally inside it.
- **List:** the whole row is clickable and keyboard-reachable (Enter/Space on
  a focusable row, `aria-selected` on the open one, a visible highlight). A
  hint above the table: "Select a participant to open its positions, trades,
  history, settlement and sessions." The gateway cell is no longer a link.
- **Gateway ids elsewhere:** Trades buyer/seller, Reconciliation, Gateway
  Sessions and EOD account (not `EXCHANGE`) render as links to
  `/participants/:gatewayId`, so they open the drawer over the Participants
  screen. Only for ADMIN; on the "My …" pages they stay text.
- **First failing tests:** clicking a row (and Enter on it) opens the drawer
  with that gateway's title and the URL `/participants/GW1`; Escape returns
  to `/participants` with focus on that row; a deep link to
  `/participants/GW1/trades` shows the list and the drawer on Trades; a
  Reconciliation gateway cell links to the drawer; axe has no violations with
  the drawer open.
- **Exit:** `routing.test.tsx` and `admin.test.tsx` updated; no route renders
  the old page.
- **Done 2026-11-26.** `test/participantDrawer.test.tsx` (13) failed first.
  `components/shared/Drawer.tsx` (dash-gui's pattern) is portalled into a
  drawer layer that `AppShell` now has beside the scrolling `main`, so the
  drawer sits under the top bar and does not scroll with the page;
  `w-[90%] max-w-[110rem]`. `ParticipantDetailPage` became
  `components/views/ParticipantDrawer.tsx` (git mv); both participant routes
  render `ParticipantsPage`, which draws the list and, with `:gatewayId`, the
  drawer. `DataTable` got `onRowClick`/`selectedKey` (`tabIndex=0`,
  Enter/Space, `aria-selected`, highlight, `data-row-key`); closing returns
  focus to the row via `data-row-key` (only if that row is on the shown
  page). `GatewayId`/`gatewayColumn` link ids for ADMIN only, never
  `EXCHANGE`: Trades buyer/seller, Reconciliation, Gateway Sessions, EOD
  settlement and balance accounts.
  **Found and fixed:** the shell's error boundary was keyed by the full path,
  so opening or closing a drawer remounted the list (losing sort and page).
  It is now keyed by screen (`screenKey`: every `/participants/...` is one
  screen); a test proves the sort survives, and fails with the old key.
  **Axe:** `role="dialog"` is not allowed on `aside`, and a `header` in the
  drawer is a second banner; both are `div`s (dash-gui's drawer has the same
  two, but dash-gui runs no axe on it). `aria-selected` on table rows passes.
  The drawer heading reads "Participant TRADER01" (kind as a small label), so
  the dialog's name and the existing heading-based tests are unchanged.
  Suite 226 (was 213), typecheck and build green.

### CG22 — Searchable Gateway / Symbol / Account filters

- **Goal:** pick a value from a searchable list instead of typing one blind.
- **Control:** a `combobox` field type in `Filters.tsx` (an input with a
  filtered listbox, keyboard up/down/Enter/Escape, ARIA combobox pattern).
  Empty means All. A typed value not in the list is still accepted: gateways
  that connected but never traded are not in the participants list, and an
  operator may know an id the GUI has not seen.
- **Options:** gateways from `/clearing/participants`; symbols from
  `/api/v1/symbols` (already fetched, `staleTime: Infinity`); EOD accounts from
  the balances reply, including `EXCHANGE`.
- **Screens:** Reconciliation (Gateway, Symbol), Trades and History (Symbol),
  Gateway Sessions (Gateway), EOD Settlement (Account).
- **First failing tests:** typing "aa" lists AAPL and Enter selects it; an
  unlisted value still filters; Escape closes the list without clearing it;
  axe has no violations.
- **Exit:** no free-text gateway/symbol/account field left.
- **Done 2026-11-26.** `test/filterCombobox.test.tsx` (10) failed first.
  `components/shared/Combobox.tsx` (ARIA 1.2 combobox, list autocomplete;
  pick on mousedown so it lands before blur; Escape closes and stops there,
  so it does not also close a drawer) is the `combobox` field type of
  `FilterForm`, with `suggestions`. **Deviation (symbol source):**
  `/api/v1/symbols` requires a trading key (`require_trading`), so ADMIN could
  not read it; symbols come from `GET /api/v1/reference/symbols` (any key)
  instead, whose `ReferenceSymbolList` schema is declared in full and added to
  `ROUTE_SCHEMAS`, so the contract test holds it. Lists are fetched once and
  not polled: `useSymbolOptions` (`staleTime: Infinity`), `useGatewayOptions`
  and `useAccountOptions` (cached 60 s, `enabled` only where the filter
  exists, so a participant's Sessions/Settlement pages ask for neither); a
  test holds `/participants` to one request over 30 s on Gateway Sessions.
  A participant's Symbol list is every venue symbol, not only those it
  traded. Suite 238 (was 226), typecheck and build green; axe clean with a
  list open.

### CG23 — New Overview

- **Goal (D4):** the Overview answers "is anything wrong right now?"; lists
  live on their own screens.
- **Removed:** the Participants panel (the Reconciliation link moves to the
  page header).
- **Needs attention:** two small tables side by side. *Largest losses*: the
  5 participants with the lowest total P&L below zero (from
  `/clearing/participants`, already polled). *Largest positions*: the 5
  gateway/symbol rows with the highest gross notional (from `/positions`
  without a gateway, the ADMIN venue scope, with CG20's `netNotional`; or
  `/exposure?sort=gross_notional` — decide in the WP, whichever needs no
  1 000-row cap caveat). Gross notional is per symbol in that
  symbol's own precision and converted to display currency before ranking,
  as `tickColumn` sorts; no cross-symbol sum. Rows open the CG21 drawer.
  Empty states: "No participant is at a loss" / "No open positions".
- **Phase + staleness:** a tile with the phase from `GET /api/v1/session`
  (shared with CG19, but refreshed at the 30 s health cadence). A warning
  banner when the phase is not CLOSED and the last clearing write is older
  than a stated threshold. Threshold: 30 s (six 5 s flushes), a constant in
  the code and in the help text; with no trading, no write is expected, so the
  warning names the age and says "no trade has arrived, or clearing is not
  writing" rather than claiming a fault.
- **EOD/settlement lag:** a warning when the last EOD run is not `ok`, or when
  the last settled day is before the latest trading day that has trades and
  the session is CLOSED for that day. Uses `/summary` (`last_eod_run`,
  `session_date`) and `/eod/balances` (`last_settled_date`), which already
  exist. While the market is open, today not being settled is normal and not
  shown as lag.
- **First failing tests:** with fixture data: 7 participants, 3 at a loss →
  exactly those 3 listed, worst first; phase CONTINUOUS and a 60 s old write →
  the staleness banner; phase CLOSED and an old write → no banner; last EOD
  run `failed` → the EOD warning; last settled day yesterday and today's
  session closed with trades → the lag warning.
- **Exit:** no element on the Overview duplicates a whole other screen.
- **Done 2026-11-26.** `test/overview.test.tsx` (14) failed first. Rules are
  plain functions in `pages/admin/overviewChecks.ts`
  (`staleWriteSeconds`, `eodProblem`, `largestLosses`); the panel is
  `components/views/NeedsAttention.tsx`. Decisions taken in the WP:
  - **Largest positions source:** `GET /exposure?limit=5&sort=gross_notional`
    (the server's default sort). `store._EXPOSURE_SORT` ranks by display
    currency (`/ {_CCY}`), so mixed precisions order correctly and the
    reply is five rows: no 1 000-row ranking in the browser, no cap caveat.
    Flat rows (net 0) are dropped. `useLargestPositions` polls at 5 s.
  - **Staleness only in CONTINUOUS,** not "any phase but CLOSED": clearing
    writes on fills, and PRE_OPEN and the auction phases fill only at the
    uncross, so a warning there would fire every day. Threshold
    `STALE_WRITE_MS` = 30 s; the text names both causes (no trade, or
    clearing not writing).
  - **EOD lag from the summary alone:** `last_eod_run` (status, trade_date)
    and `session_date`, no `/balances` request. Warns when the last run is
    not `ok`, or when the phase is CLOSED and the last run is for an earlier
    day than `session_date`. Known gap: once the next day opens, a skipped
    previous day is no longer flagged (only the failed-run rule still
    shows); catching it would need the previous trading day, which nothing
    the GUI reads gives. No warning when the EOD ledger is unavailable (the
    EOD tile already says so).
  - **Phase tile** from `useSession` (same `/session` key as the shell's
    timezone read, polled at 30 s while the Overview is shown); "unknown /
    the engine did not answer" when it fails, and then no staleness warning.
  Old tests updated on purpose: the Overview-Participants row test removed
  (covered by the new tests); two tests waited on that table; the
  "no notional" rule now exempts the Largest positions table (one
  position's own size, its tooltip says "not a venue total"); `requests`
  allows `/exposure` and `/session` as polled; the timezone-once test moved
  to screens that do not show the phase; the axe stub gained `/exposure`.
  Suite 251 (was 238), typecheck and build green.

### CG24 — Help and guides

- **Scope:** `components/help/helpContent.ts`;
  `docs/books/operator-guide/part-6-observe-and-recover/080-clearing-gui.md`
  and `docs/books/participant-guide/part-6-front-ends/040-clearing-gui.md`;
  the design doc `docs-design/EduMatcher-Clearing-GUI.md` where it describes
  the screens: the drawer,
  the pager, the venue timezone, the merged Positions table, the new
  Overview and its thresholds. Screenshots retaken where the layout changed.
- **Check:** every statement verified against the running GUI on a live sim,
  as the 2026-11-19 guide reviews did.
- **Exit:** `mkdocs build` clean; no text says "UTC", "Exposure table" or
  "Load more" for the clearing GUI.
- **Done 2026-11-26.** Operator chapter: routes (`/session`,
  `/reference/symbols`), what-must-run rows (timezone/phase, symbol lists),
  the new Overview (phase, stale-write and EOD warnings with their limits,
  Needs attention), the Participants drawer and gateway-id links, a new
  "Working with the tables" section, four diagnosis rows, and the load
  section (no per-gateway exposure poll; Overview phase at 30 s; timezone and
  filter lists once). Participant chapter: merged My Positions, the Trades
  pager, a new "Working with the tables" section with times. Help drawer:
  new topics Tables and filters, Times, Overview warnings; ADMIN role line
  mentions the drawer. Design doc §7.1–7.3 and §8 brought in line. No
  screenshots exist in either chapter, so none to retake. "UTC" remains only
  where the fallback is described, which is intended. `mkdocs build` clean;
  suite 251, typecheck green.
  **Not done:** the live-sim check of every statement. The texts were checked
  against the code and the tests, not against a running GUI; do that on the
  next sim run (drawer under the top bar at each font size, the staleness
  warning in a quiet continuous session, the EOD-lag warning after the
  close).

### 8.4 Holistic review of CG18–CG24 (2026-11-26)

The committed range `2d51ef61..3c00c483` (49 files) was read as a whole,
looking for interactions between the WPs and for cases each WP's own tests
did not reach. Four defects were found; each got a failing test first and is
fixed. Suite 255 (was 251), typecheck, build and `mkdocs build` green.

| # | Sev | Finding | Fix |
|---|---|---|---|
| R1 | High | **The stale-write warning (CG23) could not appear in the case it exists for.** It computed `Date.now() − last_flush_ts_ns` during render, but a poll that returns the same summary does not re-render the page (TanStack Query v5 re-renders only on changed, tracked fields), and "the same summary" *is* the stale case. CG23's test loaded data that was already 60 s old, so it passed. Proven: with the page open, recent data at load and 35 s of unchanged polls, no warning. Second defect in the same line: it compared the server's timestamp with the browser's clock, so a laptop clock 30 s off warns always or never. | `useUnchangedForMs` (`overviewChecks.ts`): how long the last-write timestamp has stood unchanged on the browser's own clock, re-checked by a 5 s tick. `staleWriteSeconds(phase, unchangedMs)`; text "No new clearing write for at least N s … (last write …)". Tests with fake timers: appears after 35 s of unchanged polls; never while writes change, with the server clock two hours off; never outside CONTINUOUS. Limit: a ledger already stale when the page opens is reported after 30 s of watching. Operator guide, help and design doc updated. |
| R2 | Low | Trades pager (CG20) with **All rows** and more on the server: Next was enabled but did nothing (it set a page number; the fetch rule needs a page size). | `DataTable.changePage`: with All, Next past the one page asks for the next server page. Test. |
| R3 | Low | Combobox (CG22): pressing the list's **scrollbar** blurred the input and closed the list, so a long list could not be scrolled with the mouse; Enter with nothing highlighted submitted but left the list open. | `mousedown` on the listbox is cancelled (focus stays in the input); Enter with no active option closes the list and lets the form submit. Two tests. |
| R4 | Low | Phase tile (CG23): after a failed refresh TanStack keeps the last reply, so the tile showed an old phase as current. | Sub-line "last known — the engine did not answer the latest check" when the latest refresh failed. Test. The stale-write rule keeps using the last-known phase, which is the useful reading when the engine stops answering mid-session. |

Checked and found sound (no change):

- Page-size store: one persisted choice; page index clamped through polls,
  reset on sort/size; a new filter remounts the table (proven in CG18).
- `more` loading: one `fetchNextPage` per need (effect keyed on the flag,
  tested to issue exactly one `after=` request).
- Venue timezone: one `/session` read per login from the shell; the Overview
  adds its own 30 s poll on the same key; a failed refresh keeps the zone.
- Merged Positions: per-row `net_qty × mark_price_ticks` matches
  `store.query_exposure`; no mark gives dashes.
- Gateway links: ADMIN only, never `EXCHANGE`; drawer's error boundary key
  keeps the list mounted (proven by mutation in CG21).
- Request discipline: `requests.test` holds every screen to its polled set.

Accepted limits (documented, not changed):

- N1: the error boundary is keyed per screen, so a crash inside a
  participant's drawer replaces the whole Participants screen until another
  screen is opened (the price of not remounting the list on open/close).
- N2: the EOD-lag rule cannot flag a day left unsettled once the next day has
  opened (CG23; operator guide says so).
- N3: Escape closes the drawer only while focus is inside it (non-modal by
  design, as dash-gui's).

Lesson: a warning that depends on time passing must be tested with time
passing — fake timers and unchanged polls — not with data that is already
old when the page loads.

## 9. Teaching round (2026-11-26)

The clearing GUI is primarily a teaching tool. After CG18–CG24 it shows every
number the ledger holds, but not how a number arises: a beginner sees
"Unrealized +240" without the average cost, the mark and the quantity that
make it, and sees a list of trades without the idea that every share bought
was sold by someone and that clearing nets thousands of trades into a few
payments. This round adds explanations and pictures for both levels: one
participant's position, and the venue as a whole.

The API may change where the data is missing. Any
arithmetic that clearing does is done by the server, never repeated in the
browser, so a picture cannot teach a rule that differs from the ledger's.

### 9.1 Decisions

| # | Question | Decision |
|---|---|---|
| D7 | Explanations in a tool operators also use | An **Explain** toggle in the top bar, one persisted choice (as the font size), **on by default**. On: figures show their formula and a one-line explanation inline, and the teaching pictures are shown. Off: the CG18–CG24 screens, unchanged. Words beside signs ("−300 short", "+240 gain") and the teaching empty states are always on. |
| D8 | Longs against shorts per symbol | Allowed. This **reverses CG1 constraint 7** ("not … long/short open interest") for the per-symbol long and short totals only: they are sums of stored positions, shown as a balance picture. Still no margin, equity or buying power. |
| D9 | Replaying a position trade by trade | **On the server**, through pm-clearing's own `_apply_fill_to_position`, from the previous stored end of day; the reply says whether the replay ends on the stored daily row. The browser draws, it does not compute. |
| D10 | Who traded with whom | ADMIN only. A participant never sees a counterparty, as today's trade rows. |
| D11 | Netting for a participant | Their own day: gross bought and sold value against their one net payment. The venue's totals only for ADMIN. |
| D12 | Pictures and accessibility | Every chart has its numbers in a table beside or under it (the `CloseChart` rule), is lazy-loaded with recharts, and has a fixed size fallback for tests and print. Colour is never the only carrier: gain/loss and long/short are also words. |

### 9.2 Work packages

API WPs come before the screens that need them. Order is the table order.

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 25 | CG25 | Explain mode; "how this number is made" per position; P&L split; words beside signs; teaching empty states | — | 1.5 d | ☑ | 2026-11-26 |
| 26 | CG26 | API: long/short totals per symbol; `GET /clearing/netting` | — | 1 d | ☑ | 2026-11-26 |
| 27 | CG27 | GUI: longs against shorts; netting; money in and out; venue P&L sums to zero | CG25, CG26 | 1.5 d | ☑ | 2026-11-26 |
| 28 | CG28 | API: `GET /clearing/position-replay` | — | 1.5 d | ☑ | 2026-11-26 |
| 29 | CG29 | GUI: position build-up replay in the drawer and My Positions | CG25, CG28 | 1.5 d | ☑ | 2026-11-26 |
| 30 | CG30 | API + GUI: who traded with whom (`GET /clearing/flows`) | CG25 | 1 d | ☑ | 2026-11-26 |
| 31 | CG31 | GUI: follow one trade | CG28 | 1 d | ☑ | 2026-11-26 |
| 32 | CG32 | Help, guides and a holistic review of CG25–CG31 | CG25–CG31 | 1 d | ☑ | 2026-11-26 |

API WPs are test-first in pytest (`tests/test_api_gateway_clearing_*.py`,
`clearing_api_fixture.py`) and exit with the clearing and api-gateway suites,
the OpenAPI contract suites, `spec/rest/openapi.json` regenerated, the REST
reference chapter ("Clearing" in `060-rest-and-websocket.md`) updated, and
black/flake8/mypy/pyright clean. GUI WPs are test-first in clearing-gui's
vitest suite and exit with the suite, the typecheck, the build and
`a11y.test.tsx` green; `contract.test.ts` holds every new schema to the
published spec.

### CG25 — Explain mode and "how this number is made"

- **Goal (D7):** the step from a number to its formula, using data every
  screen already has.
- **Explain toggle:** `useExplainStore` (zustand `persist`, key
  `clearing-explain`, default on; storage failure falls back to on), a
  switch in the top bar beside the font size, `aria-pressed`. An `<Explain>`
  wrapper renders its children only when on.
- **Per position (merged Positions table, drawer and My Positions):** in
  Explain mode a row expands (click, or the row's disclosure button) into a
  card: a small horizontal price scale with the average cost and the mark
  marked on it, the gap shaded gain or loss, and the arithmetic written out
  with the row's own values and precision: "Long 300 at average 101.20, mark
  102.00: (102.00 − 101.20) × 300 = +240.00 gain". A short reads
  "(average − mark) × quantity". A flat position explains that realized P&L
  stays after the position is closed. Values come from the row only.
- **P&L split:** in the card, a stacked bar realized + unrealized = total,
  each part labelled with its word and value.
- **Words beside signs (always):** net quantity "−300 short" / "+300 long" /
  "0 flat"; P&L "+240.00 gain" / "−12.00 loss" where a P&L column or tile is
  shown. Column widths checked at the smallest font size.
- **Teaching empty states (always):** each empty participant table says what
  would fill it and links the participant guide's clearing chapter, e.g.
  Positions: "No positions yet: a position appears when one of your orders
  trades."
- **Explain lines on the Overview and participant tiles:** one sentence under
  each `Stat`, from the same text as its tooltip, when on.
- **First failing tests:** the toggle persists and defaults on; a long and a
  short row produce the exact formula strings with the row's precision; the
  split bar's parts sum to the row's total P&L; with Explain off no card,
  chart or explain line is in the DOM; `−300 short` in the Net qty cell; each
  empty table shows its teaching text and link; axe clean with the card open.
- **Exit:** tests green; nothing changes for an operator who switches
  Explain off, except words beside signs and empty-state texts.
- **Done 2026-11-26.** `test/explain.test.tsx` (17) failed first on the
  absent behaviour (the store alone was added so the file would load). New:
  `store/useExplainStore.ts` (key `clearing-explain`, default on),
  `components/shared/Explain.tsx` (`ExplainToggle` in the top bar,
  `useExplain`, `ExplainLine`), `components/views/PositionExplain.tsx` (the
  sum, an SVG price scale with a text alternative, the split bar) and
  `components/views/teaching.tsx` (empty-table hints worded for "you",
  "this gateway" or "a gateway"). `DataTable` gained `detail` (open rows kept
  by `rowKey` through polls and paging). `lib/money.ts` gained
  `formatPnlTicks`, `formatPnlCurrency` and `formatPosition`; `tickColumn`
  a `pnl` option and `columns.tsx` a `positionColumn`. `Stat` shows its
  `title` as an explain line; the Overview's EOD tile does the same.
  The sum's result is always the ledger's value, never recomputed; the
  written-out average is rounded (4 decimals when not a whole tick), so the
  sum can be off in the last decimal, which the module comment says.
  Words: every per-position and per-participant P&L cell and the drawer's
  P&L tiles; not the Overview's venue P&L tiles or the Symbols screen's
  venue columns (a venue sum is nobody's gain), not settlement amounts (a
  payment, not P&L), not net notional. Changed old tests: `myClearing`
  expects "110 long", "26.67 gain", "100.00 gain" (intended). Suite 272
  (was 255), typecheck and build green; axe clean with a card open.
  **Deviations:** (1) the disclosure is a button at the start of the first
  cell, not a row click: a separate column broke the "every header has a
  tooltip" rule, and a row click is already the drawer on the Participants
  list. (2) Empty tables *name* the guide chapter ("Read more in the
  Participant Guide, “Positions and P&L”") instead of linking it: the GUI
  has no docs URL to link to (`mkdocs.yml` `site_url` is the repository).
  **Not done:** the column widths at the smallest font size and the price
  scale's look were not checked in a browser; do it on the next live run
  with CG27's pictures.

### CG26 — API: long/short totals per symbol, and netting

- **Goal (D8, D11):** the two venue-level figures a beginner needs, computed
  where the positions and daily rows are.
- **`GET /clearing/symbols` (ADMIN) gains** `open_long_qty`,
  `open_short_qty` (positive, from current positions), `long_holders`,
  `short_holders` (gateway counts). `open_net_qty` stays and the docstring
  explains `open_long_qty − open_short_qty = open_net_qty`. Update the
  `ClearingSymbolRow` model, example and the reversed constraint 7 in CG1's
  text (with a pointer to D8).
- **New `GET /clearing/netting?date=`** (default: the latest `trade_date`),
  from `gateway_daily_summary` and `trade_events` for that day:
  - ADMIN: `trade_count`, `traded_qty`, `gross_value` (Σ buy value, each trade
    counted once), `payment_count` (gateways with a non-zero net amount),
    `net_paid` and `net_received` (Σ of negative and positive net amounts,
    display currency per row then summed, as `participants`), and per
    gateway `bought_value`, `sold_value`, `net_amount`.
  - TRADER/MM: the same totals for their own gateway only (one row; no
    venue counts).
  - `trades_retained: false` when the day's raw trades are pruned (then
    `trade_count` is null; the daily-row figures still answer).
- **First failing tests:** a fixture with two gateways long and one short in a
  symbol gives the right long/short totals and holder counts, and long −
  short equals the old net; netting on a 3-gateway day gives gross value
  counted once, net amounts summing to zero, `payment_count` and the
  per-gateway rows; a participant sees only their row; a pruned day gives
  `trades_retained: false`; bad date 400; unknown day an empty reply.
- **Exit:** as §9.2 for API WPs.
- **Done 2026-11-26.** `tests/test_api_gateway_clearing_teaching.py` (10)
  failed first (404 / missing fields). `store.query_symbols` gains
  `open_long_qty`, `open_short_qty`, `long_holders`, `short_holders` (a flat
  position is on neither side); new `store.query_latest_trade_date` and
  `store.query_netting`; route `GET /clearing/netting` with model
  `ClearingNetting` / `NettingGatewayRow`, example
  `CLEARING_NETTING_REPLY`. A pruned day is detected as "the day has daily
  rows and is older than `query_retained_from`". A net below 1e-9 counts as
  zero (float residue of balanced days). Spec regenerated; REST chapter
  section + route row, operator-guide and participant-guide route tables;
  contract matrix and the v1 route layout list gained the route;
  clearing-gui `schemas.ts` gained `Netting` and the four symbol fields
  (the GUI contract test requires every route). Full suite 15 589 passed,
  coverage 91.9%; black, flake8, mypy, pyright, `openapi-check`, `mkdocs
  build` clean; clearing-gui 274.
  **Beyond the plan:** (1) a `gateway` filter, as every gateway-scoped
  route has: the error-code check found `SCOPE_DENIED` reachable through
  `clearing_scope`, and CG27's drawer needs one gateway's netting for an
  ADMIN; tested (ADMIN `gateway=TRADER01` equals TRADER01's own reply; a
  participant naming another is `SCOPE_DENIED`). (2) `trade_count` per
  gateway. **For CG27:** this is the cash the trades net to, not pm-eod's
  settlement (which moves the change in P&L); the screen must not call these
  "settlement payments". The API docs say so.

### CG27 — GUI: longs against shorts, netting, money in and out, P&L sums to zero

- **Longs against shorts (Symbols screen, ADMIN):** per symbol, a mirrored
  bar: long quantity right, short quantity left, always equal length, with
  the holder counts. Explain line: "Every share held long was sold by someone
  who is now short: the two sides are always equal." The table keeps the
  numbers.
- **Netting (Overview for ADMIN; My Settlement / drawer Settlement for a
  participant):** one sentence and two bars: "Today 1 240 trades worth
  3.1 M were settled with 14 net payments totalling 42 k." For a participant:
  "You bought 120 k and sold 118 k; you pay 2 k." From `/clearing/netting`,
  polled at 30 s for the current day, once for a past day.
- **Money in and out (drawer and My History):** per day, the bought and sold
  value bars and the net amount, from the existing daily rows.
- **Venue P&L sums to zero (Participants screen, ADMIN, Explain mode):** a
  bar per gateway, gains above the line and losses below, with the sum shown
  as "0.00 (gateways trade with each other)". From the participants list
  already fetched; a sum that is not zero within rounding is shown as it is,
  not hidden.
- **First failing tests:** each picture's table equivalent holds the reply's
  numbers; the netting sentence for a venue and a participant reply; a pruned
  day says "raw trades for this day are no longer kept" instead of a count;
  `requests.test` gains the netting poll on exactly the screens above;
  Explain off removes the pictures, not the tables; axe clean.
- **Exit:** as §9.2 for GUI WPs.
- **Done 2026-11-26.** `test/teaching.test.tsx` (16) failed first (no
  panels; the 5 Explain-off cases passed vacuously until then). New:
  `components/shared/Bars.tsx` (`DivergingBars`, `ValueBars`, both
  `aria-hidden`), `components/views/NettingPanel.tsx` (Overview, venue;
  My Settlement, own; drawer Settlement, `gateway=`), `LongShortPanel.tsx`
  (Symbol Activity), `MoneyByDay.tsx` (History, drawer and My, follows the
  history filters) and `PnlBalance.tsx` (Participants); `useNetting` (30 s,
  enabled only in Explain mode); `Netting` types. Every panel says what the
  picture means in one or two sentences and carries its numbers in a table
  (P&L sums: the Participants table above it). The netting texts say it is
  cash netting and not pm-eod's settlement, which moves P&L (CG26's note).
  `requests.test` allows `/clearing/netting` as a polled route; the tooltip
  and axe suites now stub it, so its table's headers are checked. Suite 290
  (was 274), typecheck and build green.
  **Deviations:** (1) the pictures are plain HTML bars, not lazy-loaded
  recharts (D12): horizontal bars need no chart library or lazy chunk.
  (2) Every CG27 addition, the netting panel and its table included, is
  Explain-only, by D7 ("off: the CG18–CG24 screens, unchanged"); the
  plan's "removes the pictures, not the tables" meant the tables that
  existed before. (3) Netting shows the latest trading day only (the API's
  default); no past-day picker, so "once for a past day" does not arise.
  (4) At most 20 bars per picture (largest first), the table lists all.
  **Not done:** a look in a browser (bar widths at each font size, a venue
  with many gateways); with CG25's, on the next live run.

### CG28 — API: position replay

- **Goal (D9):** how one gateway's position in one symbol moved through one
  trading day, step by step, by clearing's own rules.
- **`GET /clearing/position-replay?gateway=&symbol=&date=`** (date default:
  the latest `trade_date` for that pair). Scope as `positions`.
- **Start state:** the pair's last `gateway_daily_summary` row before `date`
  (`end_net_qty`, `end_avg_cost`; realized starts at 0 for the day), or flat
  when there is none.
- **Steps:** the pair's own fills on `date` from `trade_events`, in ledger
  order, each applied with `ledger._apply_fill_to_position` on a scratch
  `_Position` (rescaled with `_rescale_position` when `tick_decimals` changes,
  as the ledger does). Per step: `trade_id`, `ts_ns`, side, quantity, price,
  `kind` (`open` / `add` / `reduce` / `close` / `flip`), and after the step
  `net_qty`, `avg_cost`, `realized_delta`, `realized_day`, the unrealized P&L
  at the fill price. Money in the row's precision with `_ticks`, as every
  clearing route.
- **Check:** `matches_daily_row` (end state equal to that day's stored row
  within the ledger's float tolerance) and, for the latest day,
  `matches_position`. A mismatch is reported with both values, never
  corrected.
- **Limits:** a day older than the raw-trade retention gives
  `trades_retained: false` and no steps; at most 5 000 steps
  (`has_more: true` beyond, with the start state still correct for the
  shown steps).
- **First failing tests:** open, add (VWAP), partial reduce, full close and
  flip each produce the documented `kind`, `avg_cost` and `realized_delta`;
  a replay over a fixture day ends on the stored daily row and position; a
  start from a previous day's carried position; a `tick_decimals` change;
  scope denial for another gateway; pruned day; the 5 000 cap.
- **Exit:** as §9.2 for API WPs.
- **Done 2026-11-26.** 10 tests in `test_api_gateway_clearing_teaching.py`
  failed first (404; the module held only `MAX_STEPS` so the file loads).
  New `clearing/replay.py` (`replay_position`, 100% covered), models
  `PositionReplay` / `ReplayStart` / `ReplayStep` / `ReplayDailyRow`,
  example `CLEARING_POSITION_REPLAY_REPLY`, route with a required `symbol`
  and optional `gateway`, `date`. Steps use the ledger's
  `_apply_fill_to_position` and `_rescale_position` on a scratch
  `_Position` (file-level `reportPrivateUsage=false`, as
  `audit/replay/rerun.py`, with the reason). Order: `trade_events.rowid`,
  the order clearing stored and applied the trades; a self-trade is buy leg
  then sell leg. Kinds: open / add / reduce / close / flip. A hand-made
  ledger covers every kind and a precision change in a carried position; a
  test replays every gateway × symbol × day of the recorded venue and
  requires it to end on the ledger (mutation-checked: starting flat instead
  of from the previous day fails it). Spec regenerated; REST chapter
  section and row, operator and participant guide rows, contract matrix,
  route layout, clearing-gui `PositionReplay` schema. Full suite 15 604
  passed, coverage 91.9%; black, flake8, mypy, pyright, `openapi-check`,
  `mkdocs build` clean; clearing-gui 292.
  **Decisions made here:** the stored daily row is echoed as `daily_row`
  (CG29's mismatch warning needs both values); `matches_position` is
  checked on the pair's latest day only, and on net quantity and average
  cost (the stored position's realized P&L is cumulative, the replay's is
  the day's); a replay cut at `MAX_STEPS` is not checked.

### CG29 — GUI: position build-up replay

- **Where:** the Explain card of a position (CG25) gains "Show how this
  position was built today", in the drawer and My Positions; History rows
  open the replay for their day.
- **Picture:** a step chart of `net_qty` per fill, the average-cost line
  beside the fill prices, and the day's realized P&L stepping at each reduce.
  A step table under it (the D12 rule). Selecting a step (chart or table)
  writes it out: "Sold 100 of a 300 long at 103.00: realized
  (103.00 − 101.20) × 100 = +180.00 gain; average cost unchanged." One
  sentence per `kind`.
- **Mismatch:** when `matches_daily_row` is false, a warning above the chart
  with both values ("Replay ends at 290, the ledger holds 300 — report this").
- **First failing tests:** each `kind`'s sentence from a fixture reply; the
  step table matches the reply; a mismatch shows the warning; pruned day and
  empty day texts; keyboard selection of steps; axe clean.
- **Exit:** as §9.2 for GUI WPs.
- **Done 2026-11-26.** `test/replay.test.tsx` (16) failed first (no
  button; the Explain-off case passed vacuously). New
  `components/views/PositionReplayView.tsx`: start sentence, an SVG of two
  bands (position as a step line; fill prices as dots, buy green / sell
  red, against the average-cost line), a `role="status"` line that writes
  out the selected fill (`stepSentence`, one form per kind, with the
  previous step's average converted to the fill's precision), and the
  "Fills of SYMBOL on DATE" table (unsorted, row click / Enter selects).
  Mismatch with the daily row or the position is a `role="alert"` with
  both values; pruned, empty, never-traded and capped days have their own
  sentence. Opened from the position card ("Show how this position was
  built", the latest day the pair traded) and, in Explain mode, from each
  Daily activity row ("Replay SYMBOL on DATE", that day). `usePositionReplay`
  is a cached read, fetched only when opened. `formatAverage` moved to
  `lib/money.ts` (shared with the CG25 card). Suite 308 (was 292),
  typecheck and build green; axe clean with a step selected.
  **Deviations:** the chart is plain SVG, not recharts (as CG27); its dots
  are mouse-only and `aria-hidden`, the table is the keyboard and
  screen-reader path. "Built today" is "the latest day the pair traded",
  the API's default, so a position untouched today still has a replay.

### CG30 — Who traded with whom

- **API (D10): `GET /clearing/flows?date=&symbol=`**, ADMIN only
  (`require_admin`): per (buyer, seller) gateway pair, `trades`, `quantity`,
  `value`, from `trade_events` for the day; `trades_retained` as CG26. Tests:
  a 3-gateway fixture's pairs, symbol filter, a self-trade pair if the engine
  allows one, role denial for TRADER/MM, pruned day.
- **GUI (Symbols screen or a new "Flows" panel on the Overview, ADMIN):** a
  buyer × seller grid, cells shaded by value with the value written in, rows
  and columns ordered by total, at most 20 gateways shown with the rest as
  "others". Gateway headers open the participant drawer. Explain line: "Each
  cell is what one participant bought from another today; clearing settles
  each participant's net, not each cell." Table equivalent: the pair list.
- **Exit:** as §9.2 for API and GUI WPs.
- **Done 2026-11-26.** API: 4 tests in `test_api_gateway_clearing_teaching.py`
  failed first (404). `store.query_flows` (pairs from `trade_events`, value
  per trade in its own precision, largest first; pruned day = daily rows
  older than the retained trades), models `ClearingFlows` / `FlowPair`,
  example, route `GET /clearing/flows?date=&symbol=` (ADMIN only; default
  the latest day). Spec, REST chapter section and row, operator-guide row
  (not the participant guide: ADMIN only), contract matrix, route layout.
  Full suite 15 613 passed, coverage 91.9%; black, flake8, mypy, pyright,
  `openapi-check`, `mkdocs build` clean.
  GUI: `test/flows.test.tsx` (6) failed first. `FlowsPanel.tsx` on the
  Overview after Netting, Explain only, `useFlows` (30 s): one sentence, the
  grid (a real table: row and column headers with tooltips, the value
  written in each shaded cell, gateway headers link to the drawer; beyond
  the 20 gateways that traded most, one "others" row and column) and the
  "Trades by pair" list with every pair. `requests.test` allows the poll;
  tooltip and axe suites stub it. Suite 316 (was 308), typecheck and build
  green.
  **Wording changed from the plan:** "clearing settles each participant's
  net" became "nets each gateway's buys against its sells … (see
  Netting)", to keep cash netting apart from pm-eod's P&L settlement
  (CG26's note). The panel is on the Overview, not the Symbol Activity
  screen: it is one day, and that screen is a date range.

### CG31 — Follow one trade

- **Where:** any trade row (Trades screen, drawer Trades, My Trades) opens a
  trade panel inside the drawer (ADMIN) or a dialog (participant).
- **Timeline:** matched in the engine (`ts_ns`) → received by clearing
  (`ingest_ts_ns`, with the difference) → the position change for each side
  the caller may see (the replay step for that trade, CG28) → the day's
  daily row → the EOD run and settlement for its `trade_date` (existing
  settlements reply; "not settled yet" before EOD). A participant sees their
  own side only.
- **Tests:** every stage from fixture replies; a trade before EOD shows "not
  settled yet"; a participant's panel has no counterparty; axe clean.
- **Exit:** as §9.2 for GUI WPs.
- **Done 2026-11-26.** `test/followTrade.test.tsx` (5) failed first (no
  button; the Explain-off case passed vacuously). New
  `components/views/TradeTimeline.tsx`: matched (exchange time, match type;
  a participant reads "you sold … The buyer is not shown to you"),
  received (ingest time and the delay), then per visible side: its replay
  step written out (`stepSentence`), the day's daily row (from the same
  replay reply, so no extra request), and pm-eod's settlement of the day
  for it (settled with direction and amount, run failed, settled with
  nothing, or "not settled yet"), with the note that a settlement moves the
  day's change in P&L, not the trade's value. The replay is the one History
  opens (same query key, cached); settlements are one cached read per side.
  `myClearing`'s "no header sorts" check now looks at the header only (the
  rows have Follow buttons). Suite 321 (was 316), typecheck and build green.
  **Deviation:** the timeline opens under its trade row (the `detail`
  disclosure, Explain mode), for ADMIN and participant alike, not in a
  separate panel or dialog: the same pattern as CG25/CG29, and nothing to
  close or lose focus to.

### CG32 — Help, guides and holistic review

- Help drawer topics "Explain mode" and "Reading the pictures"; the
  operator and participant guide clearing-GUI chapters describe each picture
  and what it teaches; the design doc's screen list. Screenshots only from a
  live sim run.
- Holistic review of CG25–CG31 as §8.4, written up as §9.3, including a
  live-sim check of every picture with real data (widths, font sizes, a day
  with many gateways).
- **Done 2026-11-26.** Help drawer topics *Explain mode* and *Reading the
  pictures*; *Getting Started* no longer says "no open interest anywhere"
  (D8). Participant guide: a section *Explain mode: where each number comes
  from* and a replay-mismatch row in *When something looks wrong*. Operator
  guide: a section *Explain mode and the teaching pictures* (where, what,
  which route), the replay mismatch in *Diagnosing* (with `pm-clearing-cli
  rebuild`), the Explain polls in *Load*, the long/short note in *What it
  leaves out*. Design doc: the three new routes and the symbols change in
  the route table, §7.4 updated, new §7.5. Review below. No screenshots:
  they wait for a live sim run.

### 9.3 Holistic review of CG25–CG31 (2026-11-26)

The committed range `086b13b3..6f93c128` (34 source files, +2 216 lines)
was read as a whole, looking for interactions between the WPs and cases
their own tests did not reach. Two defects were found; each got a failing
test first and is fixed. clearing-gui suite 323 (was 321), typecheck,
build and `mkdocs build` green; no Python changed in CG32.

| # | Sev | Finding | Fix |
|---|---|---|---|
| R5 | Low | *Money in and out by day* (CG27) sums the daily rows it is given; they come newest first, bounded at 1 000, so when more match the oldest day can be cut and its total silently short. | `MoneyByDay` takes `hasMore` and leaves the oldest day out, saying so ("… is left out: more daily rows match than were sent"). Test. |
| R6 | Low (latent) | `DataTable`'s row Enter/Space handler (CG21) also caught keys pressed on a button inside the row — CG25's disclosure: Enter on the disclosure would open the row instead. No table has both today. *(Corrected by §9.4: keys in a table nested in a detail row never reach the item row, which is its sibling.)* | The row handles only its own keys (`e.target === e.currentTarget`). Test with a table that has both. |
| D1 | Doc | Help *Getting Started* and the operator guide's *What it leaves out* still said there is no open interest anywhere; the design doc said long/short totals were not implemented. | Reworded to D8 (part of CG32's doc work). |

Checked and found sound (no change):

- No position arithmetic in the browser: the card's result, the replay and
  the trade timeline all show the server's values; written-out sums use the
  replay's own previous step.
- Cash netting is worded apart from pm-eod's settlement wherever both can
  be seen (Netting on Settlement and Overview, Money in and out, Who traded
  with whom, the trade timeline's settlement note).
- Explain off requests nothing new (each screen tested) and draws nothing
  new; words beside signs and teaching empty states stay, by D7.
- Scope: flows ADMIN only; a participant's trade timeline asks only for its
  own side; the replay and netting take `gateway` through `clearing_scope`.
- Request discipline: netting and flows are the only new polls (30 s, in
  `requests.test`); replay and settlements are cached reads on demand.
- Every new table's headers have tooltips (`Column.title` is required; the
  tooltip suite covers the panels shown by default); axe is clean on every
  picture.
- The replay's order (`trade_events.rowid`) is the order clearing applied
  the trades: inserts are `INSERT OR IGNORE`, so a row's rowid never moves.

Accepted limits (documented, not changed):

- N4: a participant following a self-trade (buyer and seller both itself)
  reads "you bought … The seller is not shown to you"; the engine's SMP
  makes such trades rare.
- N5: *Longs against shorts* follows Symbol Activity's date range: a symbol
  held but not traded in the range is not drawn. With no filter, every
  symbol is.
- N6: the live-sim check of every picture (widths at each font size, a
  venue with many gateways, a replay of a busy day) is still to do.

Lesson: a summary computed from a bounded list must know whether the list
was cut — the same `has_more` that drives the "more rows" note.

### 9.4 Holistic review of CG25–CG32 (2026-11-26)

The committed range `086b13b3..ce658de1` (CG25–CG32, including §9.3's own
fixes) was reviewed again, this time with measurements: the teaching round
added polled routes, and Explain mode is on by default, so every open
Overview and Settlement screen polls them. `tools/clearing_api_bench.py`
now includes the new routes. One defect was found and fixed test-first;
one statement of §9.3 was wrong and is corrected.

| # | Sev | Finding | Fix |
|---|---|---|---|
| P1 | Medium | `/clearing/netting` (CG26) counted each gateway's trades with `COUNT(DISTINCT id)` over a `UNION ALL` of the whole day's trades, even for one gateway. On a 100 000-trade day: 160–220 ms per call, polled every 30 s by every participant's My Settlement in Explain mode — about a quarter of a core for 40 participants. | `_day_trade_count`: buys + sells − trades with itself, each a count on the buyer/seller index. One gateway: 174 → 7 ms on that day (3 ms on the standard 90-day bench). Venue: 160 → ~100 ms, ADMIN Overview only (the trades-with-itself count needs row lookups; a partial index would cost clearing's write path, not done). Test: the query plans of `query_netting` read the gateway indexes, never the day's walk with a temporary B-tree (mutation-checked: the old union fails it); a trade with itself counts once. |
| C1 | Doc | §9.3 R6 said keys pressed in a table nested in a detail row reached the item row. They do not: the detail row is the item row's sibling. The fix stands for the real case, a button inside the row. | §9.3 corrected. |

Measured with the bench (in-process, real gateway app):

| Route | 90 days × 2 000 trades | 1 day of 100 000 trades |
|---|---:|---:|
| netting, venue (ADMIN, 30 s) | 9 ms | ~100 ms |
| netting, one gateway (30 s) | 3 ms | 7 ms |
| flows (ADMIN, 30 s) | 19 ms, 89 kB | ~110 ms, 130 kB |
| position-replay (on demand) | 4 ms | 16 ms (250 fills, 112 kB) |

Checked and found sound (no change):

- A participant naming its own gateway — as the trade timeline and the
  replay do with the row's gateway id — is accepted by `/position-replay`,
  `/settlements` and `/netting` (new test against the real routes; the
  CG31 tests used stubs).
- The replay's store order (`INSERT OR IGNORE`, rowid) and its check
  against the daily row: a precision change is compared in display values.
- Docs: every command and route named in the CG32 texts exists as written
  (`pm-clearing-cli rebuild --from-audit … --output …`).

Accepted limits (in addition to §9.3's N4–N6):

- N7: the venue netting (~0.1 s on a 100 000-trade day) and who traded with
  whom (~0.1 s; its payload grows with the number of buyer/seller pairs,
  130 kB for 40 gateways) are polled every 30 s by an ADMIN Overview in
  Explain mode. The operator guide's load table gives the numbers and says
  that Explain off stops them.

Lesson: when a mode is on by default, its polls are the default load —
measure them on a busy day, not only on the bench's average one.

