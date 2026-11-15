# pm-api-gwy Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/api_gateway/` at `b51dece5` (v0.79.0), 14 839
lines: `engine_client.py` (1 120 lines, engine sockets, waiters, event
fan-out, order cache), `main.py` (571, app factory and lifespan),
`routers/ws.py` (638, the three WebSockets), `routers/orders.py` (1 068),
`routers/admin.py` (1 151), `routers/bootstrap.py` (595),
`routers/reference.py` (718), `routers/clearing.py` (1 181),
`routers/history.py` (918), `routers/market.py` (201), `caches.py` (203),
`events.py` (200), `market_cache.py` (281), `idempotency.py` (185),
`sessions.py` (175), `metrics.py` (176), `index_client.py` (242),
`sim_client.py` (141), `config.py` (380), `translate.py` (161),
`clearing_scope.py` (59), `rate_limit.py` (54), `params.py` (72),
`routing.py` (22), `errors.py` (221), `contract.py` (93), `schemas.py` (723)
and `responses.py` (1 022) (the last two are generated or declarative and were
read for field names only). `openapi_docs.py` (2 266) is example and
description text and was read where a route's text is cited below. The engine
handlers that answer the gateway (`_handle_gateway_connect`,
`_expire_silent_gateways`, `_handle_cancel`, `_handle_amend`,
`_handle_orders_request`, `_handle_position_request`) were read where they
decide its behaviour. They were not reviewed as code of their own. So were
trader-gui's `useOrderStore.ts` and `WebSocketManager.ts`, which consume the
private stream.

**Focus:** internal correctness, restart and reconnect behaviour, WebSocket
fan-out and backpressure, performance, and whether the comments, the operator
guide chapter (`operator-guide/part-5-gateways/050-api-gateway.md`) and the
WebSocket spec (`protocols-and-clients/part-2-specifications/070-websocket.md`)
say what the code does. The REST *contract* is not re-reviewed.

**Previous work:** the contract review `EduMatcher-REST-API-Review.md`
(WP-API01–17, 2026-10-30, plus WP-API10 and the OCO ownership fix), the
admin-sink work of 2026-11-07/12 (receive batching, the admin feed without
public market data, queue 32 768, batched admin frames, the separate
`monitor` instance), the REST load dashboard metrics (2026-11-08), K11
(de-authenticate on `system.startup_recovery`) and Trader-GUI review H2/H3
(venue-wide trade resume). Their fixes are in place and are not repeated
here.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced against the tree at `b51dece5`. Most used the
bundled `mini` exchange (`pm-config-deploy --example s10-basic`,
`pm-opctl-cli start mini`) in a scratch data directory, driven over real HTTP
and WebSocket from a script. The rest drove the real `create_app()` through
`tests/api_gateway_harness.py`. *(measured)* means timed on this host (Xeon
W-2295) by feeding real engine frames (`make_ack_msg`/`make_fill_msg` of real
`Order`s) through `EngineClient._handle_events`: 200 000 orders × 2 events
over 300 gateways and 30 symbols, which is the open-burst size noted in the
2026-11-07 sim run. The other findings are by inspection, with line numbers
given.

Status: **Done, uncommitted (2026-11-15).** All eight WPs implemented; Q1–Q5 taken as recommended (a), with one deviation in WP-AGW05 to confirm (§7, Q4).

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver: frames on a WebSocket, an HTTP status and error code,
   what `EngineClient` sends to the engine, a process that exits, a metric.
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_api_gateway_*.py`,
   `tests/test_ws_spec_matches_code.py` and `tests/test_rest_spec_matches_contract.py`
   with `-n logical`, then black/flake8/mypy/pyright and `make _check`
   (openapi). When a WP changes what a client receives, also run
   `npm run typecheck && npm test` in `web-apps/trader-gui` (project rule from
   the REST review: existing clients are updated in the same WP). Do not start
   the next WP with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Unit tests build `EngineClient` with `make_pusher`/`make_subscriber` patched
(`tests/test_api_gateway_private_recovery.py`'s `client` fixture and its
`FakeWebSocket`) and feed it frames from the real message builders. Route
tests use `tests/api_gateway_harness.py`. The restart and shutdown behaviour
in WP-AGW01 and WP-AGW03 also gets one `-m e2e` test on the mini exchange
(`tests/e2e_exchange.py`), because the defects only show between processes.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-AGW01 | A closed WebSocket ends its handler; shutdown is prompt | H2 | — | 0.5 d | ☑ | 2026-11-15 |
| 2 | WP-AGW02 | A late engine accept is adopted, never a lockout | H3 | — | 0.25 d | ☑ | 2026-11-15 |
| 3 | WP-AGW03 | The private snapshot is the engine's state | H1, D1, D2 | Q1 | 1 d | ☑ | 2026-11-15 |
| 4 | WP-AGW04 | A refused cancel or amend never ends a resting order | C1, D3 | Q2 | 1 d | ☑ | 2026-11-15 |
| 5 | WP-AGW05 | Engine silence is a 503, never a role verdict | C2 | Q4 | 0.5 d | ☑ | 2026-11-15 |
| 6 | WP-AGW06 | Waits match their own reply; failures are visible | C3, C4, C5 | — | 0.5 d | ☑ | 2026-11-15 |
| 7 | WP-AGW07 | Order scans and the monitor snapshot scale with live orders | P1, P2, P3 | Q5 | 0.75 d | ☑ | 2026-11-15 |
| 8 | WP-AGW08 | Comments, operator guide, spec | D4–D9 | WP-AGW01–07 | 0.5 d | ☑ | 2026-11-15 |

Suggested order: **WP-AGW01 → WP-AGW02 → WP-AGW03 → WP-AGW04 → WP-AGW05 →
WP-AGW06 → WP-AGW07 → WP-AGW08**. WP-AGW01 first: a hung shutdown leaves
pm-api-gwy holding port 8080 after `pm-opctl-cli stop`, which breaks the
next start and every e2e run the later WPs need. WP-AGW02 is small and stops
a permanent lockout. WP-AGW03 and 04 change what clients receive and need Q1
and Q2. The text-only WP comes last so the texts describe the final code.

Estimated sequential effort: about 5 days, excluding review time and findings
discovered on the way.

---

## 1. Overall assessment

The request paths are sound. A write registers its waiter in the same loop
tick as its send, so no reply can beat it. `match=` waiters and the FIFO rule
for unfiltered ones keep concurrent callers apart. The idempotency store's
saga state makes a retried replace safe. Read-only keys never put the key on
the bus. The per-topic `seq` and per-gateway `stream_seq` are assigned before
fan-out, so a drop is always visible as a gap. The market-data cache's resume
watermarks are right for sparse per-symbol buffers. Clearing scope is
enforced before any row is read, and a participant never sees a
counterparty. The contract review's fixes hold.

The defects are in five places:

- **Restart and reconnect (H1, H3).** The private stream's `orders.snapshot`
  is built from what this process has seen since it started, not from the
  engine. After any gateway restart a trader's blotter opens empty while the
  orders still rest. A login that the engine answers after the 3 s auth
  timeout locks the gateway out for good.
- **WebSocket lifecycle (H2).** A private or admin/sim socket the client has
  closed keeps its server handler waiting for the next event. While one
  exists, SIGTERM does not stop the process, and `pm-opctl-cli stop` leaves
  it running on port 8080.
- **The order cache's status (C1).** A refused amend or cancel sent without a
  `request_tag` marks the still-resting order `REJECTED`. It then drops out
  of the admin "working" view and is evicted while it still rests.
- **Role lookups (C2).** An engine that does not answer the role query in
  time turns an ADMIN into a TRADER: `403 ROLE_DENIED` (recorded as such in
  the audit trail), and clearing routes silently narrow to the caller's own
  gateway.
- **Scans over every cached order (P1, P2).** Each process caches every
  gateway's orders on the exchange. With 200 000 of them, opening the admin
  monitor stalls the event loop for 1.5 s and sends a 77 MiB frame.

Severity key: **High**: a participant's orders, positions or access are
wrong or lost without a warning, or the process cannot be stopped. **Med**: a
wrong or misleading status, figure or error, or a stall a user notices.
**Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Private stream | After a restart `orders.snapshot` has 0 orders and no positions while the engine holds a resting order and +10 AAPL; trader-gui seeds its blotter from it *(repro)* | AGW03 |
| H2 | High | WebSockets | A client-closed `/ws/private` socket keeps its handler: SIGTERM → no exit within 120 s (0.5 s without the socket); `pm-opctl-cli stop` leaves the process on 8080 *(repro)* | AGW01 |
| H3 | High | Engine auth | An engine accept that arrives after the 3 s auth timeout locks the gateway out: `403 Gateway already connected` for > 240 s, never expiring *(repro)* | AGW02 |
| C1 | Med | Order cache | A refused untagged amend turns a resting `NEW` order into `REJECTED` in `GET /orders/{id}` and `/admin/orders`, and it is evicted while resting *(repro)* | AGW04 |
| C2 | Med | Roles | Role-lookup timeout → `TRADER`: an ADMIN gets `403 ROLE_DENIED` (audited) and narrowed clearing answers; the role cache never refreshes | AGW05 |
| C3 | Low | History | An unreadable `stats.db` escapes as `500 INTERNAL_ERROR` with a traceback, not `503 STATS_DB` *(repro)* | AGW06 |
| C4 | Low | Waiters | Quote, symbol-halt/resume/cancel-orders waits match on `symbol` although the acks carry `quote_id`/`command_id` | AGW06 |
| C5 | Low | Listener | A dead engine receive thread leaves a serving process that times out every engine call; only `/healthz` knows | AGW06 |
| P1 | Med | Admin monitor | Opening snapshot sends every cached order: 1.5 s loop stall and a 77 MiB frame at 200 000 orders *(measured)* | AGW07 |
| P2 | Low | Order cache | Every process caches every gateway's orders (697 B each, 133 MiB per 200 000); a status filter scans them all (183 ms) *(measured)* | AGW07 |
| P3 | Low | Fan-out | Request/reply topics of every process (reference bundles, gateway lists) go to every admin monitor | AGW07 |
| D1–D9 | — | Comments, guide, spec | See §5 | AGW03, 04, 08 |

---

## 3. Correctness findings

### H1. The private snapshot is the gateway's memory, not the engine's state *(repro)* — High

`routers/ws.py:181-194` builds `orders.snapshot` from `engine.get_caches(gateway_id)`:

```python
"orders": list(cache.orders.values()),
"positions": dict(cache.positions),
"quote_legs": list(cache.quote_legs.values()),
```

`SessionCaches` (`caches.py:39-117`) is filled only from events this process
has received since it started. Nothing seeds it from the engine:
`order.orders.<gw>` replies (`GET /orders`, bootstrap) are not folded in
(`apply` has no branch for them), and positions are summed from the fills
this process saw. `fetch_positions` (`routers/reference.py:595-610`) says so
itself: the local fill cache "reads flat after a gateway restart even though
the engine still holds the position". That is why `GET /positions` and the
bootstrap ask the engine, but the snapshot still uses the cache.

Repro on the mini exchange. MM01 (`disconnect_behaviour: CANCEL_QUOTES_ONLY`
in s10-basic) buys 10 AAPL and rests BUY 5 @ 20.00 GTC. The desk gateway is
stopped with SIGTERM and started again:

| After the restart | Engine (`GET /orders`, `GET /positions`) | `orders.snapshot` |
|---|---|---|
| Resting orders | 1 | 0 |
| Positions | AAPL +10 | `{}` |

The spec promises the opposite. `070-websocket.md:146` says the snapshot is
"the gateway's view of the caller's orders, positions and quote legs,
accurate as of `stream_seq`". `:189-191` says a client "MUST rebuild its
order state from it ... the snapshot is the recovery". trader-gui does
exactly that. `useOrderStore.seed` replaces the working set with the
snapshot ("authoritative baseline", `useOrderStore.ts:60`), and
`WebSocketManager.ts:482-489` reconnects to get a fresh snapshot on every
`stream_seq` gap.

What a trader sees after a pm-api-gwy restart is an empty Workspace blotter,
an empty position panel's order list and an Amend dialog with no order. Only
the Active Orders page, which calls `GET /orders` when opened, shows the
orders. The same happens without any restart for orders the process never
saw: GTC orders restored by the engine from earlier days, and orders that
rested before this gateway instance started. A trader who believes they have
no working orders may submit again.

**Fix.** Build the snapshot from the engine (Q1).

### H2. A client-closed WebSocket keeps its handler, and the process cannot stop *(repro)* — High

`routers/ws.py:199-204` (private) and `:306-308` (admin/sim) never read from
the socket after authentication:

```python
while True:
    event = await queue.get()
    await websocket.send_json(event)
```

A client that closes the socket is noticed only when the next event for that
gateway is sent and fails. Until then the handler, its queue and its sink
stay registered, and `api.ws_sessions` still counts the session
(`metrics.py:130-137`). For an idle trader that is forever. For admin/sim it
is forever when pm-market-sim is not running. The market-data socket does
not have this problem: it races a receive task against the send task
(`ws.py:382-394`).

Uvicorn's graceful shutdown waits for every running handler, so the
lifespan's `finally` (`main.py:211-232`) never runs. Repro on the mini
exchange, desk gateway started by hand, SIGTERM-to-exit time:

| Before SIGTERM | Exit |
|---|---|
| no WebSocket ever opened | 0.5 s |
| one `/ws/private` opened and closed cleanly by the client (TRADER02, idle) | not within 120 s (killed) |

Consequences:

- `pm-opctl-cli stop` sends SIGTERM, waits 15 s, reports the process and
  continues (`emo/cli.py:1082-1092`). The gateway keeps running and holding
  port 8080. Observed during this review: `stop` exited 1 with
  `pm-api-gwy` still alive. The next `pm-opctl-cli start`, or an e2e run,
  then finds the port taken.
- While it hangs, the gateway ids it holds stay connected at the engine and
  keep receiving heartbeats, so no disconnect behaviour runs.
- If the operator then kills it, the ids are refused for three heartbeat
  intervals. The SIGKILL repro measured `403 Gateway already connected` for
  179.5 s, after which the engine ran `CANCEL_ALL` for TRADER01.

This reproduces For-Later **L010** ("pm-api-gwy shutdown hang ... not
reproduced").

**Fix.** Give the private and admin/sim handlers the market-data shape: a
receive task that ends on disconnect, raced against the send loop. A bound on
uvicorn's graceful shutdown (`timeout_graceful_shutdown`) is a second guard,
so a future handler with the same mistake cannot hang a stop.

### H3. A late engine accept locks the gateway out permanently *(repro)* — High

`engine_client.py:295-326` `authenticate`: the waiter is registered and
`gateway_connect` sent. On `TimeoutError` (`:309-311`) the call returns
`False, "Engine authentication timed out"` without dropping the waiter. That
waiter is the future `asyncio.wait_for` has cancelled, so a later
`system.gateway_auth` resolves nothing. The engine has accepted the
connection and marked the session connected (`engine/main.py:2781-2848`), but
the gateway does not know it. It never adds the id to `_authenticated`, so it
never heartbeats it. Its next request sends `gateway_connect` again, and the
engine refuses a second live connection (`:2788-2800`).

The engine only expires sessions that have heartbeated at least once:
`_expire_silent_gateways` skips `heartbeat_interval_sec <= 0`
(`engine/main.py:4550`). This session never sent one, so it is never freed.

Repro on the mini exchange: the engine is paused with SIGSTOP for 5 s across
TRADER02's first request, then resumed.

```
first request while the engine is paused: 403 ENGINE_AUTH 'Engine authentication timed out' (3.0 s)
after the engine resumed: {'403 Gateway already connected: TRADER02': 239}
first 200 after 240.1 s   (none within the 240 s window)
```

Every REST request and WebSocket login for that gateway is then refused
until an ADMIN calls `POST /admin/gateways/TRADER02/disconnect` or the engine
restarts. Nothing in the operator guide connects the symptom to this cause
(D6). The trigger is an engine slower than `timeouts.engine_auth_sec` (3 s)
at a participant's first request: the open burst, a long GC pause, a
loaded host. Two smaller faults sit on the same path. The cancelled waiter
stays in `_pending` until the next reply on that topic arrives. An auth
timeout is also not counted in `engine_timeouts` (`:376-381` counts only
`await_event`), so the `api.engine_timeouts` metric misses it.

**Fix.** Adopt a late accept (Q3): keep listening after the timeout, and when
`accepted` arrives, record the id as authenticated and start heartbeating
it. The next request then succeeds. Count the timeout. The engine-side gap
(a session that never heartbeats never expires) is L029 (§9).

### C1. A refused untagged amend or cancel marks a resting order REJECTED *(repro)* — Med

`caches.py:41-64`. `order.ack accepted=false` answers three requests: a
refused new order, a refused cancel and a refused amend. The cache tells them
apart by `request_tag is not None`, and its comment claims the engine's
cancel/amend paths always forward the client's tag. They forward whatever the
request carried (`engine/main.py:6981`, `:7072`
`request_tag = payload.get("request_tag")`), which is `None` when the client
sent none. REST makes the tag optional (`PATCH /orders/{id}` body,
`DELETE /orders/{id}` query), and so do ALF and BALF. Their clients' events
also pass through this cache, because every process caches every gateway.

Repro on the mini exchange, TRADER01: a resting LIMIT, then
`PATCH /orders/{id} {"price": 20.005}` (off the 0.01 grid, no tag):

| View | Status |
|---|---|
| Engine (`GET /orders`) | `NEW`, resting |
| Gateway cache (`GET /orders/{id}`) | `REJECTED`, `reject_code: TICK_VIOLATION` |
| `GET /admin/orders?status=NEW` | absent |
| `GET /admin/orders` | `REJECTED` |

Consequences: the admin monitor's working-orders resync
(`?status=NEW|PARTIAL|AMENDED`) loses the order. `orders.snapshot` reports it
REJECTED. `_set_status` stamps it terminal, so the eviction sweep deletes a
resting order after `order_retention_sec` (`caches.py:173-203`). trader-gui
mirrors the same rule (`useOrderStore.ts:168-176`), so the trader's blotter
shows the same false REJECTED. Fills that arrive later revive it, but only
with the fill's fields. Any engine refusal of an amend or cancel triggers
this: off-tick price, a quantity below the filled amount, an unknown order, a
halted symbol, the gateway not connected.

**Fix.** Make the ack say which request it answers (Q2). A side benefit is that
`?wait=ack` on an untagged cancel/amend could then report a refusal instead
of a timeout (`orders.py:158-166`).

### C2. A slow role lookup is reported as a role verdict — Med

`engine_client.py:1096-1120` `resolve_role` returns `"TRADER"` on timeout
("so admin gating fails closed"). Its callers:

- `sessions.py:159-175` `require_admin` turns that into
  `403 ROLE_DENIED "ADMIN role required"` and records a `ROLE_DENIED`
  refusal in the audit trail (`report_refusal`). An operator whose
  first admin call meets a busy engine is told they are not an ADMIN, and
  the audit trail says the same.
- `clearing_scope.py:36-59` narrows an unconfirmed ADMIN to its own gateway.
  Its docstring states this ("an ADMIN that cannot be confirmed sees its own
  gateway only"). `GET /clearing/positions`, `/exposure`, `/trades` and
  `/daily` then answer `200` with the ADMIN gateway's rows only, usually
  none: an empty venue that the client cannot tell from a real empty one.
  The router promises the opposite for storage failures: "never an empty
  answer, which a client could not tell from 'no positions'"
  (`clearing.py:182-183`).
- `bootstrap_trader` puts the fallback into `gateway_role`
  (`bootstrap.py:352`, `:388`), so a
  market maker's or admin's bootstrap can say `TRADER`.

A resolved role is cached for the life of the process (`_role_cache`), and
`system.startup_recovery` does not clear it (`:543-555`). Roles change only
through the engine config and an engine restart (reload is refused), so after
such a change the gateway keeps answering with the old role until it is
restarted itself.

**Fix.** Q4: an unanswered lookup is `503 ENGINE_TIMEOUT` and is not cached;
clear the role cache on `system.startup_recovery`.

### C3. An unreadable stats.db escapes the history routes *(repro)* — Low

`routers/history.py:153-171`: `_open_stats` maps only `FileNotFoundError` to
`503 STATS_DB`. A corrupt or non-database file raises `sqlite3.DatabaseError`
at the first query, outside any handler. Repro through the real app
(`api_gateway_harness`), `stats_db` pointing at a 1.4 kB non-database file:
`GET /history/trades` escapes with `sqlite3.DatabaseError: file is not a
database`, which the app turns into `500 INTERNAL_ERROR` with a traceback in
the log. A database locked past the 5 s `busy_timeout` takes the same path.
The clearing router maps `sqlite3.DatabaseError` to `503 CLEARING_DB`
(`clearing.py:193`). The two disagree, and only the clearing one keeps the
error code meaningful.

**Fix.** Map `sqlite3.DatabaseError` to `503 STATS_DB` as clearing does.

### C4. Some waits match on a field that is not per request — Low

`_await_ack`/`await_event` resolve the first event whose payload matches
`match`. Several matches use a field shared by concurrent requests although
the reply carries a per-request one:

- `POST /quotes?wait=ack` matches `{"symbol": ...}` (`orders.py:969-971`).
  `quote.ack` carries `quote_id`, and the request may set it. Two quotes on
  one symbol in flight (a refresh loop) can swap verdicts.
- `POST /admin/symbols/{s}/halt`, `/resume` and `/cancel-orders` match
  `{"symbol": symbol}` (`admin.py:410`, `:453`, `:596`) while sending a
  `command_id` the acks echo (`SymbolHaltAck`, `SymbolResumeAck`,
  `CancelSymbolAck` carry it). Two operators acting on one symbol can each
  receive the other's verdict.

`/admin/market/halt` and `/resume` (`:784`, `:811`) match nothing, and their
acks carry no `command_id`. FIFO handles them as well as it can, and that is
noted, not changed.

**Fix.** Match on `quote_id` when the request has one, and on `command_id` for
the symbol commands.

### C5. A dead receive thread leaves a gateway that answers only with timeouts — Low

`engine_client.py:424-462`: `_receive_loop` ends on any `ZMQError` other
than `EINTR` (re-raised), and its `finally` sets `_running = False`. The
process keeps serving. Every engine-backed request now waits its full timeout
and answers 503, WebSockets go silent, and the health beacon reports nothing
about it: `metrics.samples` has no listener state. Only `/healthz` turns 503.
pm-opctl's health check for this profile is a TCP connect to 8080
(`emo/cli.py:304-307`), which still succeeds. The same holds for
`IndexClient` and `SimClient`. The `EINTR → break` branch is dead: pyzmq 27's
`zmq_poll` retries EINTR itself (`zmq/backend/cython/_zmq.py`, `zmq_poll`),
so only real failures reach it. Lessons-learned A4 asks that a dead worker
thread make the process exit non-zero.

**Fix.** When the engine listener thread dies unexpectedly, log it at ERROR
and stop the server so the process exits non-zero and the supervisor sees
it.

---

## 4. Performance findings

None of this costs anything at classroom size. All of it matters at the
s300 open, where the 2026-11-07 and 2026-11-12 runs saw the desk loop at
100–117 % CPU, loop lag up to 1.4 s and RSS growing from 110 to 730 MB.

### P1. The admin monitor's opening snapshot sends every cached order *(measured)* — Med

`ws.py:315-364` `_monitor_snapshot` sends `engine.all_orders()`: every
cached order of every gateway, terminal ones included, copied and then
JSON-encoded in one `send_json` on the event loop.
`bootstrap.py:197-212` `_active_order_counts` copies the same list to count
the live ones.

| 200 000 cached orders (all terminal) | Time on the loop |
|---|---|
| `all_orders()` (copy) | 356 ms |
| monitor snapshot: `all_orders()` + `json.dumps` | 1 488 ms, frame 77 MiB |

Every other client of that process stalls for that long, and the browser
parses 77 MiB. The monitor needs the working orders. It already resyncs with
`?status=NEW|PARTIAL|AMENDED` (trader-gui `useMonitorStore`), and terminal
history is in `GET /admin/orders` and the audit view.

### P2. Every process caches every gateway's orders *(measured)* — Low

`engine_client.py:585-604` folds every gateway-scoped event into a
`SessionCaches` for that gateway, whichever process hosts it. That is how the
admin views get a cross-gateway picture. It also means the `dashboards`
instance, which hosts only a read-only key, and the `monitor` instance keep
the whole exchange's order state too.

| 200 000 orders × (ack + fill), 300 foreign gateways | |
|---|---|
| Retained (tracemalloc) | 133 MiB, 697 B per order |
| `_handle_events` | 6.7 µs per event |
| `all_orders(status="NEW")`, 0 matches | 183 ms, a full scan |

The 183 ms scan runs on every admin gap resync, which the monitor sends every
10 s while it is behind, and so exactly while the loop is already short of
CPU. The cache grows with the day's orders up to `order_retention_sec` and
does not grow with history. 133 MiB per process explains part of the
observed RSS growth. The rest is not explained here.

### P3. Request/reply topics reach every admin monitor — Low

`events.py:77-102` `PRIVATE_PREFIXES` lists the private streams but not the
reply topics of request/reply pairs: `system.reference.<id>`,
`system.gateways.<id>`, `system.halt_status.<id>`,
`system.position_snapshot.<id>`, `system.session_status`, `system.risk_state`,
`system.volume`. `gateway_from_topic` returns `None` for them, so
`_handle_event` treats them as public (`engine_client.py:605-635`). Each one
is tested against every market-data socket's filter and then queued on every
admin monitor (`:642-651`), because `channel_for_topic` is `None` for them. All
processes subscribe to everything, so every bootstrap and every
`GET /reference` anywhere on the exchange sends a full reference bundle to
every admin monitor. None of it is rendered.

**Fix (P1–P3).** Q5: the monitor snapshot carries working orders only. Keep a
per-cache index of live order ids so a status filter and the active counts
cost O(live orders). Route reply topics past both fan-outs.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `070-websocket.md:146`, `:148-150`, `:189-191` | `orders.snapshot` is "accurate as of `stream_seq`" and "is the recovery"; it is this process's memory (H1). |
| D2 | `050-api-gateway.md:607-614` (Order cache retention) | Says the cache backs the private `orders.snapshot` with no warning that it misses orders older than the process; becomes wrong in another way once WP-AGW03 lands. |
| D3 | `caches.py:46-54` | "only `_handle_cancel`/`_handle_amend` forward the client's `request_tag`" implies cancel/amend rejects always carry one; they carry `None` when the client sent none (C1). |
| D4 | `config.py:96-104` (`order_retention_sec` comment) | "The cache is the read model behind `GET /orders`": `GET /orders` asks the engine and refuses to fall back to the cache (`orders.py:640-655`). |
| D5 | `engine_client.py:144` | "ADMIN monitor sinks receive every event across all gateways": public market data and `engine.trace` are skipped (`:636-645`). |
| D6 | `050-api-gateway.md`, Common problems | The `403 ENGINE_AUTH` advice is only "check the `participants` list". It does not cover `Gateway already connected` (another process holds the id; after a crash up to 3 minutes; after H3, until an admin disconnect) or `Engine authentication timed out`. The ALF chapter has that row (`010-alf-gateway.md:1073`). |
| D7 | `050-api-gateway.md`, Common problems | "WebSocket disconnects immediately — ... client rate limit hit": no WebSocket has a rate limit; a bad key closes with 1008. |
| D8 | `050-api-gateway.md`, Common problems | "History endpoints return empty results — `pm-stats` not running": a missing `stats.db` is `503 STATS_DB`, not an empty result. |
| D9 | `050-api-gateway.md` | Nothing says that stopping or restarting `pm-api-gwy` disconnects every gateway id it holds, so the engine applies each participant's `disconnect_behaviour`. With s10-basic's traders (`CANCEL_ALL`) a planned restart cancels their resting orders, GTC included (seen in the restart repro). |

---

## 6. Verified as correct

- **Register before reply.** Every route sends and then calls
  `await_event`/`await_topic`, which registers its future synchronously
  before the first `await`. The receive thread hands events over with
  `call_soon_threadsafe`, so no reply can be handled between the send and the
  registration. `authenticate` and the transition/reload waits register
  before sending and drop the waiter if the send fails.
- **FIFO for unfiltered waiters** (`_resolve_pending`): one event resolves
  at most one `match=None` waiter, so two concurrent `GET /orders` each get a
  reply. A reply that arrives after its waiter timed out goes to the next
  waiter, which is a valid (slightly older) answer, not another caller's
  data.
- **Idempotency** (`idempotency.py`): a duplicate waits on the first attempt
  under `shield`. A failed attempt with recorded saga steps is released for
  the retry. Pruning cannot pin on a released entry (R1). The replace saga
  never cancels twice or submits twice.
- **Sequencing:** `seq` per topic and `stream_seq` per gateway are assigned
  before fan-out, so a dropped event leaves a gap. trader-gui reconnects on a
  private gap (`WebSocketManager.ts:482-489`).
- **Market-data cache:** per-symbol and venue-wide eviction watermarks make
  resume decisions correct for sparse per-symbol buffers (P5, H3 of the
  Trader-GUI review).
- **Engine restart:** `system.startup_recovery` clears `_authenticated`, so
  the next request re-authenticates (K11). Books exist for every configured
  symbol from engine start (`engine/main.py:1186-1187`), so `GET /book` is
  answered for a quiet configured symbol.
- **EINTR:** pyzmq 27 retries it inside `zmq_poll`; the receive loops are not
  stopped by a signal (see C5 for the dead branch).
- **Clearing scope** (`clearing_scope.py`) is resolved before any query; a
  participant's trades have the counterparty's gateway and order id blanked
  (`clearing.py:280-290`).
- **Read-only keys** never travel on the bus (`correlation_id` hashes them).
  `/history/index-events` adds a per-call suffix so concurrent calls do not
  share a reply topic.
- **Backpressure on sends:** `_send` turns `zmq.Again` into
  `503 ENGINE_UNAVAILABLE` and best-effort notices never raise.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Where does `orders.snapshot` come from? (a) The engine: after registering the sink, ask for `order.orders_request` and `system.position_request`, send the snapshot with the engine's resting orders plus this process's cached terminal ones, positions from the engine, and the `stream_seq` of the `order.orders` reply. On an engine timeout close with 1013 (try again later) instead of sending a partial snapshot. (b) Seed the cache from the engine on first authentication and on `startup_recovery`, and keep serving the snapshot from the cache. (c) Keep it and document the limit. | **(a)**. The `order.orders` reply is itself a private event with a `stream_seq`, so every live event numbered above it is newer than the snapshot, and the existing "skip `stream_seq` ≤ snapshot" rule stays exact. (b) still misses changes while seeding and needs the same round trip anyway. (c) leaves trader-gui's blotter empty after every restart. |
| Q2 | How does a client tell a refused cancel/amend from a refused new order? (a) The engine adds `request: NEW \| CANCEL \| AMEND` to `order.ack` (spec, msgen, every ack path), and the cache and trader-gui use it. (b) pm-api-gwy puts its own `request_tag` on every untagged REST cancel/amend. | **(a)**. The cache holds every gateway's orders, ALF and BALF clients included, so only the engine can label every ack. (b) fixes REST requests only and shows clients a tag they never set. (a) is additive on the wire. |
| Q3 | What happens to an engine accept that arrives after `engine_auth_sec`? (a) Adopt it: record the id as authenticated and heartbeat it, so the next request succeeds. (b) After the timeout, send `gateway_disconnect` to undo a connect the engine may have processed. | **(a)**. (b) runs the participant's disconnect behaviour on a session that may already hold orders from a concurrent request, and races a retry's connect. |
| Q4 | What does a role lookup that times out mean? (a) `503 ENGINE_TIMEOUT`, not cached, nothing recorded as a refusal; clear the role cache on `startup_recovery`. (b) Keep the `TRADER` fallback. | **(a)**. "Fail closed" is kept, because nothing is granted, while the caller gets the true reason. (b) audits a false `ROLE_DENIED` and returns narrowed clearing data as complete. |
| Q5 | What does the admin monitor's opening snapshot carry? (a) Working orders only (`PENDING`, `NEW`, `PARTIAL`, `AMENDED`). (b) Everything, as now, with the encoding moved off the loop. | **(a)**. The monitor's own resync already asks for exactly that set; terminal history has `GET /admin/orders` and the audit view. (b) still builds a 77 MiB frame. |

---

**Decided 2026-11-15:** (a) for all five (the user accepted the
recommendations). Q4 was implemented with `503 ENGINE_UNAVAILABLE` instead of
`503 ENGINE_TIMEOUT`, because clients read `ENGINE_TIMEOUT` on a write as
"sent, outcome late" and a role lookup happens before anything is sent; see
the WP-AGW05 outcome. To confirm.

## 8. Work packages

### WP-AGW01 — A closed WebSocket ends its handler; shutdown is prompt (H2)

**Tests first** (`tests/test_api_gateway_ws_lifecycle.py`, new):

1. `/ws/private` with `FakeWebSocket` whose `receive` returns
   `websocket.disconnect` after authentication: `private_events` returns
   within 1 s with no event ever queued, and the sink is removed
   (`engine._sinks["GW01"]` empty). (Fails today: it waits on
   `queue.get()`.)
2. Same for `/ws/admin/sim` with no sim events. (Fails today.)
3. Same for `/ws/admin/monitor`. (Fails today.)
4. Through `MetricsMiddleware`: `api.ws_sessions{channel="private"}` is back
   to 0 after the client closes. (Fails today.)
5. A live private socket still receives queued events in order, and a send
   failure still removes the sink. Unchanged.
6. `-m e2e` (mini exchange): open and close a `/ws/private` socket, then
   `pm-opctl-cli stop`. Every process is gone and port 8080 is free within
   15 s. (Fails today.)

**Change.** A shared helper that runs the send loop and a receive watcher
(`websocket.receive()` until `websocket.disconnect`) and returns when either
ends, used by `private_events`, `admin_monitor` and `admin_sim`. Pass
`timeout_graceful_shutdown` to `uvicorn.run` (a few seconds) as the backstop.
Set L010 to Fixed in `EduMatcher-For-Later-ToDo.md`.

**Exit criteria.** Tests 1–6 pass; `tests/test_api_gateway_*.py` and
`tests/test_ws_spec_matches_code.py` green; SIGTERM-to-exit ≤ 2 s with a
closed private socket, measured with the review's repro script.

**Outcome (2026-11-15).** `routers/ws.py` has a shared
`_send_until_closed(websocket, send_next)`: it races the handler's send loop
against `_until_client_closes`, a task that reads `websocket.receive()` until
`websocket.disconnect` (anything else a client sends on these sockets is
ignored, as before), and returns when either ends, cancelling and awaiting the
other. `private_events`, `admin_monitor` and `admin_sim` use it, so their
`finally` removes the sink as soon as the client closes. `main.py` passes
`timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SEC` (5 s) to `uvicorn.run` as
the backstop. L010 is set to Fixed.

Tests: `tests/test_api_gateway_ws_lifecycle.py` (new). Tests 1–4 failed first
with `TimeoutError` (each handler still waiting on its queue after the client
closed). Test 5 is two tests (events in order; a send failure removes the
sink) and passed before and after. `test_main_cli_success` now asserts the
graceful-shutdown bound (failed first on the missing constant). Test 6 is
`tests/test_api_gateway_e2e.py::test_stop_after_a_closed_private_socket`
(`-m e2e`): with both changes reverted it failed with "pm-api-gwy still running
after stop"; it passes with the handler fix alone (backstop reverted) and with
both. The `FakeWebSocket` doubles in `test_api_gateway_private_recovery.py`
and `test_api_gateway_sim.py` gained a `receive` that stays connected.

Measured with the review's repro (scratch script on the mini exchange, a
`/ws/private` socket opened and closed by the client, then SIGTERM to the
desk gateway): **0.28 s** SIGTERM-to-exit (was > 120 s).

Full suite: 14 472 passed, 1 skipped; `make _check` green.

### WP-AGW02 — A late engine accept is adopted, never a lockout (H3; after Q3)

**Tests first** (`tests/test_api_gateway_auth_handshake.py`, new):

1. `authenticate("GW01", timeout=0.05)` with no reply returns
   `(False, "Engine authentication timed out")`. A `system.gateway_auth.GW01
   accepted=true` delivered afterwards puts GW01 in `active_gateways()` and
   sends one heartbeat. (Fails today.)
2. After 1, a second `authenticate("GW01")` returns `(True, "")` and sends no
   second `gateway_connect`. (Fails today.)
3. A late `accepted=false` changes nothing; a later `authenticate` sends a
   new `gateway_connect`. Unchanged in effect.
4. No waiter for `system.gateway_auth.GW01` is left in `_pending` once the
   late reply has been handled or a new attempt has started. (Fails today.)
5. `engine_timeouts` counts the auth timeout. (Fails today.)

**Change.** On timeout, leave a done-callback (or keep the waiter alive) that
records a late `accepted=true` as authenticated, sends the first heartbeat
and seeds symbols. Count the timeout. Add L029 to the For-Later list (§9).

**Exit criteria.** Tests 1–5 pass; `tests/test_api_gateway_*.py` green; the
review's SIGSTOP repro gets a `200` on the first request after the engine
resumes.

**Outcome (2026-11-15).** `EngineClient.authenticate` waits on
`asyncio.shield(future)`, so a timeout no longer cancels the waiter. On a
timeout (or a cancelled caller) `_await_late_accept` keeps the waiter in
`_late_auth[gateway_id]` with a done-callback: a later `accepted=true` adds
the id to `_authenticated`, sends the first heartbeat and asks for the
symbols snapshot (without waiting: the reply lands in the cache as usual).
A late refusal does nothing. A new attempt for the same id drops the old
waiter before registering its own; replies are FIFO, so the first connect's
late accept then resolves the new attempt, and the engine's "already
connected" answer to the second connect finds no waiter. An auth timeout now
counts in `engine_timeouts`. New log-ledger entry for the WARNING
"late engine accept adopted gateway_id=%s". L029 was already on the For-Later
list (added with the review).

Tests: `tests/test_api_gateway_auth_handshake.py` (new). Tests 1, 2, 4 (both
halves) and 5 failed first: GW01 not in `active_gateways()`, `(False, …)` on
the second attempt, two cancelled waiters left in `_pending`,
`engine_timeouts == 0`. Test 3 (late refusal) and the extra regression test
"a new attempt still adopts the first connect's accept" passed before and
after. The done-callback runs one loop tick after the reply, so the tests
yield once (`asyncio.sleep(0)`) after delivering it.

SIGSTOP repro (scratch script, mini exchange, engine paused 5 s across
TRADER02's first request): `403 Engine authentication timed out (3.0 s)`
while paused, then **`200`** on the first request after the engine resumed
(was 239 × `403 Gateway already connected` for 240 s).

Full suite: 14 478 passed, 1 skipped; `make _check` green.

### WP-AGW03 — The private snapshot is the engine's state (H1, D1, D2; after Q1)

**Tests first** (`tests/test_api_gateway_private_recovery.py`):

1. Fresh `EngineClient` (empty cache). The engine answers `order.orders.GW01`
   with one resting order and `system.position_snapshot.GW01` with AAPL +10.
   The `orders.snapshot` frame carries that order and `{"AAPL": 10}`. (Fails
   today: 0 orders, `{}`.)
2. The snapshot's `stream_seq` equals the `stream_seq` the `order.orders`
   reply was given. A fill queued before the reply is not sent after the
   snapshot with a higher `stream_seq`. (Fails today.)
3. A terminal order in the cache (filled a minute ago) and not in the
   engine's resting list is still in the snapshot. Unchanged in effect.
4. Engine silent: the socket is closed with 1013 and no `orders.snapshot` is
   sent. (Fails today.)
5. `-m e2e` (mini exchange): the review's MM01 restart scenario. After a desk
   restart the snapshot has the resting order and the position. (Fails
   today.)
6. trader-gui: `useOrderStore.seed` with the new frame, unchanged
   (`npm test`).

**Change.** `private_events` registers the sink, sends `authenticated`, then
requests orders and positions from the engine and builds the snapshot from
the replies plus cached terminal orders. Update `070-websocket.md`
(snapshot source, the 1013 close) and the operator guide's cache section
(D1, D2). Run `make openapi`/`test_ws_spec_matches_code`.

**Exit criteria.** Tests 1–6 pass; `tests/test_api_gateway_*.py`,
`tests/test_ws_spec_matches_code.py` and trader-gui `npm test` green.

**Outcome (2026-11-15).** Q1 (a). New `EngineClient.private_snapshot(gateway_id,
queue, timeout) -> (stream_seq, data)`. After the sink is registered it sends
`system.position_request` and then `order.orders_request`, and reads the
socket's own queue until the `order.orders.<gw>` reply arrives; that event's
`stream_seq` is the cut, and every event dequeued before it is covered by the
snapshot and not sent. Details that came out of writing the tests:

- **Positions are exact at the cut.** The engine answers one sender's
  requests in order, so the position snapshot is published before the orders
  reply. Its waiter is registered with `match={}` (observes, does not take a
  concurrent `GET /positions` caller's FIFO slot) and a new
  `_PendingWait.on_resolve` hook that records the private `stream_seq` at the
  moment the position snapshot is handled. Fills between that point and the
  cut are added to the engine's net quantities; zero quantities are dropped,
  as the engine drops them.
- **The cut is the first `order.orders` reply after the position snapshot**,
  not merely the first one: a reply to someone else's earlier `GET /orders`
  published before the position snapshot would make positions newer than
  orders.
- **Orders:** the engine's resting rows (`OrderDisplay`, with `order_id`
  added beside `id` and `client_tag` always present) plus the cached terminal
  orders the engine does not list. A cached *working* order the engine no
  longer holds (a missed terminal event) is left out. Quote legs still come
  from the cache.
- **Engine silent** for `engine_reply_sec`: the socket is closed with `1013`
  (`WS_1013_TRY_AGAIN_LATER`), no snapshot is sent, `engine_timeouts` counts
  it, and a WARNING (new log-ledger entry) names the gateway.
- `private_events` now builds and sends the snapshot inside the sender task
  of WP-AGW01's helper (renamed argument: it takes the sender coroutine), so a
  client that closes while the engine is being asked still ends the handler at
  once.

Residual, not handled: if more than 256 private events for one gateway were
queued between two turns of the snapshot loop, a fill between the position
snapshot and the cut could be dropped from the queue and be missing from the
snapshot's positions. The loop drains the queue on every turn and the receive
thread hands over at most 256 events per batch across all gateways, so this
needs several batches handled back to back for one gateway; it was not
reproduced.

Docs: `070-websocket.md` (snapshot source, contents, cut, the new `1013`
close code; D1), the operator guide's "Order cache retention" (D2), and two
sentences in `060-rest-and-websocket.md` that called the snapshot "the cached
view". `test_ws_spec_matches_code` pins the close codes as `{1008, 1013}`.

Tests (`tests/test_api_gateway_private_recovery.py`, replacing the old
cache-based snapshot test): 1 failed first with `[] == ['ORD-R']`; 2 with
`stream_seq 0 == 2`; the extra "earlier orders reply is not the cut" test
with `[] == ['ORD-R']`; 3 with `{'ORD-DONE', 'ORD-GONE'}` (the stale working
order was reported); 4 never closed. Test 5 is
`tests/test_api_gateway_e2e.py::test_snapshot_after_a_gateway_restart`
(`-m e2e`, MM01 buys 10 AAPL and rests BUY 5 @ 20.00 GTC, desk SIGTERM'd and
started again): with the pre-WP `ws.py` it failed with the resting order
absent from `{}`; it passes now, and so does WP-AGW01's e2e. Test 6: a new
trader-gui `orderStore` test seeds the engine row shape beside a cached
terminal row; `npm run typecheck` and `npm test` (559) green. The WP-AGW01
lifecycle tests now answer the two snapshot requests.

Full suite: 14 482 passed, 1 skipped; `make _check` green.

### WP-AGW04 — A refused cancel or amend never ends a resting order (C1, D3; after Q2)

**Tests first:**

1. `tests/test_engine_*` (the cancel/amend reject tests): an untagged
   refused amend publishes `order.ack` with `request: "AMEND"`; a refused
   cancel `request: "CANCEL"`; a refused new order `request: "NEW"`. (Fails
   today: no such field.)
2. `tests/test_api_gateway_*` (cache): a resting `NEW` order, then an
   untagged `order.ack accepted=false request=AMEND` → status stays `NEW`,
   not terminal, not evicted by `evict_terminal_orders(0.0, now+∞)`. (Fails
   today: `REJECTED`, evicted.)
3. A refused new order still becomes `REJECTED`. Unchanged.
4. `DELETE /orders/{id}?wait=ack` without `request_tag`, refused: the reply is
   `REJECTED` with the engine's `reject_code`, not `ack_timeout: true`.
   (Fails today.)
5. trader-gui `useOrderStore.applyAck` keeps a resting order on an untagged
   cancel/amend refusal (`npm test`). (Fails today.)

**Change.** `spec/messages/order.yaml` `order.ack.request`, regenerate with
pm-msgen, set it on every ack path in the engine, use it in
`SessionCaches.apply` and `useOrderStore.applyAck`, and race the reject in
`_await_cancel_or_amend_event` without a tag. Fix the D3 comment. Check
audit replay and pm-stats for consumers of `order.ack` that compare whole
payloads.

**Exit criteria.** Tests 1–5 pass; `tests/test_api_gateway_*.py`,
`tests/test_engine_*.py`, `tests/test_cross_transport_rejects.py`, msgen and
`make _check` green; trader-gui `npm run typecheck && npm test` green; the
review's amend repro shows `NEW` in all four views.

**Outcome (2026-11-15).** Q2 (a). `spec/messages/order.yaml` `order_ack` has a
new optional enum `request: NEW | CANCEL | AMEND` (additive on the wire;
regenerated with `pm-msgen`, message reference included). The engine sets it
on every ack: `Engine._order_ack` and `_reject` take `request` as a required
keyword with no default, so a new ack site cannot forget it (31 call sites:
`_handle_new_order`, `_publish_dispatch` (book rejects only ever end a new
order), the seeded quote legs, combo and OCO legs → `NEW`; `_handle_cancel`
→ `CANCEL`; `_handle_amend` → `AMEND`; `_error_answer` by request topic via
`_ACK_REQUEST`); the inline hot-path ack carries `"request": "NEW"`.
`make_ack_msg` gained the `request` argument.

Consumers: `SessionCaches.apply` leaves the status alone for a refusal whose
`request` is `CANCEL` or `AMEND` (D3 comment rewritten; the `request_tag`
heuristic is gone). `EngineClient.await_cancel_or_amend_outcome` takes
`request` and an optional `request_tag`, and races the refusal matched on
`order_id` + `accepted=False` + `request` (+ `request_tag` when set); the
cancel and amend routes always race now, and the replace saga passes
`request="CANCEL"`. trader-gui: `OrderAckData.request`, and both
`useOrderStore.applyAck` and `useOrderEventNotifications` (which used the
same `request_tag` heuristic and would have toasted an untagged refused
cancel as "killed") key on it. Audit-replay lexicon gloss for the new enum.
Audit replay's own refusal detection (causation id, refusal-only codes) and
pm-stats' `REJECT` event type were checked and need no change. Docs: the
REST spec's cancel/amend `wait` rows and the "Without a `request_tag`"
paragraph, a paragraph in `070-websocket.md`, the OpenAPI examples
(`make openapi`).

Tests first: `tests/test_engine_ack_request.py` (new; all five failed with
`KeyError: 'request'`), `tests/test_api_gateway_ack_request.py` (new; the
two cache tests failed with `'REJECTED' == 'NEW'`, the untagged
`DELETE ?wait=ack` with a timeout; the new-order test passed before and
after), trader-gui `orderStore.test.ts` ("an untagged refused amend or
cancel leaves a resting order working" failed first) and
`orderEventNotifications.test.ts` (failed first: `'Order ORD4 killed: …'`).
Existing tests that encoded the old rule were updated:
`test_trader_gui_review_c1.py` payloads now carry `request`,
`test_cancel_wait_ack_without_request_tag_falls_back_to_single_topic`
became `…_still_races_the_refusal`, and four test doubles of
`await_cancel_or_amend_outcome` take the new argument.

Amend repro (scratch script, mini exchange, TRADER01, untagged
`PATCH {"price": 20.005}?wait=ack`): the reply is now `200 REJECTED
TICK_VIOLATION` (was a timeout), and engine `GET /orders`, cache
`GET /orders/{id}`, `GET /admin/orders?status=NEW` and `GET /admin/orders`
all show **`NEW`**.

Full suite: 14 494 passed, 1 skipped; `make _check` green; trader-gui
typecheck and `npm test` (561) green.

### WP-AGW05 — Engine silence is a 503, never a role verdict (C2; after Q4)

**Tests first** (`tests/test_api_gateway_admin.py`,
`tests/test_api_gateway_clearing_scope.py`):

1. ADMIN key, engine silent on `system.gateways_request`: `POST
   /admin/market/halt` is `503 ENGINE_TIMEOUT`, and no `ROLE_DENIED` refusal
   is reported. (Fails today: `403 ROLE_DENIED`, reported.)
2. ADMIN key, engine silent: `GET /clearing/positions` is
   `503 ENGINE_TIMEOUT`, not `200` with the caller's own rows. (Fails today.)
3. Engine silent: a later lookup asks the engine again (not cached).
   Unchanged.
4. `system.startup_recovery` clears the role cache; the next admin call asks
   the engine. (Fails today.)
5. A TRADER key on an admin route is still `403 ROLE_DENIED`. Unchanged.

**Change.** `resolve_role` raises on timeout. `require_admin`,
`clearing_scope`, the bootstrap routes, `status_summary` and the admin
WebSockets map that to 503 (WebSockets: close 1013). Clear `_role_cache`
beside `_authenticated` on `startup_recovery`. Update `clearing_scope`'s
docstring and the error-code declarations (`docs.errors`, `make openapi`).

**Exit criteria.** Tests 1–5 pass; `tests/test_api_gateway_*.py`,
`tests/test_api_gateway_error_codes.py`, `test_rest_spec_matches_contract.py`
and `make _check` green.

**Outcome (2026-11-15).** Q4 (a), with one deviation in the error code:
an unanswered role lookup is **`503 ENGINE_UNAVAILABLE`**, not
`503 ENGINE_TIMEOUT`. Found while checking the clients: trader-gui reads
`ENGINE_TIMEOUT` on a write as "the command reached the engine, the outcome
is late" (`lib/bulkOutcome.ts` `isUnconfirmed`); the kill-switch panel then
toasts "Kill switch submitted — awaiting engine confirmation". The role
lookup runs before the command is sent, so that toast would have been false.
`ENGINE_UNAVAILABLE` is the registry's "could not be handed to the engine;
nothing was sent. Transient; retry", which is exactly the case, and it is
already a code every route declares, so no route's contract changes. The
substance of Q4 (a 503, not cached, no refusal recorded, cache cleared on
`startup_recovery`) is as decided. **To confirm with the user.**

Changes: `EngineClient.resolve_role` raises that 503 on timeout and caches
nothing; `system.startup_recovery` clears `_role_cache` beside
`_authenticated`. `require_admin`, `clearing_scope`, the bootstrap routes and
`GET /status` pass the 503 through unchanged. The admin WebSockets share a
new `ws._admin_confirmed`: an unconfirmed role closes the socket with
`1013` (WARNING with a new log-ledger entry), not an `error` frame and
`1008`. `clearing_scope`'s docstring and the WebSocket spec's checks table
and `1013` row are updated.

Tests: `tests/test_api_gateway_role_lookup.py` (new, real `EngineClient`
through the app): 1 failed first with `403 ROLE_DENIED`; 2 (given a real
clearing ledger, so the scope is reached) answered `200` with the caller's
rows; 3 "DID NOT RAISE"; 4 `'TRADER' == 'ADMIN'` (stale cache); 5 (a
TRADER is still `403 ROLE_DENIED`, refusal recorded) passed before and
after. The extra admin-socket test (both sockets close `1013`) failed with
the 503 escaping the handler. `test_api_gateway_clearing_scope.py`'s
"unanswered lookup fails closed" test, which pinned the old narrowing,
now pins the 503.

Full suite: 14 501 passed, 1 skipped; `make _check` green.

### WP-AGW06 — Waits match their own reply; failures are visible (C3, C4, C5)

**Tests first:**

1. `GET /history/trades` with a non-database `stats_db`: `503 STATS_DB`.
   (Fails today: 500.)
2. Two concurrent `POST /quotes?wait=ack` on one symbol with different
   `quote_id`s, acks delivered in reverse order: each reply carries its own
   `quote_id`'s verdict. (Fails today.)
3. Two concurrent `POST /admin/symbols/AAPL/halt`, acks in reverse order:
   each gets the ack with its own `command_id`. (Fails today.)
4. `_receive_loop` raising a non-EINTR `ZMQError`: an ERROR line is logged
   and the server is asked to stop (`should_exit`), so the process ends
   non-zero. (Fails today.)
5. A normal `stop_listener` at shutdown logs no ERROR. Unchanged.

**Change.** Map `sqlite3.DatabaseError` in `_in_stats_db`. Match quote acks
on `quote_id` when present, symbol commands on `command_id`. A listener that
dies unexpectedly logs at ERROR and triggers the server's shutdown. Remove
the dead `EINTR` branch's `break` or turn it into `continue`.

**Exit criteria.** Tests 1–5 pass; `tests/test_api_gateway_*.py` green.

**Outcome (2026-11-15).**

- **C3.** `history._in_stats_db` maps `sqlite3.DatabaseError` from the
  worker thread to `503 STATS_DB` and logs a WARNING (new ledger entry), as
  `_in_clearing_db` does. Test (`test_api_gateway_history.py`, through the
  real app with a 1.5 kB non-database `stats_db`) failed first with
  `sqlite3.DatabaseError: file is not a database` escaping the app.
- **C4.** `POST /quotes?wait=ack` matches `quote_id` when the request has
  one (the symbol otherwise, as before). Symbol halt, resume and
  cancel-orders match the `command_id` they send; every engine path of the
  three acks echoes it (`engine/main.py` `_handle_symbol_halt`, `…_resume`,
  `…_cancel_symbol`, checked). Tests (`tests/test_api_gateway_wait_matching.py`,
  new, real `EngineClient`, acks delivered in reverse order) failed first
  with swapped verdicts (`('Q-1', False)`; `409 == 200`).
  `test_symbol_scoped_admin_acks_pass_symbol_match`, which pinned the symbol
  match, now pins the `command_id` match.
- **C5.** `EngineClient._receive_loop` catches what kills the thread: if
  the listener was still meant to run (not `stop_listener` closing its
  sockets), it logs `engine listener died; stopping pm-api-gwy` at ERROR with
  the traceback and calls `on_listener_failure` on the loop. The lifespan
  sets that callback to mark `app.state.listener_failed` and set
  `should_exit` on the uvicorn server; `main()` now builds
  `uvicorn.Server(uvicorn.Config(...))` itself (it needs the handle; same
  settings as the old `uvicorn.run`) and exits with status 1 after the server
  returns when the flag is set (CRITICAL line). The EINTR branch is a
  `continue`. Tests (`tests/test_api_gateway_listener.py`, new): the dying
  listener test failed first (the callback never ran); the normal-stop test
  passed before and after; the `main()` exit-status test was not run against
  the old code, because the old `main()` calls the real `uvicorn.run` and
  starts a server (it hung the first attempt until the timeout killed it).
  `test_main_cli_success` now patches `uvicorn.Server`. Both e2e tests
  (`-m e2e`) pass with the `Server`-based `main()`. `IndexClient` and
  `SimClient` have the same receive-loop shape and were not changed (the WP
  names the engine listener); noted in §9 and as For-Later L033.

Full suite: 14 507 passed, 1 skipped; `make _check` green.

### WP-AGW07 — Order scans and the monitor snapshot scale with live orders (P1, P2, P3; after Q5)

**Tests first:**

1. The monitor snapshot carries only `PENDING`/`NEW`/`PARTIAL`/`AMENDED`
   orders. (Fails today.)
2. `all_orders(status="NEW")` with 200 000 terminal and 10 live orders reads
   only the live ones: assert on a counter or on the time (< 5 ms on this
   host; today 183 ms). (Fails today.)
3. `_active_order_counts` equals today's result for a mixed cache. Unchanged.
4. A `system.reference.RO…` reply reaches no admin sink and no market-data
   filter. (Fails today.)
5. A `system.symbols.GW01` reply still reaches GW01's private sink.
   Unchanged.

**Change.** A live-id set per `SessionCaches`, maintained in `_set_status`.
`all_orders` and the counts use it for live statuses. The monitor snapshot
uses it. Classify reply topics (from the message registry, not a literal
list) so `_handle_event` resolves waiters and stops there.

**Exit criteria.** Tests 1–5 pass; `tests/test_api_gateway_*.py` green;
the bench in §4 shows the monitor snapshot under 50 ms at 200 000 terminal
orders (a guess, to be confirmed by measurement).

**Outcome (2026-11-15).** Q5 (a).

- `SessionCaches.live` (a dict used as an ordered set) holds the ids of the
  non-terminal orders; `_set_status` maintains it beside `terminal_at`, so
  eviction (terminal only) never touches it. The one write that bypassed
  `_set_status`, `_cache_submitted`'s `PENDING` entry, now goes through a new
  `SessionCaches.submitted()`.
- `EngineClient.all_orders` gained `working=True`, and a status filter for a
  non-terminal status (`NEW`, `PARTIAL`, `AMENDED`, `PENDING`) reads through
  `live` too. The monitor snapshot sends `all_orders(working=True)`;
  `bootstrap._active_order_counts` counts the same, and its now-unused
  `_TERMINAL` set is gone. A terminal status filter (`?status=FILLED`) and
  the unfiltered `GET /admin/orders` still read everything; that is what
  they ask for.
- P3: `events.REPLY_PREFIXES`, read from the message registry like
  `COMMAND_TOPICS`: every engine-published topic whose only parameter is the
  gateway id, less the private stream and `admin.action` (24 topics: the
  `system.*` replies, `risk.*_ack`, `session.transition_ack`,
  `system.gateway_bye`, `order.price_level_orders`, the `index.*` acks).
  `_handle_event` resolves their waiters and returns: no `seq`, no
  market-data filter, no admin sink. `system.gateway_bye` is still acted on
  (it is handled before the return). trader-gui's monitor renders none of
  these (`lib/monitorEvents.ts`: `order.*`, `session`, `circuit_breaker`,
  `admin.action`), and the spec already told monitors to ignore types they do
  not render.
- P2 itself (each process caches every gateway's orders, about 700 B per
  order) is unchanged: the admin views need the cross-gateway cache. What
  changed is that no hot path scans it any more.

Docs: `070-websocket.md` (snapshot contents, which events the monitor gets,
the recovery advice that relied on the snapshot being large).

Tests (`tests/test_api_gateway_order_index.py`, new): the monitor snapshot,
the no-scan status filter (an order dict that refuses iteration), and the
reply fan-out test failed first for the right reasons (statuses included
FILLED/CANCELLED/REJECTED; "scanned every cached order"; the reply was on
the admin queue). The active-count and live-index tests failed first on the
missing `submitted()` helper they use to cache a `PENDING` order, so they do
not prove much against the old code; the count test compares with a full
scan. "A `system.symbols` reply still reaches its gateway" passed before and
after. Two test doubles (`test_tick_validation.py`,
`test_cross_transport_rejects.py`) now use a real `SessionCaches`, and the
bootstrap fake's `all_orders` takes `working`.

Measured (scratch bench, 200 000 terminal + 2 000 working orders over 300
gateways and 30 symbols, fed as real ack and fill frames):

| | Before | After |
|---|---|---|
| Monitor snapshot orders + `json.dumps` | 900 ms, 61 MiB | **4.2 ms, 471 KiB** |
| `all_orders(status="NEW")` | full scan (183 ms in §4) | **1.0 ms** |
| `all_orders(status="FILLED")` / unfiltered | 387 / 339 ms | unchanged (they return everything) |
| `_handle_events` per event | 6.7 µs | 6.7 µs |

Full suite: 14 513 passed, 1 skipped; `make _check` green.

### WP-AGW08 — Comments, operator guide, spec (D4–D9)

**Change.** Fix D4 and D5 in code comments. Operator guide
`050-api-gateway.md`: the Common problems rows (D6, D7, D8), and a short
"Stopping and restarting the gateway" passage (D9): every held id
disconnects and its `disconnect_behaviour` runs, a killed process blocks its
ids for up to three heartbeat intervals, and `POST
/admin/gateways/{id}/disconnect` frees an id at once. Re-walk the guide's
restart, WebSocket and admin passages and the training guide's chapter 24
against the code after WP-AGW01–07 (lessons-learned B1).

**Exit criteria.** `make _check` green; every row of §5 resolved; the
re-walk recorded in the outcome.

**Outcome (2026-11-15).** §5, row by row: D1 and D2 were fixed in WP-AGW03
and D3 in WP-AGW04. **D4** `config.py`'s `order_retention_sec` comment names
what the cache backs (`GET /orders/{order_id}`, the admin order table, the
snapshot's finished orders) and says `GET /orders` never falls back to it.
**D5** the `_admin_sinks` comment lists what the admin feed leaves out.
**D6** the operator guide's Common problems splits `403 ENGINE_AUTH` into
three rows: a refused id, "Gateway already connected" (who can hold it, the
3-minute timeout after a kill, the admin disconnect), and "Engine
authentication timed out" (retry; a late accept is adopted). The `401` row
is now only `AUTH`. **D7** the WebSocket row is replaced by `1008` (with
every cause, and "WebSockets have no rate limit") and `1013`. **D8** history:
`503 STATS_DB` for a missing or unreadable file, empty or stale results when
pm-stats is stopped. **D9** a new "Stopping and restarting" subsection under
"Start the process": a clean stop disconnects every id and runs its
`disconnect_behaviour` (traders' resting orders, GTC included, are cancelled
by the default `CANCEL_ALL`); open sockets are closed and the process waits at
most 5 s; a killed process blocks its ids for up to 3 minutes (60 s × 3
missed heartbeats, `engine/main.py` `_HEARTBEAT_MISSED_LIMIT`,
`GATEWAY_HEARTBEAT_INTERVAL_SEC`); `POST /admin/gateways/{id}/disconnect`
frees one at once; after a restart the private snapshot comes from the
engine; exit status 1 after "engine listener died". The `/healthz` row no
longer says a dead listener leaves the process up (WP-AGW06 stops it).

Checked by running, not only by reading: an **open** `/ws/private` socket at
SIGTERM receives close code `1012` within 0.1 s and the process exits in
0.46 s (scratch script on the mini exchange), which is what the D9 text
says.

Re-walk (lessons-learned B1): the operator guide's start, restart,
WebSocket ("What operators need to know"), admin, cross-gateway views and
cache-retention passages, the WebSocket spec's connection, close-code,
private and admin-monitor sections, the REST spec's write-outcome table and
the cancel/amend sections, and training guide chapter 24 (`240-api-gwy.md`).
One more stale statement was found and fixed: chapter 24 said every history
call answers `503 STATS_DB` when pm-stats "is not running"; it does so only
when `stats.db` is missing or unreadable. The chapter's private-stream
transcript (`authenticated`, then `orders.snapshot` with your orders and
positions) and its admin exercises (`403 ROLE_DENIED` for a trading key,
"Gateway already connected: OPS01" while `pm-admin` holds the id) are still
what the code does. `mkdocs build --strict` passes.

Full suite: 14 513 passed, 1 skipped; `make _check` green.

---

## 9. Out of scope, noted

- **L029 (new): the engine never expires a session that never heartbeated.**
  `_expire_silent_gateways` skips `heartbeat_interval_sec <= 0`
  (`engine/main.py:4550`), so any client that connects and dies before its
  first beat holds its id until an admin disconnect or an engine restart.
  WP-AGW02 removes the REST path into this state; ALF, BALF and the bots
  have their own. Engine change.
- **L030 (new): admin position and order queries about a disconnected
  gateway return empty lists.** `_handle_position_request` and
  `_handle_orders_request` answer `[]` when the *target* is not connected
  (`engine/main.py:2622-2625`, `:2861-2864`). `GET
  /admin/gateways/{id}/positions` and `/orders` then show a logged-off ALF
  trader with GTC orders and a position as flat with no orders, in a `200`.
  The engine message names one gateway for both "who asks" and "about whom",
  so the fix is an engine and IDL change.
- **Restart lockout after a crash.** A killed pm-api-gwy blocks its ids for
  three heartbeat intervals (179.5 s measured), after which the engine runs
  each participant's disconnect behaviour. This is the engine's rule for every
  transport, and the ALF chapter documents it. WP-AGW08 documents it for REST.
- **L027 (BALF, existing)** is the BALF counterpart of H1: after a restart
  the gateway knows nothing about the orders its participants have resting.
- **L010 (existing)** is reproduced by H2 and closed by WP-AGW01.
- **`IndexClient` and `SimClient` receive threads** (found in WP-AGW06):
  they end on a non-EINTR `ZMQError` like the engine listener did, and the
  process keeps serving. The engine listener now stops the process (C5);
  these two feed `/history/index-events` and the sim/news streams, whose
  loss is less severe. Recorded as For-Later **L033**.
- **RSS growth on the s300 sim (110 → 730 MB).** P2 accounts for about
  133 MiB per 200 000 cached orders per process. The rest was not
  investigated here.
