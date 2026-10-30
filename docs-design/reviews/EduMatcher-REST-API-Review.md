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
| **WP-API02** | Safe asynchronous writes | Ack timeout returns 202 with `order_id` and `ack_timeout: true`, never 503. Idempotency (Q2). `wait=ack` for OCO, combo, quote and their cancels. `replace`: race the reject topic, symbol-ready check, same-symbol rule, optional `wait=ack` for the replacement. | E7, R1, R2, C8 | M–L |
| **WP-API03** | Resource layout freeze | WebSockets under `/api/v1/ws/*`. Admin resource scheme (D1). Remove duplicates (D2). One public `GET /session` open to read-only keys, plus `/halts` and symbols metadata (C5). `GET /quotes` replaces `/quotes/bootstrap`. Admin audit path rename (D3). Explicit `oco_id`/`combo_id` in responses. Update all four GUIs, the examples and the docs. Accept and pass through the disconnect `reason` trader-gui already sends (§9.2). | D1–D5, C5, DOC1 | L |
| **WP-API04** | Typed contract | Response models for all operations. Generate engine-payload models from `spec/messages` through msgen; hand-write the gateway-owned ones. List-envelope convention and status enums (D6). Timestamp rule, with `index-events` switched to ISO (D7). Price-unit rule (D8, Q1). Explicit operationIds. Parameter descriptions and bounds. Scrub internal references from descriptions. Drop compatibility shims (subscription-ack legacy fields). | S1, S3, S4, D6–D8, DOC3 | L |
| **WP-API05** ✅ | Correctness fixes | **Done 2026-10-30 (uncommitted)**, see §9.1. Bootstrap positions from the engine, matching `/positions` (R3). `/healthz` returns 503 when unhealthy (O2). Rebalance `reason` bounded and passed through, or removed (S5). Stop logging the API key (O1). OCO and combo leg validation, and rejection of irrelevant `OrderRequest` fields (S5). `GET /orders` cache fallback flagged or turned into a 503 (R4). Each fix gets a reproducing test first. | R3, R4, O1, O2, S5 | S–M |
| **WP-API06** | Contract guard | Commit `openapi.json`; a test regenerates it and fails on diff; optional `oasdiff breaking` in CI. Lands last among the P0s, after WP-API04. | X1 | S |

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

### P1: strongly recommended for 1.0 (additive, but defines "complete control")

| WP | Title | Content | Findings | Size |
|---|---|---|---|---|
| **WP-API07** | Admin parity with `pm-admin-cli` | Market halt/resume (`halt_all`/`resume_all`). Symbol reopen through force-uncross, with `price` and `dry_run`. Gateway kill switch scoped by symbol. Admin quote cancel for another gateway. Engine-authoritative `GET /admin/gateways/{id}/orders`. Price-level drill-down. Daily volume. Fits the D1 scheme. | C1, R5 | M |
| **WP-API08** | WebSocket normative spec | Normative WebSocket chapter (or AsyncAPI): auth, close codes, full event catalogue with schemas, control frames, seq and recovery semantics, slow-consumer and drop policy. Include `/ws/admin/sim`. Add the enum and unknown-field extension rules and the 1.0 stability statement (DOC6). | DOC2, DOC6 | M |
| **WP-API09** | Examples and single source of docs | A Python client covering the order lifecycle, errors and retries, pagination, private-WebSocket recovery, market-data subscribe/resume and one admin flow. Examples run in CI. Spec endpoint tables generated from or tested against OpenAPI; the operator guide trimmed to concepts. | DOC4, DOC5 | M |

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
| Q2 | Idempotency: client order id, or `Idempotency-Key` header? | **Client order id** (`client_order_id`, optional, unique per gateway among live and retained orders; a duplicate returns 409 with the existing `order_id`). It is exchange-native (FIX `ClOrdID`), serves as correlation too, and needs no response cache. Keep `client_tag` as the non-unique label for ALF parity, or decide to fold the two together. |
| Q3 | Validation status: 400 or 422? | **400 everywhere.** Most routes already use it, it matches the "malformed request" semantics of ALF parity, and only the history router needs to change. |
| Q4 | Adopt the admin scheme in D1 (resource plus action), or keep RPC style but make it consistent? | **D1 scheme.** It also gives WP-API07's new endpoints an obvious home. |
| Q5 | Is admin parity (WP-API07) a 1.0 blocker? | **Yes, if 1.0 is marketed as "full operator control over REST".** If not, it is purely additive and can be 1.1. |
| Q6 | Remove `HistoryQuery` (`schemas.py:384`, unused, existing dead code)? | Remove it in WP-API04. |
