# REST API Review before v1.0.0

**Scope:** `src/edumatcher/api_gateway/` (`main.py`, `sessions.py`, `schemas.py`,
`openapi_docs.py`, `routers/{orders,reference,history,admin,bootstrap,ws}.py`),
the generated OpenAPI document, the normative spec
(`docs/books/protocols-and-clients/part-2-specifications/060-rest-and-websocket.md`),
the operator guide chapter (`operator-guide/part-5-gateways/050-api-gateway.md`),
the training chapter (`training-guide/240-api-gwy.md`) and the REST examples under
`docs/examples/REST/`.

**Date:** 2026-10-30 (code at v0.65.6, `develop` @ `0e17ec96`)

**Subject:** whether `pm-api-gwy`'s `/api/v1` REST and WebSocket surface is ready
to be frozen as the v1.0.0 contract.

**Method:** I read every router and schema. I generated `openapi.json` from
`create_app()` and analysed it (61 operations). I probed the running ASGI app
for error behaviour (missing auth, unknown route, wrong method). Then I compared
the surface with the engine topic catalogue (`models/generated/*`),
`pm-admin-cli`, `pm-index-admin-cli` and `pm-news-cli`, and checked the docs
against the code.

---

## 1. Overall assessment

The API is **functionally rich and carefully engineered underneath**. Several
things are better than in most exchange APIs I have reviewed:

- `reject_code` uses the same vocabulary as ALF, so REST and ALF clients see the
  same code for the same mistake.
- Keyset pagination uses opaque cursors and rejects stale cursors explicitly.
- `retained_from` lets a client tell "no data" from "data pruned".
- The bootstrap endpoints run their queries in parallel and report a partial
  failure through `incomplete`.
- The WebSocket sink is registered *before* the snapshot is taken, and
  `stream_seq` makes private-stream recovery possible.
- A market-data subscription is a set of (symbol, channel) pairs.
- The tick-grid gate and the `SYMBOLS_NOT_READY` gate are in place.
- The OpenAPI examples are tested against the message specs.

The main weakness is the **contract layer**: what a client can rely on and code
against. That layer is not yet in a shape that should be frozen:

1. **Only 6 of 61 operations have a typed response schema.** The other 55 return
   `dict[str, Any]`, often an engine payload forwarded unchanged. In practice the
   1.0 contract would be "whatever the engine happens to send", and any engine
   message change would silently become an API change.
2. **The error model is inconsistent with its own normative MUST.** Unknown
   routes and wrong methods return FastAPI's `{"detail": ...}`. A missing
   `Authorization` header returns `400 VALIDATION`, not `401 AUTH`. Validation
   failures are `400` on some endpoints and `422` on others. Engine refusals of
   admin commands come back as `403 ROLE_DENIED`.
3. **Asynchronous writes are not safe to retry.** There is no idempotency
   mechanism. Also, a `?wait=ack` timeout returns `503` *after the order was
   sent*, so the client never learns the `order_id` of a live order.
4. **The resource layout has grown organically.** There are duplicate endpoints,
   three different "session" endpoints, admin URL styles that mix verbs,
   resources, path, body and query parameters, WebSocket paths sharing the REST
   namespace (`/api/v1/admin/sim` is both a REST GET and a WebSocket), and
   internal message names in paths (`/quotes/bootstrap`).
5. **The WebSocket half of the API has no normative specification.** The
   OpenAPI description gives the wrong WebSocket paths.

All of these changes are **breaking**. Today they cost one coordinated change
across the gateway, the four web apps and the docs. After 1.0 they would need a
`/api/v2`. Completeness gaps, by contrast, are mostly **additive** and can ship
in 1.x without breaking anyone.

**Verdict:** not ready to freeze as is. Fix the P0 work packages in §9 (contract,
errors, write semantics, layout, plus a handful of correctness bugs) before
tagging 1.0.0. Admin parity (P1) is strongly recommended for 1.0 given the "full
control" goal, but is additive. The P2 items can follow in 1.x.

---

## 2. Surface inventory

| Group | Ops | Paths |
|---|---:|---|
| Trading (`orders` tag) | 14 | `POST/GET /orders`, `GET/PATCH/DELETE /orders/{id}`, `POST /orders/{id}/replace`, `POST /oco`, `DELETE /oco/{id}`, `POST /combos`, `DELETE /combos/{id}`, `POST /quotes`, `DELETE /quotes/{symbol}`, `POST /mass-cancel`, `POST /kill-switch` |
| Reference & account | 15 | `/reference`, `/reference/{config-version,symbols,risk,indexes,schedule}`, `/symbols`, `/news`, `/companies/{symbol}`, `/session`, `/halts`, `/quotes/bootstrap`, `/quotes/legs`, `/positions`, `/status` (+ unlisted `/healthz`) |
| History | 11 | `/history/{orders,orders/{id},fills,session,trades,daily,price-snapshots,index-daily,index-snapshots,index-ids,index-events}` |
| Admin | 18 | `/admin/session/{transition,schedule}`, `/admin/reference/reload`, `/admin/sim`, `/admin/gateways`, `/admin/gateways/{gid}/disconnect`, `/admin/circuit-breaker/{trigger,resume}`, `/admin/halts`, `/admin/risk/state`, `/admin/indexes`, `/admin/indexes/{id}/rebalance`, `/admin/kill-switch/{symbol,gateway,global}`, `/admin/orders`, `/admin/orders/{id}`, `/admin/positions` |
| Bootstrap | 3 | `/bootstrap/{trader,mm,admin}` |
| WebSocket | 4 | `/events`, `/market-data`, `/admin/monitor`, `/admin/sim` |

---

## 3. Completeness

The test here is whether every capability in the system is reachable, and
whether the API gives the control a participant or operator would expect.

### C1. Admin control lags behind `pm-admin-cli` (High)

`pm-admin-cli` (`commands/cli.py`) can do the following, which REST cannot,
although the engine topics already exist:

| CLI command | Engine topic | REST |
|---|---|---|
| `halt` / `resume` (exchange-wide) | `risk.circuit_breaker_halt_all[_ack]`, `..._resume_all[_ack]` | missing |
| `reopen --sym [--price] [--dry-run]` | `risk.force_uncross[_ack]` | missing: an operator cannot reopen a halted symbol at a chosen price |
| `kill --gw --sym` | `risk.kill_switch_gateway` | `/admin/kill-switch/gateway` has no symbol scope |
| `qcancel --gw --sym` | `quote.cancel` for another gateway | missing |
| `orders --gw` (engine-authoritative) | `order.orders_request` | only `/admin/orders`, a best-effort cache (see R6) |
| `level --sym [--price]` | `order.price_level_orders_request` | missing |
| `volume` | `system.volume_request` | missing |
| `book --sym` | `book.snapshot_request` | WebSocket only |

The admin GUI (`dash-gui`) and any operator automation therefore still need
ZMQ access through the CLI for real incident handling: halt the market, reopen
a symbol, pull one market maker's quote. For a 1.0 that claims operator control
over REST, this is the most visible gap.

### C2. Index administration is partial (Medium)

Only `rebalance` is exposed. `pm-index-admin-cli`'s `split`, `dividend`,
`shares`, `add` and `delist` (`index.corp_action`, `index.constituent_change`)
are not. `history` is covered by `/history/index-events`.

### C3. No REST control of news or the simulator (Low–Medium, classroom value)

`/admin/sim` and `/ws/admin/sim` are read-only. `pm-news-cli`'s
`inject`/`confirm`/`retract`/`play` and the `sim.command` topic have no REST
equivalent, so an instructor cannot run a news scenario from a browser.
Additive, so it can wait for 1.x.

### C4. No REST market-data snapshot (Medium)

Book, depth and top of book are WebSocket only. A script, a spreadsheet or a
teaching exercise ("fetch the book, place an order inside the spread") has to
open a WebSocket for a single read. `GET /book/{symbol}` (L1/L2) and a
venue-wide `GET /quotes/top` (or similar) are standard in exchange REST APIs.
The gateway already caches book events (`market_cache.py`) and can request a
snapshot (`book.snapshot_request`).

### C5. Public data is locked behind trading keys (Medium, breaking to fix later)

`GET /session`, `GET /halts` and `GET /symbols` call `require_trading`. The
docs call session and halt state public, and read-only keys get them over the
market-data WebSocket, but a read-only REST client cannot ask "is the market
open?". `/history/session` exists partly to work around this. Relaxing access
is additive, but folding the session endpoints together (D2) is not.

### C6. Structures cannot be listed or inspected (Medium)

There is `POST /oco` and `DELETE /oco/{id}`, but no `GET /oco` or
`GET /oco/{id}`, and the same for combos. Active quotes are only reachable
through the oddly named `GET /quotes/bootstrap`. After a reconnect a client
cannot rebuild which OCO groups or combos it has open without scanning order
events.

### C7. Limits on order reads (Low)

- `GET /orders` has no `status` or `symbol` filter and no pagination.
- `GET /orders/{id}` is served from the cache only, and returns 404 once
  `order_retention_sec` evicts the order. A client then has to know to fall
  back to `/history/orders/{id}`.

### C8. `?wait=ack` coverage is uneven (Medium)

`wait=ack` exists for submit, cancel and amend only. OCO, combo, quote and
their cancels always return `PENDING`, with no way to get the verdict except
the WebSocket. `replace` always waits for the cancel but never for the
replacement, and accepts no `request_tag`.

### C9. Out of scope, but should be stated (Info)

Drop copy, clearing ledger queries (beyond realized P&L on `/positions`), audit
search and the log server are not on REST. That is reasonable because they
have their own gateways and CLIs. The 1.0 spec should say so explicitly so the
absence reads as a decision, not an omission.

---

## 4. Resource design and consistency

### D1. The admin URL scheme mixes four styles (High, breaking)

| Endpoint | Target given in |
|---|---|
| `POST /admin/gateways/{gid}/disconnect` | path (`gid`) |
| `POST /admin/kill-switch/gateway` | body (`target_gateway_id`) |
| `GET /admin/positions?gateway_id=` | query (`gateway_id`) |
| `POST /admin/circuit-breaker/trigger` | body (`symbol`), with a verb in the path |

The same concept (a gateway or a symbol) is addressed three different ways,
under three names (`gid`, `target_gateway_id`, `gateway_id`). Proposal: one
resource-plus-action scheme.

```
POST /admin/market/halt | /resume | /kill-switch          (venue-wide)
POST /admin/symbols/{symbol}/halt | /resume | /reopen | /cancel-orders
GET  /admin/symbols/{symbol}/orders[?price=]              (price-level drill-down)
GET  /admin/gateways                                      (roster)
POST /admin/gateways/{gateway_id}/disconnect | /kill-switch[?symbol=]
GET  /admin/gateways/{gateway_id}/orders | /positions
DELETE /admin/gateways/{gateway_id}/quotes/{symbol}
POST /admin/session/transition
POST /admin/reference/reload
POST /admin/indexes/{index_id}/rebalance | /corporate-actions | /constituents
```

### D2. Duplicate and overlapping endpoints (Medium, breaking)

Every duplicate is permanent maintenance and documentation cost after 1.0.

| Duplicate | Recommendation |
|---|---|
| `POST /kill-switch` is an alias of `POST /mass-cancel` | keep one; per the no-backwards-compat rule, drop the alias |
| `GET /admin/halts` is the same as `GET /halts` | drop the admin copy |
| `GET /admin/indexes` is the same as `GET /reference/indexes` | drop the admin copy |
| `GET /admin/session/schedule` is close to `GET /reference/schedule` | keep one (reference) |
| `GET /session`, `GET /history/session` and `GET /reference/schedule` each answer part of "what is the session" | one `GET /session` returning phase, `next`, `session_timezone`, `session_date` and `country`, open to read-only keys |
| `GET /symbols` and `GET /reference/symbols` | keep both only if the per-caller fields (MM obligation, `prev_close`) are worth a second endpoint; otherwise merge into `/reference/symbols` with a caller section |

### D3. One path pattern, three meanings (Medium, breaking)

- `GET /orders/{id}` returns the cached current state.
- `GET /history/orders/{id}` returns the pm-stats event timeline.
- `GET /admin/orders/{id}` returns the pm-audit trail.

The admin one breaks the expectation that `/admin/X` is "X for any gateway".
Rename it to `/admin/orders/{id}/audit`, or move it to `/audit/orders/{id}`.

### D4. Internal names leak into the public surface (Low, breaking)

- `/quotes/bootstrap` is named after the `system.quote_bootstrap` message. It
  should be `GET /quotes`.
- `/status` returns gateway cache counters (`orders`, `quote_legs`). That is
  gateway internals, not participant state.
- `/history/index-ids` could be `GET /history/indexes`.

### D5. The WebSocket namespace collides with REST (High, breaking)

`/api/v1/events`, `/api/v1/market-data`, `/api/v1/admin/monitor` and
`/api/v1/admin/sim` sit beside REST routes. `/api/v1/admin/sim` is both
`GET` (REST) and a WebSocket endpoint. A reverse proxy that needs to route
WebSocket upgrades separately cannot do so by prefix. The OpenAPI description
already claims `/api/v1/ws/private`, `/api/v1/ws/market-data` and
`/api/v1/ws/admin/monitor` (`openapi_docs.py:80-84`). Make that true: move all
four sockets under `/api/v1/ws/`.

### D6. List envelopes and status vocabularies vary (Medium, breaking)

- **List keys and `count`:** list keys are `orders`, `events`, `legs`,
  `positions`, `daily`, `snapshots`, `index_ids`, `halted`, `gateways`. `count`
  is present on some lists and missing on others (`/orders`, `/positions`,
  `/quotes/legs`).
- **Nesting:** bootstrap returns `orders: {"orders": [...]}`, which is double
  nested. `monitor.snapshot` does the same with `gateways` and `halts`.
- **Status values:** `OrderAccepted.status` is `PENDING | ACKED`; order
  `status` is `NEW | PARTIAL | FILLED | ...`. Admin replies say `APPLIED`,
  `RELOADED` or `DISCONNECTED`, or echo the engine ack. Most are free strings,
  not declared enums.
- **Ids:** `PendingIdResponse.id` for OCO and combo, where `oco_id` and
  `combo_id` would be explicit. For quotes the field silently falls back to the
  symbol.

Proposal: every collection response is `{ "<plural>": [...], "count": n }`,
plus `next_cursor` and `has_more` when paginated. No envelope nests inside
another. Every status field is a declared enum.

### D7. Timestamps come in three forms (Medium, breaking)

- `ts` is ISO-8601 in history rows, the WebSocket envelope and bootstrap.
- `*_ns` fields are epoch nanoseconds in engine payloads.
- History `from`/`to` take ISO or a date, but `/history/index-events` takes
  `from`/`to` as **Unix seconds (float)** (`history.py:712-722`).

Write the rule down ("`*_ns` is epoch ns, `ts` is ISO-8601 UTC, query ranges
are ISO-8601 or `YYYY-MM-DD`") and make `index-events` follow it.

### D8. Price units (Medium, decision needed)

Requests take display prices as JSON floats. Responses are mostly display
prices, but some carry `*_ticks` siblings, and the guide says `order.triggered`
carries prices **only** as integer ticks (`stop_price_ticks`,
`trigger_price_ticks`). Rule to freeze: "every price has a display-unit field;
a `*_ticks` field is optional and supplementary." Separately, decide whether
1.0 keeps JSON floats or moves to decimal strings (see Q1).

---

## 5. Contract and schema (OpenAPI)

### S1. 55 of 61 operations have no response schema (Critical)

Measured on the generated `openapi.json`. Only `POST /orders`,
`DELETE /orders/{id}`, `POST /orders/{id}/replace`, `POST /oco`,
`POST /combos` and `POST /quotes` declare a 2xx schema. Everything else is
`dict[str, Any]` with an example attached.

Consequences:

- Generated SDKs (openapi-generator, openapi-typescript) produce untyped
  objects. The four in-repo web apps hand-maintain their own types
  (`trader-gui/.../types/index.ts`), which already drift independently.
- The response contract cannot be checked by a machine, and there is nothing to
  diff in CI.
- Handlers forward engine replies verbatim (`GET /orders`, `/symbols`,
  `/session`, `/halts`, the admin acks). So **any engine message-spec change is
  an unannounced API change.**

**Fix:** declare response models for every operation. Most of these payloads
are already described in `spec/messages/*.yaml` and generated by msgen, so a
msgen emitter for Pydantic models (or JSON Schema) would cover them
mechanically and keep REST and wire in lockstep. The remainder (history rows,
bootstrap, positions) are gateway-owned and small.

### S2. Auth is not declared as a security scheme (High)

`auth()` takes `authorization` as a required **Header parameter**
(`sessions.py:52-63`), so OpenAPI has no `securitySchemes`. As a result:

- Swagger has no "Authorize" button.
- Generated SDKs make every call take an `authorization` argument.
- A missing header is caught by request validation before `auth()` runs (see
  E2).

Use `fastapi.security.HTTPBearer(auto_error=False)` and raise `401 AUTH`
yourself.

### S3. operationIds are auto-generated (Medium, breaking for SDKs)

Today's ids look like `submit_order_api_v1_orders_post` and
`history_index_snapshots_api_v1_history_index_snapshots_get`. These become SDK
method names forever. Set `generate_unique_id_function=lambda r: r.name` (the
handler names are already good) before 1.0.

### S4. Parameters lack descriptions and bounds (Low)

- Path parameters `order_id`, `oco_id`, `combo_id`, `symbol`, `gid` and
  `index_id` have no descriptions.
- The `/admin/orders` query parameters have no descriptions.
- `GET /admin/orders/{id}?limit=` has no `ge`/`le` bounds (`admin.py:672`).

### S5. Request validation is uneven (Medium)

- `OcoLegRequest` and `ComboLegRequest` have no per-`order_type` validation.
  A `MARKET` leg with a price, or a `LIMIT` leg without one, is accepted with
  `202 PENDING`. The engine does reject it, but asynchronously as an
  `oco.ack`/`combo.ack` on the WebSocket, while the same mistake on
  `POST /orders` is a synchronous 400. (Corrected during WP-API05: the first
  version of this review said the leg "reaches the engine" as if unchecked.)
- `OrderRequest` silently accepts fields irrelevant to the order type
  (`trail_offset` on `LIMIT`, `visible_qty` on `STOP`), although
  `extra="forbid"` shows the intent is strictness. Note that `stop_price` on a
  `TRAILING_STOP` is *not* irrelevant: it is an optional initial stop, which
  the engine otherwise derives from the last trade (`engine/main.py:2008`).
- `IndexRebalanceRequest.reason` is accepted, unbounded, and **dropped**: it is
  never passed to `send_and_await_rebalance` (`admin.py:471-481`).
- `QuoteRequest` has no `client_tag`, unlike orders, OCO and combos.
- `HistoryQuery` (`schemas.py:384`) is unused. It is dead code that predates
  this review; I mention it but have not removed it.

### S6. Version information (Low)

`FastAPI(version="1.0.0")` is hard-coded while the package is 0.65.6. That is
fine as an *API* version, but clients have no way to read the build version.
Expose it in `/status` or as a response header.

---

## 6. Error model and status codes

The normative spec says: "All non-2xx replies MUST use this JSON envelope
shape." Probing the app showed the following.

### E1. The error envelope is not universal (High)

```
GET /api/v1/nope     -> 404 {"detail":"Not Found"}
PUT /api/v1/orders   -> 405 {"detail":"Method Not Allowed"}
```

`main.py:301` registers its handler for FastAPI's `HTTPException`. Routing
raises Starlette's base class, so these responses bypass the envelope.
Unhandled exceptions (500) also have no envelope. **Fix:** register the handler
on `starlette.exceptions.HTTPException`, and add a catch-all `Exception`
handler that returns `500 INTERNAL_ERROR`.

### E2. A missing `Authorization` header gives 400, not 401 (High)

```
GET /api/v1/reference (no header) -> 400 {"error":{"code":"VALIDATION","field":"authorization","reject_code":"MISSING_FIELD",...}}
```

The spec documents `401 AUTH` for a missing key. There is also no
`WWW-Authenticate: Bearer` header. Fixed by S2.

### E3. Validation status is split between 400 and 422 (Medium)

Body and query validation return `400`. History filters, cursors and
index-events return `422` (`history.py` throughout). The spec papers over this
with "`400`, `422`". Pick one; see Q3.

### E4. Engine refusals of admin commands say `403 ROLE_DENIED` (High)

`_require_accepted` (`admin.py:101-113`) maps *any* `accepted: false` ack from
circuit-breaker trigger/resume and the three kill switches to
`403 ROLE_DENIED`. Halting an unknown symbol therefore tells an ADMIN they
lack the role. Session transition, reload and rebalance already use `409` with
a specific code. Do the same here (`HALT_REJECTED`, `RESUME_REJECTED`,
`KILL_SWITCH_REJECTED`) and pass the engine's `reason` through.

### E5. Unknown order uses a generic code (Low)

`GET /orders/{id}` raises a bare string detail (`orders.py:491-493`), so
clients get `code: HTTP_ERROR, reject_code: UNKNOWN`. The admin twin returns
`UNKNOWN_ORDER`. Use `UNKNOWN_ORDER` for both.

### E6. 200 vs 202 has no rule (Medium, breaking)

The spec says 202 means "waiting for the engine to confirm". In practice:

- `POST /admin/session/transition` waits for the ack, returns `APPLIED`, and
  uses **202**.
- Circuit-breaker trigger/resume and the kill switches wait for the ack and
  use **202**.
- `POST /admin/reference/reload` waits and uses **200**.
- `POST /mass-cancel` waits and uses **200**.
- `POST /admin/gateways/{gid}/disconnect` does **not** wait, uses 202, and
  claims `"status": "DISCONNECTED"`.

Rule to adopt: **200 when the response carries the outcome, 202 when it does
not.** Under that rule, `?wait=ack` should return 200 with the verdict.

### E7. A `wait=ack` timeout loses a live order (High)

`submit_order` sends the order (`orders.py:210`) and *then* waits. On timeout
`_await_order_event` raises `503 ENGINE_TIMEOUT` (`orders.py:102-106`). The
order is in the engine, but the client never receives its `order_id`, so it
cannot cancel or track it, and the obvious retry creates a duplicate. Cancel
and amend have the same shape, though there it is less harmful. **Fix:** on an
ack timeout, return `202` with `order_id`, `status: PENDING` and
`ack_timeout: true`. Keep 503 for "could not send at all".

### E8. Smaller error-model items (Low)

- Only the first validation error is reported (`exc.errors()[0]`). Returning
  all of them in an `errors[]` array is cheap and additive, but the field name
  should be fixed now.
- `reason` duplicates `message` in nearly every case. Decide before 1.0
  whether `reason` stays; removing it later is breaking.
- `code` and `reject_code` use near-identical spellings (`RATE_LIMIT` /
  `RATE_LIMITED`, `AUTH` / `AUTH_REQUIRED`, `SYMBOLS_NOT_READY` /
  `SYMBOL_NOT_READY`). This is defensible, since one is the HTTP category and
  the other ALF parity, but the spec should state the rule.
- The spec's error-code table is incomplete. It lacks `HTTP_ERROR`,
  `COMPANY_DB_UNAVAILABLE`, `UNKNOWN_COMPANY` and `INTERNAL_ERROR`, and does
  not enumerate `reject_code` values per endpoint.

---

## 7. Write semantics and reliability

### R1. No idempotency (High, decision needed)

A `POST /orders` that times out at the network layer, or returns 503 (E7),
cannot be retried safely. `client_tag` is explicitly non-unique. Every serious
order-entry API offers one of:

- (a) a client-assigned order id, unique per gateway (FIX `ClOrdID`): a
  duplicate gets `409 DUPLICATE_CLIENT_ORDER_ID` carrying the existing
  `order_id`;
- (b) an `Idempotency-Key` header: the gateway replays the first response for
  the same key within a window.

Either changes the request contract, so it must be decided before 1.0. See Q2.

### R2. `replace` has three defects (Medium)

`replace_order` (`orders.py:380-406`):

- It waits for `order.cancelled` without a `request_tag`, so it cannot race the
  reject topic. If the cancel is rejected (the order filled in the meantime),
  the caller waits the whole `wait_ack_sec` and gets `503`, not a `409` saying
  the order is gone.
- It skips `_check_symbol_ready(body.symbol)`, which every other submit path
  calls. It also does not require the replacement's symbol to match the
  original.
- The replacement's ack is never awaited (see C8).

### R3. Bootstrap positions disagree with `/positions` (High, correctness)

`/bootstrap/{trader,mm}` builds `positions` from the gateway's local fill cache
(`bootstrap.py:192-197`). Those rows have no `avg_cost` and no P&L. The
`/positions` docstring (`reference.py:457-475`) explains why that is wrong: the
cache "reads flat after a gateway restart even though the engine still holds
the position". A trader logging in after a gateway restart therefore sees flat
positions in the bootstrap and real ones on refresh. Bootstrap should reuse
the `/positions` logic.

### R4. `GET /orders` falls back to the cache silently (Medium)

On an engine timeout, `GET /orders` returns the cache with no indication
(`orders.py:441-449`). Bootstrap deliberately does the opposite and returns 503
("stale order state at login is more dangerous than a 503"). Choose one
behaviour. Either return 503, or keep the fallback and add `"source": "cache"`
(or `stale: true`) so a client can tell.

### R5. `/admin/orders` looks authoritative but is not (Medium)

It is served from `_caches` (`engine_client.py:618`). That cache holds only
events this API-gateway process has seen since it started, and drops terminal
orders after `order_retention_sec`. Orders resting from before the gateway
started are missing. The docstring is honest about this; the endpoint name is
not. Provide the engine-authoritative per-gateway listing (C1,
`order.orders_request` for a target gateway). Either rename the cache view or
document it as `source: cache`.

### R6. Reads are not rate-limited, and 429 carries no hints (Medium)

Many reads cost an engine round trip: `/orders`, `/positions`, `/symbols`,
`/session`, `/halts`, `/reference/*` and the bootstraps. They are unthrottled,
so one polling client can load the matching engine. A `429` has no
`Retry-After` header and no `RateLimit-*` headers. Add a separate read bucket.
The headers are additive, but their names should be fixed at 1.0.

---

## 8. Security, operations and documentation

### O1. The API key is logged in plaintext (Medium, security)

`orders.py:47` logs `"rate limit exceeded api_key=%s"` at DEBUG. The bearer key
is the only credential, so this puts the secret in the log server. Log the
credential `description` or a short hash instead.

### O2. `/healthz` always returns 200 (Medium)

`healthz` (`reference.py:551-564`) returns `{"ok": false, ...}` with HTTP
**200**. Container, Kubernetes and load-balancer probes check the status code,
so an unhealthy gateway never fails its probe. Return 503 when `ok` is false.
It also lists `active_gateways` to unauthenticated callers. That is minor
information disclosure; consider moving it to `/status`.

### O3. Smaller operational items (Low)

- `swagger_enabled` defaults to `True`. Fine for a teaching venue, but the
  deployment guide should say how to turn it off for exposed deployments.
- There is no CORS configuration. That is correct if the web apps are always
  served same-origin through a proxy; the spec should state it.
- Keys are static, stored in plaintext, and only change on restart. This is
  documented. Post-1.0 options are hashed keys in config and hot reload.
- `/ws/admin/sim` resolves the role without calling `engine.authenticate`,
  unlike the other three sockets.

### DOC1. The OpenAPI description is wrong about WebSockets (High, quick fix)

`API_DESCRIPTION` lists `/api/v1/ws/private`, `/api/v1/ws/market-data` and
`/api/v1/ws/admin/monitor`. None of these exist. This is the first thing a
Swagger user reads. D5 fixes it by making the paths real.

### DOC2. The WebSocket protocol has no normative spec (High)

The normative spec says WebSocket streams "are documented in the operator
guide and are not repeated here". The operator guide is tutorial-style, and
`/ws/admin/sim` is missing from its table. For 1.0 the WebSocket contract
needs the same rigour as REST:

- the auth frame and close codes;
- the full `type` catalogue per socket, with payload schemas;
- the control frames (`subscribe`, `unsubscribe`, `snapshot`, `resume`) and
  their replies (`subscription`, `resume.rejected`, `trades.reset`, `error`);
- `seq` and `stream_seq` semantics;
- slow-consumer behaviour: per-socket queues of 256/512/64 events, drop
  policy, and `dropped_events`.

An AsyncAPI document would be the natural companion to `openapi.json`.

### DOC3. Stale and internal text in public descriptions (Medium)

- `GET /admin/positions` says `GET /positions` is "served from this process's
  local order/fill cache, no `avg_cost`" (`admin.py:735-737`). That is no
  longer true.
- `/history/index-events` exposes "AR-0.3" and ZMQ details
  (`history.py:737-758`). `/admin/orders` mentions `_caches`, and
  `/admin/positions` mentions `_gateway_positions`.
- The "Prices and time" description points to `tick_decimals` in `/symbols`,
  which read-only keys cannot call.
- Several in-code comments describe compatibility shims ("legacy shape" in the
  subscription ack `symbols`/`channels`, `ws.py:120-124`; `has_more` "mirrors
  the pre-existing contract", `history.py:179-183`). Given the no-backwards-
  compat rule, 1.0 is the moment to drop these shims rather than freeze them.

### DOC4. Three overlapping descriptions will drift (Medium)

The same endpoints are described in the normative spec (2,200 lines), the
operator guide (2,000 lines, with its own reference tables) and the OpenAPI
descriptions. DOC3 shows the drift has already started. Recommendation: make
OpenAPI plus AsyncAPI the single source of truth for per-endpoint detail.
Generate (or test) the spec's endpoint tables from it, and keep the operator
guide to concepts and procedures.

### DOC5. Examples are thin (Medium)

`docs/examples/REST/` contains a 58-line Python client, `demo_info.py`, a
MARKET-order script, and a C client that only does GET. Missing examples:

- a LIMIT order with `wait=ack`;
- amend, cancel and replace;
- handling `reject_code` and retries;
- a pagination loop over `next_cursor`;
- a private WebSocket with `stream_seq` gap detection and snapshot recovery;
- market-data subscribe with `items` and resume;
- one admin flow (halt, then reopen).

The training chapter's exercises are good, but they are curl/Swagger
walkthroughs, not reusable code. The examples should run in CI as a smoke test
so they cannot rot.

### DOC6. Missing 1.0 policy statements (Low)

The compatibility policy (spec §"Compatibility and deprecation policy") is a
good start. Add:

- the **enum-extension rule** generalised to every enum ("new members may be
  added; clients MUST ignore unknown values"). Today it is stated only for
  `cancel_reason`;
- the same rule for unknown **fields**, and for unknown WebSocket `type`
  values;
- that the WebSocket contract is covered by the same versioning;
- what counts as breaking for error `code` values.

### X1. No machine-checked contract guard (High, process)

Nothing stops an accidental breaking change after 1.0. Commit the generated
`openapi.json` (and later `asyncapi.yaml`). Add a test that regenerates the
document and fails on any diff. Optionally run `oasdiff breaking` in CI. This
only pays off once S1 has given the document real response schemas.

---

## 9. Prioritised work packages

**Ordering principle:** anything **breaking** goes before 1.0, because it is
cheap now and costs a `/v2` later. **Additive** work is ranked by user value
and may ship in 1.x. Every renamed path must be updated in the four web apps
(trader-gui, terminal-gui, dash-gui, book-gui), the examples and the docs in
the same WP, with no aliases (no-backwards-compat rule).

### P0: must land before 1.0.0

| WP | Title | Content | Findings | Size |
|---|---|---|---|---|
| **WP-API01** ✅ | Error model unification | **Done 2026-10-30 (uncommitted)**, see §9.2. Envelope for 404, 405 and 500 (Starlette and catch-all handlers). `HTTPBearer` with 401 and `WWW-Authenticate`. One validation status code (Q3). Admin engine refusals become 409 with specific codes. `UNKNOWN_ORDER` on `GET /orders/{id}`. Rule: 200 when the outcome is in the body, 202 when not. Decide `reason` and `errors[]`. Complete code table in the spec. | E1–E8, S2 | M |
| **WP-API02** ✅ | Safe asynchronous writes | **Done 2026-10-30 (uncommitted)**, except `wait=ack` on the structure cancels (Q8), see §9.5. Ack timeout returns 202 with `order_id` and `ack_timeout: true`, never 503. Idempotency (Q2). `wait=ack` for OCO, combo, quote and their cancels. `replace`: race the reject topic, symbol-ready check, same-symbol rule, optional `wait=ack` for the replacement. | E7, R1, R2, C8 | M–L |
| **WP-API03** ✅ | Resource layout freeze | **Done 2026-10-30 (uncommitted)**, see §9.3. WebSockets under `/api/v1/ws/*`. Admin resource scheme (D1). Remove duplicates (D2). One public `GET /session` open to read-only keys, plus `/halts` and symbols metadata (C5). `GET /quotes` replaces `/quotes/bootstrap`. Admin audit path rename (D3). Explicit `oco_id`/`combo_id` in responses. Update all four GUIs, the examples and the docs. Accept and pass through the disconnect `reason` trader-gui already sends (§9.2). | D1–D5, C5, DOC1 | L |
| **WP-API04** ✅ | Typed contract | **Done 2026-10-30 (uncommitted)**, see §9.4. Response models for all operations. Generate engine-payload models from `spec/messages` through msgen; hand-write the gateway-owned ones. List-envelope convention and status enums (D6). Timestamp rule, with `index-events` switched to ISO (D7). Price-unit rule (D8, Q1). Explicit operationIds. Parameter descriptions and bounds. Scrub internal references from descriptions. Drop compatibility shims (subscription-ack legacy fields). | S1, S3, S4, D6–D8, DOC3 | L |
| **WP-API05** ✅ | Correctness fixes | **Done 2026-10-30 (uncommitted)**, see §9.1. Bootstrap positions from the engine, matching `/positions` (R3). `/healthz` returns 503 when unhealthy (O2). Rebalance `reason` bounded and passed through, or removed (S5). Stop logging the API key (O1). OCO and combo leg validation, and rejection of irrelevant `OrderRequest` fields (S5). `GET /orders` cache fallback flagged or turned into a 503 (R4). Each fix gets a reproducing test first. | R3, R4, O1, O2, S5 | S–M |
| **WP-API06** ✅ | Contract guard | **Done 2026-10-30 (uncommitted)**, see §9.6. Commit `openapi.json`; a test regenerates it and fails on diff; optional `oasdiff breaking` in CI. Lands last among the P0s, after WP-API04. | X1 | S |

Suggested order: **05** (small, independent, removes bugs before refactoring)
→ **01** → **03** → **04** → **02** → **06**. WP-API03 and WP-API04 both touch
every route, so run them back to back, with 03 first so models are written
once against the final paths.

### 9.1 WP-API05 outcome (2026-10-30)

Each fix was preceded by a test that reproduced it (22 failing, then passing).

| Item | Decision and change |
|---|---|
| R3 bootstrap positions | `reference.fetch_positions()` is now the one implementation behind `GET /positions` and `/bootstrap/{trader,mm}`. `positions` is a **required** bootstrap field (503 on failure, like `orders`); a cache fallback is exactly the flat-after-restart bug. The cache-based `_positions` helper is gone. The trader-gui already typed the field as the full `Position` row, so no client change. |
| O2 `/healthz` | Returns 503 with the same body when `ok` is false. Only docs consume it. |
| S5 rebalance `reason` | **Removed** from `IndexRebalanceRequest`. `index.rebalance` has no field to carry it, and adding one means a message-spec, pm-index and history-record change for a note nobody reads. Sending it is now a 400 (`extra="forbid"`). No client sent it. |
| O1 API key in log | The rate-limit debug line logs `gateway_id`. No other site logged the key. |
| S5 order/leg fields | One table, `schemas._TYPE_FIELDS` (required plus optional fields per order type, everything else forbidden), now drives `OrderRequest`, `OcoLegRequest` and `ComboLegRequest`. A type that needs a field the leg cannot carry is refused (`ICEBERG` on any leg, `TRAILING_STOP` on a combo leg). Existing error messages are unchanged; trader-gui forms send only valid fields. |
| R4 `GET /orders` | **503 `ENGINE_TIMEOUT`**, not a flagged fallback: consistent with bootstrap and every other engine read, and a flag is a field every client must learn to check. The cached view stays available as the private WebSocket `orders.snapshot`. Trader-gui's refresh already handles the error with a toast. |

**Docs:** normative spec (bootstrap required fields and positions shape,
`POST /orders` field rules, OCO/combo leg rules, `GET /orders`, `/healthz`,
`/positions`) and operator guide (field rules, orders/positions table,
bootstrap partial failures, rebalance body, healthz checklist and
troubleshooting).

**Insights carried forward:**

- **Pre-existing spec error, fixed here:** the normative `GET /orders` section
  documented `symbol`/`status`/`after`/`limit` parameters and a paginated reply
  that never existed. This is more DOC3/DOC4 drift; WP-API04's generated
  contract and WP-API06's guard are what stop it recurring.
- **REST/ALF divergence (not changed):** ALF checks *required* fields only,
  forbids nothing extra, and does no per-type check on OCO legs. The engine's
  combo check differs again (price required for `LIMIT/FOK/STOP_LIMIT/ICEBERG`,
  not `IOC`; no `stop_price` check). REST is now the strictest and the only
  consistent layer. The same mistake can therefore be a synchronous 400 on
  REST and an asynchronous engine reject on ALF; `reject_code` parity holds
  only for the cases `test_cross_transport_rejects.py` covers. Consider moving
  `_TYPE_FIELDS` to `models/` and applying it in ALF and the engine. That is
  outside this review's REST scope, so it is noted rather than scheduled.

### 9.2 WP-API01 outcome (2026-10-30)

Decisions confirmed by Johan: validation is `400` everywhere (Q3), and the
envelope's `reason` field is dropped. `errors[]` was not added; it is additive
and can come in 1.x.

| Item | Change |
|---|---|
| E1 envelope everywhere | The handler is registered on Starlette's `HTTPException` (routing raises the base class), so 404 → `NOT_FOUND` and 405 → `METHOD_NOT_ALLOWED`. A catch-all returns `500 INTERNAL_ERROR` with no internals; Starlette still re-raises, so the traceback is logged. Exception headers (`WWW-Authenticate`, `Allow`) are passed through; they used to be dropped. |
| E2 / S2 auth | `HTTPBearer(auto_error=False)` replaces the header parameter. OpenAPI now has one `http`/`bearer` security scheme on every operation, and no `authorization` parameter. Missing, malformed, empty and unknown keys are all `401 AUTH` with `WWW-Authenticate: Bearer`. `_extract_bearer` is gone. |
| E3 400 everywhere | The history router's 11 `422` sites became one `_invalid(field, message)` helper; every filter error names its parameter (`date`, `from`, `to`, `after`, `event_type`, `types`). The OpenAPI `422` entries became a shared `INVALID_FILTER` 400 example. |
| E4 admin refusals | `_require_accepted(ack, code)` returns `409` with `HALT_REJECTED` / `RESUME_REJECTED` / `KILL_SWITCH_REJECTED`, and the engine's reason as `message`. OpenAPI examples use real engine reason strings. |
| E5 unknown order | `GET /orders/{id}` returns `404 UNKNOWN_ORDER`. |
| E6 200 vs 202 | Order submit/cancel/amend return `200` when `?wait=ack` yields the outcome, else `202` (new `docs.ok_or_acked` documents both). Transition, circuit-breaker trigger/resume, the three kill switches and rebalance are `200`. Disconnect stays `202` and now says `PENDING_DISCONNECT` instead of claiming `DISCONNECTED`. |
| E8 `reason` | Removed from the envelope, `ErrorDetail`, every OpenAPI example and trader-gui's `ApiError`. Engine-event `reason` fields (inside `event`) are engine payload and unchanged. |
| Parity fix | `ENGINE_UNAVAILABLE` now carries `reject_code: INTERNAL_ERROR`, as ALF sends for the same condition; REST said `UNKNOWN`. |

**Clients.** trader-gui's `KillSwitchPanel` and `AdminCircuitBreakersPage`
keyed their "Rejected: <reason>" toast on `ROLE_DENIED`. They now key on the
409 codes (still also on a genuine `ROLE_DENIED`), with new tests that fail
without the fix. Comments in `endpoints.ts`, `types/index.ts` and
`AdminSessionPage.tsx` were updated. The terminal-gui bridge test fixtures
modelled the gateway as `{"detail": ...}` and `422`; they now model the real
envelope and `400`. The example clients don't parse error bodies, so they
needed nothing.

**Tests.** A new `tests/test_api_gateway_errors.py` drives the real
`create_app()` through raw ASGI calls (no httpx in the venv). It is the only
place the app-level handlers, the security dependency and the final status
code are exercised. 23 existing tests encoded the old contract and were updated
to the new one.

**Docs.** In the spec: a complete error-code table (code, status, `reject_code`
and meaning for all 26 codes), the 200/202 rule, the envelope's universality,
`400` for cursors and `fills_limit`, and per-endpoint replies for
orders/cancel/amend, mass-cancel, transition, disconnect, the circuit breaker,
the kill switches and rebalance. Operator guide, training guide and the stats
chapter were updated to match.

**Insights carried forward:**

- **Spec drift again** (more DOC3/DOC4). In blocks touched here, the spec
  documented `202` for `mass-cancel` (always `200`) and a `reason` argument on
  `mass-cancel` that the request model rejects. It also called the halt
  `level` required (it is optional) and still listed rebalance's `reason`,
  which WP-API05's doc pass missed. All fixed. The remaining per-endpoint
  tables are not trustworthy line by line, which strengthens the case for
  WP-API04/06 generating or testing them from OpenAPI.
- **New finding, not fixed (scope):** trader-gui's `disconnectGateway` sends
  `{ reason }`, but `POST /admin/gateways/{gid}/disconnect` has no body
  parameter, so the note is silently dropped. The engine message can carry a
  reason (`send_disconnect(gid, "admin disconnect")`). Fold it into WP-API03,
  which rewrites the admin URLs anyway: accept an optional `reason` body and
  pass it through.
- **Starlette's `Allow` header** names only the methods of the first route
  matched at a path (`PUT /orders` reports `Allow: POST`, not `GET, POST`).
  This is framework behaviour, not ours; noted, not worked around.
- **ALF's `ENGINE_UNAVAILABLE` mapping** is in `alf_gwy/protocol.py`, while
  REST's lives in `main._HTTP_REJECT_CODES`. A shared table would prevent the
  next drift; that belongs with the ALF/REST consistency note in §9.1.

### 9.3 WP-API03 outcome (2026-10-30)

Decision confirmed by Johan: the D1 resource-plus-action scheme (Q4). The new
capabilities D1 sketches (market halt, reopen, per-gateway orders, price
level, admin quote cancel) remain WP-API07; this WP moved and removed what
exists.

| Before | After |
|---|---|
| WS `/events`, `/market-data`, `/admin/monitor`, `/admin/sim` | WS `/ws/private`, `/ws/market-data`, `/ws/admin/monitor`, `/ws/admin/sim` (D5); metric label `events` → `private` |
| `POST /kill-switch` (alias) | removed; `POST /mass-cancel` |
| `GET /quotes/bootstrap` | `GET /quotes` |
| `GET /session` (trading key) + `GET /history/session` | `GET /session`, any key: engine phase + `session_timezone` + `session_date` |
| `GET /halts` (trading key) | any key |
| `GET /history/index-ids` | `GET /history/indexes` |
| `POST /admin/circuit-breaker/trigger` / `resume`, symbol in body | `POST /admin/symbols/{symbol}/halt` / `resume`; body optional (`level`, `reason`) |
| `POST /admin/kill-switch/symbol` | `POST /admin/symbols/{symbol}/cancel-orders` |
| `POST /admin/kill-switch/gateway`, `target_gateway_id` in body | `POST /admin/gateways/{gateway_id}/kill-switch` |
| `POST /admin/kill-switch/global` | `POST /admin/market/kill-switch` |
| `GET /admin/positions?gateway_id=` | `GET /admin/gateways/{gateway_id}/positions` |
| `POST /admin/gateways/{gid}/disconnect` | `…/{gateway_id}/disconnect`, optional `{reason}` now reaches the engine |
| `GET /admin/orders/{order_id}` (audit) | `GET /admin/orders/{order_id}/audit` (D3) |
| `GET /admin/halts`, `/admin/indexes`, `/admin/session/schedule` | removed: `GET /halts`, `/reference/indexes`, `/reference/schedule` |
| `POST /oco`, `/combos`, `/quotes` reply `{id, status, event}` | `{oco_id, status}`, `{combo_id, status}`, `{symbol, quote_id, status}` |

Five request models collapsed into `SymbolHaltRequest {level?, reason?}` and
`AdminNoteRequest {reason?}`. The admin `{symbol}` and `{gateway_id}` path
parameters carry the same load-bearing length bounds (16/32) the body fields
had. The surface is now 56 REST operations plus 4 sockets, pinned exactly by
`tests/test_api_gateway_layout.py`.

**Decisions taken in the WP:**

- **D2, last row (`/symbols` vs `/reference/symbols`): kept both.** They have
  different sources and audiences: an engine round trip resolved per caller
  (MM obligation, `prev_close`) versus the static bundle any key may read.
- **`country` is not in `GET /session`**, although D2 listed it. It is static
  configuration, already in `/reference/schedule`, and no client read it from
  `/history/session`. Leaving it out keeps `/session` at one engine round trip.
- **`session_timezone` comes from the compiled config** (as bootstrap already
  did), not from the stats DB as `/history/session` did. `/session` therefore
  works without pm-stats. The two can differ only if pm-stats recorded under a
  different `locale.session_timezone` than the current config.
- **Read-only bootstrap now carries `session` and `halts`** (best effort, like
  for any key); only positions, orders and fills stay structurally empty.
- **D4's `/status` cache counters** were left alone: they are a response-shape
  question for WP-API04. `GET /history/indexes` still answers
  `{"index_ids": ...}`; envelope keys are WP-API04 (D6).

**A trap found while opening reads to read-only keys:** the engine
upper-cases and clamps to 32 characters the id it echoes in a reply topic
(`_clamp_wire_id`), so a raw API key cannot be the correlation id. The obvious
fix, a fresh id per request, would leak memory: EngineClient creates
per-id state (`_caches[...]`, per-topic sequence counters) for every reply
topic it sees. `sessions.correlation_id()` therefore derives a stable id per
key (`RO` + 16 hex digits of a SHA-256 of the key), bounded by the number of
configured keys, and the key itself never goes on the bus.
`/history/index-events` builds a fresh id per call, but it goes through
IndexClient, which has no such per-id state.

**Clients.**
- trader-gui: every changed endpoint helper, the OCO/combo/quote id handling
  in three forms, the WebSocket URLs, types, comments, and the mocks in eight
  test files.
- book-gui bridge: `/ws/market-data` and `/session`; its history test now
  asserts the path it calls.
- terminal-gui and dash-gui only use endpoints that kept their paths; their
  suites were run anyway.
- trader-gui's own page routes (`/quotes/bootstrap`, `/admin/indexes`) and
  query-cache keys are UI names, not API paths, and were left alone.
- `docs-design/*` design documents are history and were not rewritten.

**Docs.**
- The spec: sections of removed endpoints deleted; headers, index tables and
  anchors regenerated; bodies, replies and access updated.
- The operator guide, training guide, both GUI guides, the risk, index, model
  and admin-console chapters, the reference manual and the ai-traders book
  updated. `mkdocs build` reports no broken anchors.

**Insights carried forward:**

- **Earlier WPs' doc passes missed behaviour statements:** `GET
  /orders/{id}` "returns a plain `{"detail": ...}` body" (WP-API01), the
  transition row's `"status":"PENDING"`, and rebalance "accepts an optional
  `reason`" (WP-API05). The lesson for later WPs: grep the docs for the old
  *behaviour*, not only the old paths.
- **The reference manual's API summary was fiction in places:** a REST `GET
  /market-data` "top-of-book" endpoint that never existed, and `/symbols`
  shown as open to any key. Fixed, and it now points to the spec as the full
  list. This is more evidence for WP-API04/06.

### 9.4 WP-API04 outcome (2026-10-30)

Decided by Johan: keep JSON float prices (Q1, D8 rule frozen in the spec);
generate engine payload models with msgen; validate responses at runtime.
Also done: Q6 (`HistoryQuery` removed).

**What was built:**

- **msgen REST emitter** (`msgen/generators/rest.py`). It writes Pydantic body
  models to `models/generated/rest/<family>.py` for every message and nested
  type, and `make msgen-check` covers them.
  - Body fields are those of `to_dict`, so topic-only fields are absent.
  - A field `to_dict` can omit (`omit_when_none`/`omit_when_empty`) is
    optional; every other field is required (`T | None` where nullable).
  - Descriptions are attribute docstrings (`use_attribute_docstrings`), so
    the output is black-clean without running black.
  - `tests/test_msgen_rest.py` proves the required set matches `to_dict` for
    every message, and that real wire payloads round-trip unchanged.
- **Every one of the 56 operations has a `response_model`** (6 before):
  - engine replies use the generated models;
  - gateway-owned shapes are in `api_gateway/responses.py`, with `Company`
    built from compdb's own column list;
  - shared path parameters are in `api_gateway/params.py`;
  - every router uses `routing.ContractRoute`, which serialises with
    `exclude_unset`, so "omitted rather than null" holds everywhere.
- **D6:**
  - every collection carries `count`;
  - `next_cursor` is always present (`null` on the last page);
  - bootstrap is un-nested (`orders`, `recent_fills`, `halts`, `gateways`,
    `quotes` (was `quote_bootstrap`), `quote_legs`);
  - status fields are `Literal`s;
  - `/history/index-events` always carries `warnings`.
- **D4 `/status`** is now `{gateway_id, gateway_role, gateway_count?}`;
  `SessionCaches.status()` was removed.
- **D7:** `/history/index-events` takes ISO-8601/date `from`/`to` (session
  timezone for bare times), converted to the Unix seconds pm-index wants.
- **OpenAPI:**
  - operationIds are the handler names, unique by test;
  - every parameter is described and bounded (test);
  - no internal references in descriptions (test);
  - every 2xx example is validated against its route's model with an exact
    round-trip (test). Route examples are derived from the engine examples
    through the generated bindings (`*_REPLY` in `openapi_docs.py`).
- **Shims dropped:** the subscription ack's legacy `symbols`/`channels`.

**Real defects the runtime validation exposed** (they would have been 500s or
wrong data):

- **Incomplete engine examples.** 31 of the hand-written examples did not
  match what the routes send. Most hand-written engine examples left out
  fields the engine always writes (`OrderDisplay` lacked 17), and history
  examples still showed `_rowid`, which the queries strip.
- **`/admin/orders` rows** for orders learned from other gateways' events
  lacked `client_tag`. The listing now applies the same `null` default as
  `GET /orders/{id}`, and `status` is optional (absent until a state event is
  seen).
- **`GET /quotes/legs`** answered from the gateway's leg cache with only
  `legs`, while the engine reply also carries `show_requested`, `complete`
  and `recent`. It (and bootstrap) now always asks the engine.

**Testing approach:**

- Handler-level tests skip FastAPI's response validation. So
  `tests/api_gateway_harness.check_contract()` runs it explicitly in the
  history and pagination helpers (real SQLite rows), runtime history,
  bootstrap, routes and admin tests.
- `wire()` builds wire-shaped test doubles through the generated bindings.

**Clients.**

- trader-gui: bootstrap hydration (halts list), types (bootstrap,
  `StatusResponse`, `next_cursor: string | null`), the fills cursor loop, and
  a new `bootstrapHydrate.test.ts`.
- book-gui's cursor loop already handled `null`; terminal-gui and dash-gui
  needed nothing.

**Docs.**

- Spec: a new "Response contract" section freezes the omitted/null, D6,
  time, price and extension rules; plus the pagination, bootstrap, `/status`
  and index-events sections.
- Operator guide (`/status`, cursor end, subscription ack) and training
  guide.

**Insights carried forward:**

- **`event` stays an untyped object** on the order submit, cancel and amend
  replies. Typing it would need a discriminated union of ack and cancel
  events, which the IDL has no variant for. The message reference documents
  each event.
- **The generated models enforce enum values on output.** A gateway older
  than the engine that adds an enum member would answer 500. Both come from
  one spec and release together, but WP-API06's contract snapshot should note
  that enum additions are only additive if gateway and engine deploy
  together.

### 9.5 WP-API02 outcome (2026-10-30)

Decided by Johan: Q2 is an optional `Idempotency-Key` header, not a unique
client order id. D1 (Trading Verification §A.1.4) had made `client_tag` the
non-unique label precisely to avoid FIX `ClOrdID` semantics.

**What was built:**

- **E7, an ack timeout keeps the id.** `?wait=ack` that gives up is now
  `202` with the normal pending body and `ack_timeout: true` on every write
  that waits: order submit, cancel, amend, replace, OCO, combo, quote. It
  used to be `503 ENGINE_TIMEOUT`, which lost the `order_id` of an order
  that had been sent. The client could not cancel or track it, and its
  natural retry made a second order. A `4xx`/`5xx` on a write now always
  means nothing reached the engine; the one exception is replace (below).
- **Q2, `Idempotency-Key`** (`api_gateway/idempotency.py`) on `POST
  /orders`, `/oco`, `/combos`, `/quotes` and `/orders/{order_id}/replace`:
  - A repeat with the same key from the same gateway is not sent; it gets
    the first reply (status and body) with `Idempotent-Replayed: true`.
  - A concurrent duplicate waits on the first attempt.
  - The same key on a different request (path, query or body) is
    `409 IDEMPOTENCY_KEY_REUSED`.
  - A request that failed before reaching the engine is forgotten, and a
    duplicate that was waiting on it makes its own attempt.
  - Keys are kept for `order_retention_sec` (1 h when eviction is off), in
    process, and are lost on a restart.
  - The attempt runs as its own task, so a client disconnecting mid-wait
    cannot cancel an attempt whose order is already out (found in review, see
    below).
  - The header's bounds (1–255) give `400` naming `Idempotency-Key`.
- **`wait=ack` for OCO, combo and quote submits.** The reply is now
  `OcoAccepted`, `ComboAccepted` or `QuoteAccepted` with `accepted`, `reason`,
  `event` and `ack_timeout`. Each matches its ack on `oco_id`, `combo_id` or
  `symbol` (the quote ack always names the symbol; `quote_id` is optional).
- **R1/R2, replace:**
  - The gateway tags its own cancel, so a refused cancel (the order filled
    first, say) is `409 REPLACE_REJECTED` with the engine's `reject_code`. It
    used to wait out the timeout as a 503.
  - The symbol-ready check runs before the cancel; it used to run after, when
    refusing the replacement would leave the caller with no order at all.
  - The replacement must keep the original's symbol (`400`, `field: symbol`).
  - The replacement is seeded into the gateway's order cache like any submit.
  - It takes `?wait=ack` for the replacement's verdict.
  - A cancel whose outcome is unknown stays `503 ENGINE_TIMEOUT`, with no
    replacement sent.

**Found while reviewing the work.** My first idempotency version ran the
attempt inline. A client disconnecting after its order was sent cancelled the
handler, which forgot the key, so the retry the key exists for sent a second
order. Fixed by running the attempt as a task, and pinned by
`test_a_disconnect_mid_wait_still_records_the_reply`.

**Not done: Q8, `wait=ack` on `DELETE /oco`, `/combos`, `/quotes`.** The
engine gives these cancels no ack the gateway can attribute:

- A refused OCO or combo cancel arrives as `oco.ack` / `combo.ack` with
  `accepted: false`, the topic the submit uses, and with no request tag.
- A successful OCO cancel publishes only the legs' `order.cancelled`.

Attributing the outcome needs an IDL change: a `request_tag` on the structure
acks, or dedicated cancel acks. That is engine work, so it is open as **Q8**
below. The cancels still answer `202 PENDING_CANCEL`.

**Clients.**

- trader-gui's order ticket reads `ack_timeout` ("awaiting confirmation",
  now with the order id). It now reports a 503 as a failure, since nothing was
  sent. Before, it called every 503 "awaiting confirmation", including
  `ENGINE_UNAVAILABLE`.
- `OrderAccepted` gains `ack_timeout`, and the test mock is typed.
- The REST example client sends an `Idempotency-Key` and reuses it on a
  connection retry, and prints `ack_timeout`.
- The other GUIs don't use `wait=ack` and needed nothing.

**Docs.**

- Spec: a new "Write outcomes and safe retries" section (the 200 / 202 /
  202+`ack_timeout` / error table, and the key rules); per-endpoint replies
  and errors; the common error codes (`REPLACE_REJECTED`,
  `IDEMPOTENCY_KEY_REUSED`, `ENGINE_TIMEOUT` reworded).
- Operator guide: an ack-timeout and key paragraph with a curl example, the
  `wait=ack` scope, replace, and the implementation notes.
- Example-libraries chapter and the trader GUI guide.

**Insights carried forward:**

- **The GUIs' other "awaiting confirmation" 503 branches are stale.** Amend,
  cancel, replace, bulk and kill switch don't send `?wait=ack`, so a 503
  there is `ENGINE_UNAVAILABLE` (nothing sent). It is reported as "awaiting
  confirmation", and the trader GUI guide's class C table describes it that
  way too. Not changed here, since it was outside the order-ticket path this
  WP altered. Worth a small trader-gui WP.
- **The spec lists `ENGINE_TIMEOUT` for `DELETE /oco` and `/combos`,** which
  never wait. That predates this WP, and I left it.
- Rate limiting runs before the key check, so a replayed duplicate still
  costs a write token. This is deliberate: the limiter protects the gateway,
  not the engine.

### 9.6 WP-API06 outcome (2026-10-30)

**What was built.**

- **`spec/rest/openapi.json`** is the committed v1 contract, byte for byte
  what `/openapi.json` serves (553 kB, indented, so a diff reads per field).
  It sits next to `spec/messages/`, which it is partly generated from.
- **`api_gateway/contract.py`** generates and checks it, mirroring
  `sqlite_schema_docs`. `check` prints a unified diff and says to run
  `make openapi`.
- **Make:** `make openapi` regenerates the contract after a deliberate change.
  `make openapi-check` is part of `make check`/`_check`. Both are listed in
  `make help`.
- **CI:** a "REST contract drift check" step in the code-check job.
  FastAPI is a main dependency, so the `--no-root` job can render the
  document.
- **Tests** (`tests/test_api_gateway_contract.py`):
  - the committed copy matches;
  - the document does not depend on deployment config (the property that
    makes one committed copy valid for every gateway);
  - every path is under `/api/v1/` with version `1.0.0`;
  - drift is reported with a diff and `generate` repairs it;
  - the `main` exit codes are right.

**Decisions:**

- **No oasdiff yet.** The snapshot already turns every change into a
  reviewed diff, and the spec's compatibility policy (now extended) says how
  to judge one. A machine "is this breaking?" check (`oasdiff breaking`
  against the last release tag) is a separate binary. It only becomes
  meaningful once there is a released 1.0 to diff against. That makes it a
  post-1.0 CI addition, not a P0.
- **`scripts/mkbld.sh` does not regenerate the contract,** unlike msgen and
  dbdocs, which it does. A build that regenerates it would silently accept
  any API change, which is the thing the guard exists to stop.
- **The enum caveat from §9.4 is now policy.** A new enum value in a
  response is additive only when gateway and engine deploy together.

**Docs.**

- Spec: the swagger section points at the committed copy; the compatibility
  policy names the contract and spells out what counts as additive.
- Development practice: a "REST contract" standard with the regenerate and
  commit workflow.

**Insight.** The guard is only as good as the contract's precision.
WP-API04's runtime validation and exact-example tests are what make a diff
of this file mean a real wire change.

### P0b: follow-ups from the P0 insights (decided 2026-10-30, before P1)

Johan reviewed the P0 insights (§9.1–9.6) and chose these three, in order,
before WP-API07:

| WP | Name | Scope | From | Size |
|---|---|---|---|---|
| **WP-API14** ✅ | Spec tables vs contract | **Done 2026-10-30 (uncommitted)**, extended to exact per-route error codes (Johan), see §9.7. A test checks each endpoint section of the REST spec (statuses, error codes) against `spec/rest/openapi.json`; fix what it finds (e.g. `ENGINE_TIMEOUT` on `DELETE /oco`, `/combos`). Pulled forward from WP-API09's docs part. | §9.1, §9.2, §9.5 | S–M |
| **WP-API15** ✅ | trader-gui failure wording | **Done 2026-10-30 (uncommitted)**, see §9.8. Amend, cancel, replace, bulk and kill switch call a 503 "awaiting confirmation", but they don't wait, so a 503 means nothing was sent. Reuse WP-API02's ticket fix; correct the trader GUI guide's class C table. | §9.5 | S |
| **WP-API16** ✅ | One order-validation rule | **Done 2026-10-30 (uncommitted)**, see §9.9. Move `_TYPE_FIELDS` to `models/` and apply it in REST, ALF (and BALF) and the engine (the engine is the backstop for combo legs, whose check differs today). One shared reject-code mapping. ALF rejects a field the order type doesn't use, like REST, with the same `reject_code`; ALF spec updated. | §9.1, §9.2, Q9 | M |
| **WP-API17** ✅ | Structure cancel acks (Q8) | **Done 2026-10-31 (uncommitted)**, see §9.13. Engine: `oco.cancel_ack`, `combo.cancel_ack`, `quote.cancel_ack` (new messages, `request_tag` echoed, on success and refusal). REST: `DELETE /oco/{id}`, `/combos/{id}`, `/quotes/{symbol}` take `request_tag` and `?wait=ack` (200 with the verdict, 202 + `ack_timeout` when late), like order cancel; ALF and the GUIs read the new acks. After WP-API09, before 1.0. | Q8, §9.5 | M |

### 9.7 WP-API14 outcome (2026-10-30)

Johan widened the scope from a spec check to **exact per-route error codes**.
The contract had overclaimed errors (every route advertised `ENGINE_TIMEOUT`)
and underclaimed them (`STATS_DB`, `READ_ONLY` and `ENGINE_UNAVAILABLE` were
missing on most routes). So checking the spec against it would only have
moved the error into the spec.

**What was built:**

- **`api_gateway/errors.py`**, one registry of all 27 `error.code` values:
  status, default `reject_code`, meaning and example message.
  - It replaces `main._HTTP_REJECT_CODES`; the values are identical.
  - It feeds the OpenAPI error responses.
  - The spec's common error table is tested against it.
- **`openapi_docs.errors(*codes, examples=...)`** builds one response per
  status, with one named example per code.
  - `ANY_KEY` and `TRADING_KEY` group the codes the auth dependency raises.
  - The old ad-hoc helpers are gone: `COMMON_ERRORS`, `VALIDATION_ERROR`,
    `INVALID_FILTER`, `RATE_LIMITED`, `not_found`, `conflict`,
    `IDEMPOTENCY_CONFLICT`, `REPLACE_CONFLICT`.
  - The app-wide default is now only `INTERNAL_ERROR`.
- **`tests/api_gateway_error_scan.py`** finds each route's reachable codes
  from the source. That works because every code is a string literal.
  - It walks the handler body, plus the functions and package methods it
    calls, transitively.
  - It includes the route's `Depends` dependencies, plus `VALIDATION` when
    the route takes input and `INTERNAL_ERROR` everywhere.
- **`tests/test_api_gateway_error_codes.py`:**
  - each route's declared codes equal the reachable ones, in both
    directions;
  - each status matches the registry;
  - control facts are pinned, so a broken scan can't pass;
  - every `{"code": ...}` literal in the package must be registered.
- **`tests/test_rest_spec_matches_contract.py`** checks each spec section
  against the contract (172 checks):
  - one section per route, including the hidden `/healthz`;
  - the endpoint index lists every section;
  - argument names and Req;
  - success statuses;
  - error codes.

  The four universal codes (`AUTH`, `ENGINE_AUTH`, `ENGINE_UNAVAILABLE`,
  `INTERNAL_ERROR`) are stated once, and each table lists the rest.

**Spec defects found and fixed:**

- **Wrong:**
  - `ENGINE_TIMEOUT` on `DELETE /oco`, `/combos` and `/quotes`, and on the
    gateway disconnect, none of which wait;
  - `ROLE_DENIED` on `POST /orders`;
  - `READ_ONLY` on `/halts`, which is open to any key;
  - `INDEX_ERROR` on rebalance, where a `pm-index` refusal is
    `REBALANCE_REJECTED`.
- **Missing:**
  - `RATE_LIMIT` on cancel, amend, replace and every admin write;
  - `SYMBOLS_NOT_READY` on OCO, combo and quote;
  - `READ_ONLY` on about 20 routes;
  - `VALIDATION` on about 20 routes with bounded parameters.
- **Arguments:** missing rows (`wait`, `Idempotency-Key`; OCO/combo/quote
  `tif`, `client_tag`, `combo_type`, `smp_action`, `quote_id`).
- **Sections:** `GET /admin/sim` had no section or index entry, and the
  three bootstrap sections used their own layout. They are now normalized.

**Contract finding.** `ENGINE_UNAVAILABLE` is reachable on every route a
trading key authenticates on: `authenticate` re-raises it when it cannot hand
the connect message to the engine. The contract never said so before.

**Clients:** none affected. Runtime replies are unchanged, and no client
consumes the OpenAPI document. E2E is 15/15.

**Limits of the scan:**

- It sees only codes written as literals in `api_gateway`. The registry test
  makes an unregistered literal fail. A code computed at runtime would be
  invisible, but none exists.
- Method calls are resolved by name, which over-approximates. The equality
  test would show a false positive as a failure; none appeared.

### 9.8 WP-API15 outcome (2026-10-30)

**The rule.** `ENGINE_TIMEOUT` is the only error that means "sent, outcome
unknown". Every other error, `503 ENGINE_UNAVAILABLE` and `SYMBOLS_NOT_READY`
included, means nothing reached the engine. trader-gui's twelve sites treated
any 503 as "awaiting confirmation". They now share
`isUnconfirmed(err)` (`lib/bulkOutcome.ts`), which the bulk summary uses too.

**What changed in trader-gui:**

- The predicate is used by amend, cancel and bulk cancel, flatten and Flatten
  All, quote and group cancel, session transition, circuit-breaker halt and
  resume, and the kill switch.
- The order ticket was already fixed in WP-API02.
- **The replace dialog** used to say "the order may have already filled …
  nothing was left live" for every 503. That was wrong for an unconfirmed
  cancel, where the original may still be live. It now distinguishes
  `409 REPLACE_REJECTED` ("Replace refused: … nothing was sent") from
  `ENGINE_TIMEOUT` ("the cancel was not confirmed and no replacement was sent;
  the original may still be working").
- **Tests:** 5 new.
  - `unconfirmed.test.ts`: the predicate, and that `ENGINE_UNAVAILABLE` counts
    as failed in a bulk summary.
  - The replace dialog's two outcomes.
  - A flatten refused with 503 is an error toast, not "awaiting".

**Trader GUI guide.**

- Class C now lists only the actions that wait for the engine and so can be
  late: submit (`ack_timeout`), transition, halt, resume and kill switch.
- It says an error on the non-waiting actions means nothing was sent.
- It describes the replace dialog's two outcomes.
- The class D table gains `SYMBOLS_NOT_READY` and `REPLACE_REJECTED` and
  rewords `ENGINE_UNAVAILABLE`.

**Not changed:** the other GUIs. Their 503 handling covers only reads
(company profiles, their own bridges' databases), not command outcomes.

**Insight:** amend, cancel, group and quote cancel, and flatten never wait, so
their "awaiting confirmation" branch can no longer be reached. It is kept,
because the rule is general and those branches become correct automatically
if the calls ever adopt `?wait=ack`.

### 9.9 WP-API16 outcome (2026-10-30)

Implements Q9: ALF is frozen at 1.0, so its validation had to match REST
before release.

**The rule.** `models/order_fields.py` holds one table: which of `price`,
`stop_price`, `visible_qty` and `trail_offset` each order type requires,
allows or refuses. Its `check_type_fields()` returns one verdict:

- `MISSING_FIELD` for a required field that is absent;
- `UNSUPPORTED_FIELD` for a field the type does not use;
- `INVALID_VALUE` for a type the record cannot carry (an ICEBERG OCO leg, a
  TRAILING_STOP combo leg).

Messages are worded in each transport's field names (`LEG1_STOP`,
`LEG0.PRICE`).

**Applied everywhere:**

- **REST:** orders, OCO legs and combo legs. The error type carries the
  verdict, so a forbidden field is now `UNSUPPORTED_FIELD`; it was
  `INVALID_VALUE`, from a message heuristic.
- **ALF:** single orders, OCO legs and combo legs.
- **BALF:** single orders, where a zero field counts as absent. Verdicts are
  `RC_INVALID_FIELD`, BALF's one code for a field error.
- **The engine,** as the backstop for every transport: new orders, OCO legs
  and combo legs.

**Divergences closed:**

| Case | Before | Now, everywhere |
|---|---|---|
| A field the type does not use (`LIMIT` + `TRAIL`) | REST 400; ALF and BALF dropped it silently; engine accepted it | `UNSUPPORTED_FIELD` |
| An OCO leg missing its price or stop | REST 400; ALF forwarded it unchecked to the engine | `MISSING_FIELD` |
| A STOP_LIMIT combo leg without a price | REST 400; ALF and engine accepted it | `MISSING_FIELD` |
| An IOC without a price | REST, ALF and BALF refused it; the engine accepted it | `MISSING_FIELD` |
| An ICEBERG or TRAILING_STOP combo leg | REST refused it; ALF built a leg without the field | `INVALID_VALUE` |
| A missing price at the engine | `PRICE_OUT_OF_RANGE` | `MISSING_FIELD`, as at the gateways; a present non-positive price is still `PRICE_OUT_OF_RANGE` |

**Reject-code mapping.** The transports name their errors differently by
design (`RATE_LIMIT` versus `RATE_LIMITED`), so one literal table cannot serve
both. A parity test pins every condition both report to the same
`reject_code`, which is what prevents drift.

**Found along the way:**

- **ALF built every combo leg with `tick_decimals=2`**, whatever the symbol.
  The engine does not read the field, but the wire record told every reader
  the wrong scale for a non-2-decimal leg's ticks. Fixed: the leg carries its
  own symbol's scale. A test fails without the fix.
- **ALF spec drift:** the spec said combo legs had no `LEGi.STOP`, but the
  gateway always parsed it. Corrected; STOP and STOP_LIMIT combo legs are
  documented.
- **A false pass in my own first test lines:** they lacked
  `TYPE=OCO`/`TYPE=COMBO`, so they failed for an unrelated missing field.
  Fixed, and the leg tests now also assert ALF's message names the leg.

**Producers checked:** the AI traders, the ALF console and trader-gui's
forms all send only the fields each type uses. The orders tool, the board,
terminal-gui, the MM bot (quotes only) and the simulator place no orders
through this path.

**Tests:**

- `test_order_fields.py`;
- parity cases in `test_cross_transport_rejects.py` (single, OCO, combo, and
  the reject-code mapping);
- BALF forbidden fields;
- engine backstop cases (IOC, STOP, extra field, OCO leg, STOP_LIMIT combo
  leg);
- the combo tick scale.

**Docs:** the ALF spec (price-field rule, OCO and combo leg tables), the BALF
spec (field rule, `RC_INVALID_FIELD`), the REST spec, and the engine
order-flow chapter.

**Insight.** The engine's order book still handles a priceless IOC
(`price_limit=None`). No validated path can produce one now; it is left in
place as unreachable defensive code.

### 9.10 WP-API07 outcome (2026-10-30)

C1's admin gaps are closed. These seven routes follow the D1 scheme; the
gateway kill switch gains `?symbol=`:

| Capability | Route | Engine |
|---|---|---|
| Market halt / resume | `POST /admin/market/halt`, `/resume` | `risk.circuit_breaker_halt_all` / `_resume_all` |
| Reopen a symbol | `POST /admin/symbols/{symbol}/reopen` (`price`, `dry_run`, `reason`) | `risk.force_uncross`, matched on `command_id` |
| Gateway kill switch, one symbol | `POST /admin/gateways/{gateway_id}/kill-switch?symbol=` | `risk.kill_switch_gateway` + `symbol` |
| Pull another gateway's quote | `DELETE /admin/gateways/{gateway_id}/quotes/{symbol}` | `risk.kill_switch_gateway` + `symbol` + `quotes_only` |
| Engine-authoritative orders (R5) | `GET /admin/gateways/{gateway_id}/orders` | `order.orders_request` for the target |
| Price-level drill-down | `GET /admin/symbols/{symbol}/orders?price=` | `order.price_level_orders_request` |
| Daily volume | `GET /admin/market/volume` | `system.volume_request` |

**Decided by Johan: extend the admin message rather than impersonate.**

- **What the CLI did:** `pm-admin-cli`'s `kill --sym` and `qcancel` sent the
  *target's* own `risk.kill_switch` / `quote.cancel`.
  - The audit trail then named the target, not the operator.
  - The engine refused while the target was disconnected, which is exactly
    when an operator needs these.
- **The message change:** `risk.kill_switch_gateway` gained optional `symbol`
  and `quotes_only` (both echoed on its ack), and `AdminActionScope` gained
  `quotes_only`. Both changes are additive.
- **The engine:** the handler scopes by symbol and skips non-quote orders.
  Only the ADMIN caller must be connected.
- **The CLI:** `kill` and `qcancel` against *another* gateway now use the
  admin message. On the caller's own gateway they keep the self-service
  messages.

**Design notes:**

- **Response shapes:**
  - The per-gateway listing has the same shape as `GET /orders`. The wire
    reply's `gateway_id` is topic-only, and the path names the gateway.
  - Volume and price levels add `count` (D6).
- **The reopen `price`** is refused if it is off the tick grid
  (`TICK_VIOLATION`), as on order entry, and is `SYMBOLS_NOT_READY` before
  the symbol's precision is loaded.
- **Two new registry codes:**
  - `REOPEN_REJECTED` (409);
  - `QUERY_REJECTED` (409): an engine-refused admin query, for example an
    unknown symbol on the price-level drill-down.
- **Correlation:** reopen and the kill switches match on `command_id`.
  Market halt and resume carry none, so they match by topic, like the
  existing roster reads.
- **R5:** `/admin/orders` stays the gateway's read model. Its description,
  the spec and the operator guide point at the new authoritative listing.

**Tests:**

- `test_api_gateway_admin_parity.py` (14 tests): every route through the
  real app with response validation, including the ADMIN requirement, the
  409 paths and the tick check.
- `test_engine_admin_scoped_cancel.py`: symbol scope, quotes only, a
  disconnected target, and the audit naming the admin.
- The CLI routing test.
- The layout, error-code-scan, contract and spec-match guards cover the rest.

**Docs:** REST spec sections, index and codes; operator guide (endpoint
tables, kill-switch section); admin console guide (`kill`/`qcancel`, command
reference); message reference (generated).

**Not in scope:** `book --sym` is still WebSocket-only, and is WP-API10's
REST market-data snapshot.

### 9.11 WP-API08 outcome (2026-10-30)

**Chapter, not AsyncAPI.** A new normative chapter,
`protocols-and-clients/part-2-specifications/070-websocket.md` ("WebSocket API
Reference"), sits beside the REST spec. It is held to the code by
`tests/test_ws_spec_matches_code.py`, the approach WP-API14 used for REST. An
AsyncAPI document could be generated from it later; it would be a second
artifact to keep in step, for no client in the project.

**What it specifies (DOC2):**

- **Streams:** the four streams, with access and per-socket queue sizes
  (256 / 512 / 512 / 64).
- **Connecting:** the `{api_key}` first frame within 5 s; each auth check and
  its failure (an `error` frame or not, then close `1008`). `1008` is the only
  code the gateway itself sends.
- **Envelope and sequencing:**
  - `seq` per topic (key on `topic`, not `type`);
  - `stream_seq` contiguous per private stream;
  - a dropped event still consumes its number;
  - counters restart with the process.
- **Event types:** the `type` derivation rule and its exceptions.
- **Flow control:** drop-not-block, `dropped_events` in `/healthz` and
  metrics, gap detection.
- **Private:** opening frames, the 19-type catalogue with message-reference
  links for payload schemas, and snapshot-based recovery.
- **Market data:**
  - channels (subscribable, plus always-on session, circuit_breaker and
    news) and their event types;
  - control frames (flat and items forms, `resume_from`) and server control
    frames;
  - both rejection-reason vocabularies;
  - recovery (snapshot channels self-heal; trades replay for
    `market_data_cache_sec`, otherwise `trades.reset`).
- **Admin monitor:** snapshot, `admin.action`, other topics by the type rule,
  no replay.
- **`/ws/admin/sim`** (DOC2's missing socket): `sim.snapshot`, `sim.state`
  and `sim.value`, unnumbered.

**1.0 policy statements (DOC6),** in the shared compatibility policy:

- the WebSocket contract is part of v1;
- clients MUST tolerate unknown fields, unknown enum values (any enum),
  unknown WebSocket `type`s and unknown error codes;
- what counts as breaking for error codes.

**The guard** (12 tests) derives each catalogue from the code:

- endpoints and queue sizes (AST);
- the auth timeout;
- close codes;
- the type exceptions via `websocket_type`;
- the private catalogue from `PRIVATE_PREFIXES`;
- channels from `MarketDataChannel` / `ALWAYS_ON_CHANNELS`;
- forwarded market-data types, complete over every registry topic;
- control actions;
- both reason vocabularies;
- every emitted frame `type`;
- the sim socket.

A mutation check (dropping a catalogue row, changing a queue size, dropping a
reason or channel, a wrong topic) failed it every time.

**Corrections made while writing.** The first draft named the config key
`market_cache_sec` (it is `market_data_cache_sec`) and claimed a `1001` close
at shutdown. The gateway sends none; the server process does. Both were
fixed, and the claim was replaced by what the gateway actually does.

**Wiring:**

- the REST spec's intro and appendix now point to the chapter instead of the
  operator guide;
- the operator guide's WebSocket section is now a guided tour that links
  the normative chapter;
- the book manifest and nav are regenerated;
- every anchor in the chapter resolves in the built site.

### 9.12 WP-API09 outcome (2026-10-30)

**Q8 decided before this WP** (see the Q table): structure cancel acks go in
before 1.0, as dedicated messages, in WP-API17.

**Examples (DOC5).** `docs/examples/REST/python` gains five scenarios, each a
bounded run that exits non-zero when what it demonstrates does not hold:

| Script | Shows |
|---|---|
| `order_lifecycle.py` | LIMIT with `wait=ack` and an `Idempotency-Key`; a retry that returns the same order; amend; replace; cancel; a `TICK_VIOLATION` refusal |
| `history_pages.py` | Following `next_cursor`; `STATS_DB` on a fresh venue |
| `private_stream.py` | Snapshot, contiguous `stream_seq`, reconnect-and-resnapshot on a gap |
| `market_data.py` | `items` subscribe, per-topic `seq`, trades `resume`, snapshot healing |
| `admin_halt_reopen.py` | Halt, price-level orders, dry-run reopen, reopen or resume |

**The client.** `api_gateway_client.py` gains:

- `patch_json`, `delete_json`, and `get_json` with query params;
- `pages()`, which follows the cursor;
- two error types. `ApiError` carries `status`, `code`, `reject_code` and
  `field` from the envelope, and means nothing was sent. `ApiUnreachable`
  means no answer, so the outcome is unknown. Both subclass `RuntimeError`,
  so existing callers keep working, and `submit_market_order.py` now retries
  only on `ApiUnreachable`.

The client and the REST scripts remain stdlib-only; the two WebSocket
examples need `websockets`.

**Run in CI.** `tests/test_examples_e2e.py` runs every script as a reader
would (a subprocess from its own directory) against the bundled `mini`
exchange, in `make test-e2e`.

- The `mini` exchange startup moved from the monitor test to a shared
  `tests/e2e_exchange.py` (`running_exchange()`).
- Running two e2e modules exposed a race: `pm-opctl-cli stop` returns before
  `pm-monitor` frees its ports, so the next module skipped. The teardown now
  waits for every port. e2e is 21/21, nothing skipped.

**Found while making them run:**

- **The lifecycle example's first pricing guessed.** s10-basic has no
  `prev_close`, so the fallback priced a BUY at 99.00 against a 22.98 ask, and
  the order filled at once.
  - The scripts take `--price`, and stop with a clear message rather than
    guess when no `prev_close` exists.
  - Each step now fails the script unless the engine accepted it, so a
    silent failure cannot pass the test.
  - Without a REST book snapshot (WP-API10), a REST-only client cannot find
    the touch itself.
- **The trade payload field is `quantity`,** not `qty`.

**Single source of docs (DOC4).**

- Spec tables tested against OpenAPI: done in WP-API14.
- The operator guide's API chapter went from 2,092 to 780 lines.
  - **Removed** (each now a link to the REST or WebSocket reference): the
    endpoint, payload, query-parameter, reply-shape and error tables, the
    JSON reply examples, the per-route admin and history sections, the
    envelope, sequencing, correlation, subscription and resume detail, and
    the closing "Reference" index.
  - **Kept and rewritten as operator concepts:**
    - what each endpoint group depends on;
    - order entry in practice (per-type rule, `wait=ack` and `ack_timeout`,
      idempotency) and tick precision with `SYMBOLS_NOT_READY`;
    - live versus static reference data, `config_version`, reload limits;
    - history's `pm-stats` and `pm-index` dependencies;
    - bootstrap partial failure;
    - the ADMIN role source, the three kill-switch scopes, reopen, and live
      risk state;
    - the `pm-index` bridge and `admin.action`;
    - the read model versus the authoritative views, and cache retention;
    - a WebSocket table plus what operators need: drops, replay window, no
      monitor replay, seq restart.
- **Stale facts the trimmed text carried** (now gone):
  - `/quotes/legs` "served from the local cache";
  - `/status` open to any key;
  - an `admin.action` list without `auction.reopen`;
  - "not exposed" claims that WP-API07 made false;
  - index-events `from`/`to` as Unix seconds.
- **Anchors:** every in-page anchor and the five inbound anchors still
  resolve. The one inbound `#pagination` link now points to the spec's
  pagination contract.
- **DOC3** needed nothing: WP-API04 and WP-API06 already removed the stale
  and internal text.

### 9.13 WP-API17 outcome (2026-10-31)

Implements Q8 as decided: dedicated cancel acks, before 1.0.

**Engine and IDL:**

- New messages `oco.cancel_ack`, `combo.cancel_ack` and `quote.cancel_ack`.
  Each carries the structure's id, `accepted`, `reason`, `reject_code`
  (`ORDER_NOT_FOUND`, `ORDER_ALREADY_TERMINAL`, or the gateway-status codes),
  the echoed `request_tag` and `cancelled_order_ids`.
- The three cancel requests gained an optional `request_tag`.
- The engine answers **every** structure cancel with exactly one cancel ack,
  accepted or refused, and no longer uses the submit acks (`oco.ack`,
  `combo.ack`, `quote.ack`) for cancels. Combo still publishes
  `combo.status: CANCELLED`, and OCO its leg cancels.
- `reject_code` is a string, because the IDL has no shared enum type. A test
  pins the engine to `order.ack`'s vocabulary.

**REST:**

- `DELETE /oco/{id}`, `/combos/{id}` and `/quotes/{symbol}` take
  `request_tag` and `?wait=ack`, exactly as order cancel does:
  - `202 PENDING_CANCEL` by default;
  - `200` with `ACKED`, or `REJECTED` and a `reject_code`;
  - `202` with `ack_timeout` when late.
- Replies are `OcoCancelAccepted`, `ComboCancelAccepted` and
  `QuoteCancelAccepted`. The `*CancelPending` models are gone.
- The contract was regenerated, and the spec sections and the
  write-outcomes scope updated.

**Consumers:**

- **ALF (frozen):** the gateway renders the new acks as the frames ALF
  always sent. A refusal is `OCO_ACK`/`COMBO_ACK` with `ACCEPTED=FALSE`;
  every quote cancel is `QUOTE_ACK`; an accepted OCO or combo cancel has no
  frame, as before. A frame-parity test pins this. ALF clients, including
  the AI traders, see no change.
- **Private WebSocket:** the three types are routed to the caller. The
  WebSocket chapter's catalogue and its guard test are updated.
- **trader-gui:**
  - A refused cancel now reads "Cancel of OCO X refused". Before, it read
    "OCO X rejected", like a failed submission.
  - A quote cancel now reads "Quote AAPL cancelled". Before, a successful
    cancel read "Quote ... accepted".
  - The quote list refreshes on either outcome.
- **The rest:**
  - `pm-alf-console` subscribes to and renders the new acks;
  - `pm-admin-cli`'s `quote_cancel` waits for `quote.cancel_ack`;
  - audit replay has the three kinds, templates and cancel-request links
    (exact by `request_tag`, `STRONG` by id).

**Bugs the old wire caused, fixed by it:**

- **MM bot.** A successful quote cancel's `quote.ack` (`accepted: true`)
  matched the bot's `quote_id`, so the bot set `QUOTING` and logged
  "quote ACK" for a quote it had just withdrawn. A refused cancel (empty
  `quote_id`) fell through to the submit FIFO and was attributed to the next
  quote it had sent. The bot no longer receives either.
- **pm-stats.** It recorded a refused structure cancel as `OCO_REJECT` /
  `COMBO_REJECT` / `QUOTE_REJECT` (a submit rejection), and a quote cancel
  as `QUOTE_ACK`. It now records neither. The legs' `order.cancelled`
  events remain.

**New finding, not fixed (engine, outside this WP):**

- `_handle_oco_cancel` does not check that the caller owns the pair.
- `_oco_groups` is keyed by the client-chosen `oco_id` alone. So one gateway
  can cancel another's OCO by naming its id, and two gateways using the same
  `oco_id` collide.
- Combos check ownership; OCOs should too, and the key should be
  `(gateway_id, oco_id)`. This needs its own small engine WP before 1.0.

**Tests:**

- engine (10);
- ALF frame parity (5);
- ALF console (3);
- REST (5);
- audit links (4);
- trader-gui (4);
- updated expectations in the combo, OCO, CLI and msgen-count tests.

### P1: strongly recommended for 1.0 (additive, but defines "complete control")

| WP | Title | Content | Findings | Size |
|---|---|---|---|---|
| **WP-API07** ✅ | Admin parity with `pm-admin-cli` | **Done 2026-10-30 (uncommitted)**, see §9.10. Market halt/resume (`halt_all`/`resume_all`). Symbol reopen through force-uncross, with `price` and `dry_run`. Gateway kill switch scoped by symbol. Admin quote cancel for another gateway. Engine-authoritative `GET /admin/gateways/{id}/orders`. Price-level drill-down. Daily volume. Fits the D1 scheme. | C1, R5 | M |
| **WP-API08** ✅ | WebSocket normative spec | **Done 2026-10-30 (uncommitted)**, see §9.11. Normative WebSocket chapter (or AsyncAPI): auth, close codes, full event catalogue with schemas, control frames, seq and recovery semantics, slow-consumer and drop policy. Include `/ws/admin/sim`. Add the enum and unknown-field extension rules and the 1.0 stability statement (DOC6). | DOC2, DOC6 | M |
| **WP-API09** ✅ | Examples and single source of docs | **Done 2026-10-30 (uncommitted)**, see §9.12. A Python client covering the order lifecycle, errors and retries, pagination, private-WebSocket recovery, market-data subscribe/resume and one admin flow. Examples run in CI. Spec endpoint tables generated from or tested against OpenAPI; the operator guide trimmed to concepts. | DOC4, DOC5 | M |

### P2: can follow in 1.x (all additive)

| WP | Title | Content | Findings | Size |
|---|---|---|---|---|
| **WP-API10** | Market-data REST snapshots | `GET /book/{symbol}` (L1/L2), a venue-wide top-of-book list, last trade. | C4 | S–M |
| **WP-API11** | Structure and order queries | `GET /oco[/{id}]`, `GET /combos[/{id}]`, filters and pagination on `GET /orders`, `GET /orders/{id}` falling back to history after eviction. | C6, C7 | M |
| **WP-API12** | Index and classroom control | Index corporate actions and constituent add/delist. News inject/confirm/retract. Simulator commands. | C2, C3 | M |
| **WP-API13** | Operations polish | Read rate-limit bucket, `Retry-After` and `RateLimit-*` headers, `ETag`/`If-None-Match` on `/reference*` (keyed on `config_version`), `X-Request-ID` echo, build version exposed, hashed keys and key reload, swagger-off guidance. | R6, O3, S6 | M |

---

## 10. Decisions needed from you

| # | Question | Recommendation |
|---|---|---|
| Q1 | Prices: keep JSON floats plus `tick_decimals`, or move to decimal strings? | **Keep floats.** The tick grid is enforced at the edge (`TICK_VIOLATION`), every client already uses floats, and strings would be a large cross-GUI change for little benefit in a teaching venue. Freeze the D8 rule instead. |
| Q2 | Idempotency: client order id, or `Idempotency-Key` header? | **Decided 2026-10-30: `Idempotency-Key` header** (Johan). D1 had deliberately named the order label `client_tag` and made it non-unique to avoid FIX `ClOrdID` semantics, which a unique `client_order_id` would have reintroduced; the header also covers OCO, combo, quote and replace, not only order submit. See §9.5. |
| Q3 | Validation status: 400 or 422? | **400 everywhere.** Most routes already use it, it matches the "malformed request" semantics of ALF parity, and only the history router needs to change. |
| Q4 | Adopt the admin scheme in D1 (resource plus action), or keep RPC style but make it consistent? | **D1 scheme.** It also gives WP-API07's new endpoints an obvious home. |
| Q5 | Is admin parity (WP-API07) a 1.0 blocker? | **Yes, if 1.0 is marketed as "full operator control over REST".** If not, it is purely additive and can be 1.1. |
| Q6 | Remove `HistoryQuery` (`schemas.py:384`, unused, existing dead code)? | Remove it in WP-API04. |
| Q8 | `wait=ack` for the OCO, combo and quote cancels: how should the outcome be attributable? | **Decided 2026-10-30 (Johan): before 1.0, with dedicated cancel acks.** New `oco.cancel_ack`, `combo.cancel_ack` and `quote.cancel_ack` messages echo a `request_tag` on success and refusal, so the submit acks keep meaning "submit outcome". Scheduled as WP-API17, after WP-API09. |
| Q9 | Is ALF part of the 1.0 compatibility promise, and must it validate like REST? | **Decided 2026-10-30 (Johan): ALF is frozen at 1.0.** A field the order type doesn't use is rejected, like REST. One per-type rule lives in `models/` and is applied by REST, ALF and the engine. It must land before 1.0, because tightening ALF later would break ALF clients. Scheduled as WP-API16. |