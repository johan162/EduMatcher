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
| F9 | CG4 review | `query_reconcile` (shared with `pm-clearing-cli reconcile`) compares raw `quantity * price` in each trade's own ticks with daily rows that K6 rescales to the latest precision. | After a symbol's `tick_decimals` changes, its days report false notional discrepancies. Pre-existing; the API now at least returns `tick_decimals` per row. | data-quality/observability gap | Not fixed here (no tick-precision change in 1.0 scope); revisit with K6 if precision changes become an operator action. | open |
| F10 | CG5 | Epoch-nanosecond fields (~1.8e18) exceed JavaScript's safe-integer range: zod 4's `.int()` rejected every real timestamp, and `JSON.parse` rounds them by a few hundred ns. | Every response with a `*_ns` field would have been a contract error in the browser. | contract ambiguity | Contract test failed on the documented examples; `*_ns` are now `nanos` (a plain number), documented as display-only, never compared for equality. | closed |
| F11 | CG5 | FastAPI renders `openapi.json` with `exclude_none`, so example fields whose value is `null` vanish from the published examples (e.g. `/positions`' TSLA row, a participant's masked counterparty), while the wire carries them as `null`. | A client generated from the examples would treat nullable-required fields as optional. | documentation defect | GUI contract test restores the omitted `null`s for nullable fields only (`test/helpers.tsx` `withNulls`) and still checks required-ness against the schema; the published examples themselves are unchanged (all routes, pre-existing). | open (contract rendering) |
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
