# pm-alf-console Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/alf_console/` at `dac95e8f` (v0.80.0): `main.py`
(2 092 lines, the CLI, the `Gateway` class: sockets, authentication, the
heartbeat thread, the listener thread, the event handlers, the local order,
quote-leg and position caches, and the command parser), `display.py` (610, the
Rich console, `HELP_TEXT` and every table printer), `completer.py` (289, tab
completion) and `__init__.py` (0). Nothing else imports the package except its
tests. Read where they decide the console's behaviour, not reviewed as code of
their own: `messaging/bus.py` `make_subscriber`/`make_pusher` and the publisher
trailer (`models/message.py` `decode_sequence`), the generated builders and
topics in `models/generated/{order,system,trade}.py`, `models/price.py`
`to_ticks_exact`, the engine's `_handle_position_request`
(`engine/main.py:2646-2664`), `_handle_gateway_disconnect` (`:4491-4530`) and
`DisconnectBehaviour` (`models/participant.py:15-25`). pm-alf-gwy
(`alf_gwy/gateway.py`) was read for comparison: it serves the same command set
over TCP and has already solved several of the problems below.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, `--help`, `HELP`, the pm-help registry, the participant guide
chapter (`docs/books/participant-guide/part-2-orders/010-the-trader-console.md`)
and the reference manual section
(`docs/books/reference-manual/part-1-command-line/010-processes-environment-and-ports.md:560-633`)
say what the code does.

**Previous work:** no earlier review of this component. Fixes already in
place from other work and not repeated here: lowercase order ids and tags are
not upper-cased (`_CASE_SENSITIVE_KEYS`); a refused AMEND/CANCEL no longer
marks a live order REJECTED and combo/OCO children are registered from their
acks (`tests/test_alf_console_order_cache.py`); quote acks are matched by
`quote_id`, not arrival order; the DC handler ignores another gateway's
drop-copy topic it only prefixes (`main.py:833-836`); the engine heartbeat
thread with its own socket (`fe5114f9`); logout when the engine connection is
lost (`f7ceae81`); `cancel_reason` on CANCELLED (`57909d93`); off-grid prices
refused locally with `to_ticks_exact`. For-Later items that touch the console:
L006 (float price formatting) and L034 (`-q` is the default), see §9.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `dac95e8f`: a real
`Gateway` object whose sockets connect to real ZeroMQ sockets bound by the
script (`make_publisher`/`make_puller`, so every message carries the real
trailer), fed with frames from the engine's own builders (`make_fill_msg`,
`make_trade_msg`, `make_position_snapshot_msg`). Where timing matters the
engine side runs in its own process. Command lines were driven through
`Gateway._parse_and_send` and, for the consequence of a crash, through
`Gateway.run()` with a scripted prompt. *(measured)* means timed on this host
with the same setup. The other findings are by inspection, with line numbers
given.

Status: **Open.** Decisions Q1–Q6 are needed before WP-ACN01, -02, -03 and
-04.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (lines printed, the order/position caches, frames
   pushed to the engine, the process exit code).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_alf_console_*.py`,
   `tests/test_commands_console.py` and `tests/test_shell_completion.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP with
   a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Unit tests can keep using `_make_gateway` from
`tests/test_alf_console_quote_ack.py` (sockets replaced by mocks) and call
`_handle_event` / `_parse_and_send` directly. Tests about delivery (WP-ACN01,
WP-ACN03) need real sockets: the review's scratch `harness.py` (about 40
lines: binds a `make_publisher` on free ports, points the module's address
constants at them, starts `_listen` in a thread) can become a fixture in
`tests/test_alf_console_delivery.py`. Feed it with the engine's builders, not
hand-made frames.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-ACN01 | Only this gateway's own events reach its screen and caches | H1 | Q1 | 0.25 d | ☐ | |
| 2 | WP-ACN02 | No typed line or table print ends the session | H2, C2 | Q2 | 0.5 d | ☐ | |
| 3 | WP-ACN03 | A burst never silently costs the console its own events, and only the listener touches its sockets | C1, C3, P1 | Q3, Q4 | 0.5 d | ☐ | |
| 4 | WP-ACN04 | `POS` shows what the engine holds, also after a restart | C4 | Q5 | 0.5 d | ☐ | |
| 5 | WP-ACN05 | A refused or lost session says why and exits non-zero | C5 | Q6 | 0.25 d | ☐ | |
| 6 | WP-ACN06 | Stop triggers, dates, DC and prices are shown as they are | C6, C7, C8, C9 | — | 0.5 d | ☐ | |
| 7 | WP-ACN07 | Comments, help texts and guides say what the code does | D1–D11 | WP-ACN01–06 | 0.5 d | ☐ | |

Suggested order: **WP-ACN01 → WP-ACN02 → WP-ACN03 → WP-ACN04 → WP-ACN05 →
WP-ACN06 → WP-ACN07**. WP-ACN01 is a one-line-per-handler fix for positions
and orders silently misattributed. WP-ACN02 removes the paths where a typo
logs the participant out and lets the engine cancel their quotes or orders.
WP-ACN03 and WP-ACN04 both change what the console subscribes to and asks for
at connect, so they go next to each other. WP-ACN07 goes last so every text
describes the code as it ends up.

Estimated sequential effort: about 3 days, excluding review time and findings
discovered on the way.

---

## 1. Overall assessment

The **command parser** builds every request with the same generated builders
the other clients use, converts prices to ticks with `to_ticks_exact` and
refuses an off-grid price locally with a clear message. **Authentication and
liveness** are sound: the connect is retried until the ZMTP handshake is done,
a heartbeat thread with its own socket keeps the id alive, and an engine
disconnect logs the session out instead of leaving a console that cannot
trade. The **caches** follow the engine's events correctly for one gateway's
own traffic: a refused amend does not reject a live order, combo/OCO children
are learned from their acks, quote acks are matched by id, and the
`order.orders` reply at connect restores resting orders after a restart.

The defects are in five places:

- **Another participant's events booked as your own (H1).** ZeroMQ
  subscriptions are prefixes, and `order.fill.TRADER1` is a prefix of
  `order.fill.TRADER10`. Every gateway-scoped handler matches by substring,
  so a `TRADER1` console prints `TRADER10`'s fills, acks, cancels and kill
  acks as its own and adds them to `POS` and `ORDERS`. The configs in the
  guides use such ids (`TRADER1`…`TRADER11`, `GW1`…`GW4`).
- **One typo logs the participant out (H2, C2).** Ten kinds of malformed
  value (`PRICE=1O0.5` in AMEND, `TRAIL=0,5`, `QTY=0`, `PRICE=nan`, a 65-char
  `TAG`, …) raise out of the prompt loop. The console sends
  `system.gateway_disconnect`, prints a traceback and exits; the engine then
  applies the participant's `disconnect_behaviour`, by default cancelling all
  their quotes. `STATUS`/`POS` can do the same while the listener thread
  inserts into the dict being printed.
- **Own fills lost without a word (C1, C3, P1).** The SUB socket keeps
  ZeroMQ's default 1000-message buffer and also carries every trade in the
  market. A burst cost the console 1 022 of its own 2 000 fills; nothing
  tells the user, although every message carries a per-topic sequence number.
- **`POS` after a restart (C4).** The position table is built only from fills
  seen in this process, so a restarted console shows "No positions." while
  the engine holds them, and the guide's re-sync playbook tells the user to
  run `POS` to rebuild.
- **Smaller gaps (C5–C9).** An unreachable engine is reported as "Gateway not
  allowed" and every failure exits 0; stop triggers are never shown; a bad
  `INDEX|HISTORY` date silently becomes "last 30 days"; `DC|STATE=ON` prints
  nothing; 3-decimal symbols are printed at 2 decimals.

Severity key: **High**: a participant's positions or orders are misstated, or
their resting quotes/orders are cancelled, without a warning. **Med**: a
lost or misleading figure or event; a failure that ends the session.
**Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Routing | A `TRADER1` console prints `TRADER10`'s fill and books it: `POS` AAPL +100 from another participant's trade *(repro)* | ACN01 |
| H2 | High | Parser | 10 malformed values raise out of the prompt loop: session ends, `gateway_disconnect` sent, engine cancels the participant's quotes (default) or all orders *(repro)* | ACN02 |
| C1 | Med | Feed | Default 1000-message RCVHWM shared with the market-wide trade feed: 1 022 of 2 000 own fills lost in a burst, no warning; per-topic `seq` ignored *(repro)* | ACN03 |
| C2 | Med | Threads | `STATUS` raised `RuntimeError: dictionary changed size during iteration` in 407 of 408 calls while the listener inserted orders; same exit as H2 *(repro)* | ACN02 |
| C3 | Low | Threads | `DC` and `POS\|GW=` call `setsockopt` from the prompt thread on sockets the listener thread polls; ZeroMQ sockets are not thread-safe | ACN03 |
| C4 | Med | Positions | After a console restart `POS` shows "No positions." while the engine holds the position; the guide says `POS` rebuilds it | ACN04 |
| C5 | Low | Exit | Engine unreachable → "Connection refused: Gateway not allowed: NOBODY"; refusal, timeout and lost connection all exit 0 *(repro)* | ACN05 |
| C6 | Low | Events | `order.triggered` is not subscribed: a stop that triggers is never shown, `ORDERS` keeps it as a resting STOP | ACN06 |
| C7 | Low | INDEX | `FROM=2026-13-01` silently becomes "30 days ago"; `FROM` after `TO` is sent *(repro)* | ACN06 |
| C8 | Low | Feedback | `DC\|STATE=ON` prints nothing (guide shows `DC ON`); completion lacks `DC` and `SESSION`, offers `ID=`/`RTAG=` on `NEW` and no `LEG<i>.STOP=` *(repro)* | ACN06 |
| C9 | Low | Format | `POS`, `POS\|GW=`, `QLEGS`, `QBOOT` print prices with `.2f`; the training config has 3-decimal symbols | ACN06 |
| P1 | Low | Listener | 5.9 µs per trade but 373 µs per printed own event: a burst of own events lets the trade feed fill the buffer (feeds C1) *(measured)* | ACN03 |
| D1–D11 | — | Texts | See §5 | ACN07 |

---

## 3. Correctness findings

### H1. Another gateway's events are printed and booked as this gateway's *(repro)* — High

`main.py:373-396` subscribes per gateway:

```python
self.sub_sock = make_subscriber(
    ENGINE_PUB_ADDR,
    topic_order_ack(self.gateway_id),     # "order.ack.TRADER1"
    topic_order_fill(self.gateway_id),    # "order.fill.TRADER1"
    ...
```

A ZeroMQ SUBSCRIBE is a byte prefix (`bus.py:370-371`, "subscribes to one or
more topic prefixes"), and topics have no terminator, so `order.fill.TRADER1`
also matches `order.fill.TRADER10`, `…TRADER11`, `…TRADER1_MM`. The handlers
then match by substring (`PREFIX_ORDER_ACK in topic` at `main.py:846`,
`PREFIX_ORDER_FILL in topic` at `:890`, the same for cancelled, amended,
expired, `"combo.ack" in topic`, `"quote.status" in topic`,
`"risk.kill_switch_ack" in topic`, …) and never compare the gateway part. The
drop-copy handler alone guards against this (`main.py:833-836`); pm-mm-bot
compares the whole topic (`mm_bot/bot.py:1040`); pm-alf-gwy routes by the id
parsed from the topic.

Repro: a `GW1` console, one `make_fill_msg("GW10", …)` for a BUY of 100 AAPL
at 150.00 on the engine's PUB:

```text
GW1 console positions after a GW10 fill: {'AAPL': {'net_qty': 100, 'avg_cost': 150.0, 'realized_pnl': 0.0}}
printed: ['[08:51:11.403] [cyan]FILL[/cyan]      ord-of-gw10  qty=100 @150.0  remaining=0  [FILLED]']
```

Consequences for the `TRADER1` user while `TRADER10` trades:

- `POS` shows `TRADER10`'s position and P&L added to their own.
- `TRADER10`'s acks (combo/OCO children) and `order.orders.TRADER10` replies
  put `TRADER10`'s orders into `ORDERS`; an `AMEND`/`CANCEL` on one is
  rejected with `ORDER_NOT_FOUND`/ownership, with no hint why.
- `TRADER10`'s `KILL ACK`, `QUOTE ACK`, `COMBO FAILED` lines appear on the
  `TRADER1` screen.

The guide says the opposite: "Each session only receives events for its own
orders" (trader console chapter line 1091). Ids that collide are in the books:
`TRADER1`/`TRADER10`/`TRADER11` and `GW1`…`GW4` appear in the docs, and
config-gen's id rule (`[A-Z][A-Z0-9_]{0,31}`) allows them.

**Fix.** See Q1: route on the exact topic. Each gateway-scoped handler checks
that the topic is the prefix plus `self.gateway_id` and nothing else, and drops
the event otherwise.

### H2. A malformed value ends the session, and the engine then cancels *(repro)* — High

`run()` calls `self._parse_and_send(line)` with no guard (`main.py:2050-2057`);
an exception leaves the `while`, the `finally` sends
`system.gateway_disconnect` and closes everything (`:2058-2076`). Several
conversions sit outside the `try` blocks that turn bad input into a message:

| Input | Where | Result |
|---|---|---|
| `AMEND\|ID=abc\|PRICE=1O0.5` | `float(kv["PRICE"])`, `main.py:1533` | `ValueError` |
| `AMEND\|ID=abc\|QTY=ten` | `int(kv["QTY"])`, `:1534` | `ValueError` |
| `NEW\|…\|TYPE=TRAILING_STOP\|…\|TRAIL=0,5` | `float(kv["TRAIL"])` inside `Order.create`, `:1702`; only `TickViolation` caught (`:1708`) | `ValueError` |
| `NEW\|TYPE=OCO\|…\|LEG1_PRICE=abc` | `float(kv[price_key])`, `:1840`; only `TickViolation` caught (`:1849`) | `ValueError` |
| `NEW\|…\|QTY=0` / `QTY=-5` | `make_order_new_msg` validation, `:1728` | `MessageValidationError` |
| `NEW\|…\|PRICE=nan` / `PRICE=inf` | `to_ticks_exact`, `:1691` | `ValueError` / `OverflowError` |
| `QUOTE\|…\|BID=nan` | `to_ticks_exact`, `:1770`; only `TickViolation` caught | `ValueError` |
| `NEW\|…\|TAG=<65+ chars>` | `make_order_new_msg` validation, `:1728` | `MessageValidationError` |

(Combo legs and a non-numeric QUOTE price are caught and reported correctly.)

Driving `run()` with the scripted lines `AMEND|ID=abc|PRICE=1O0.5`, `STATUS`:

```text
run raised ValueError: could not convert string to float: '1O0.5'
engine received: ['order.orders_request', 'system.gateway_disconnect']
last console lines: ['\n[bold]Gateway TRADER01 disconnected.[/bold]']
```

`STATUS` never ran. The engine handles the disconnect with the participant's
`disconnect_behaviour` (`engine/main.py:4509-4530`): the default
`CANCEL_QUOTES_ONLY` (`models/participant.py:25`) cancels every quote of a
market maker, `CANCEL_ALL` cancels every resting order. The user also loses the
console's session-local P&L and quote-leg history. Two of the cases also leave
a ghost `PENDING` row first: `_send_new` caches the order (`:1712-1726`)
before the builder that raises.

**Fix.** See Q2: validate every numeric field inside the command's own
`try`, build the message before caching the order, and guard the prompt loop
so an unexpected exception prints an error and keeps the session.

### C1. Own fills are lost in a burst, and nothing says so *(repro)* — Med

`sub_sock` is created without `rcvhwm` (`main.py:373`), so ZeroMQ's default
receive high-water mark of 1000 messages applies, and a SUB socket drops
silently past it (`bus.py:373-376`). The same socket carries
`TOPIC_TRADE_EXECUTED` (`:395`), which is every trade on the exchange, so the
market's activity, not the user's, decides when the buffer fills. pm-alf-gwy
sets 200 000 (`alf_gwy/gateway.py:164`), and pm-dc-gwy got 100 000 in
WP-DCG01 for the same reason.

Every message published through `make_publisher` carries a per-topic
sequence (`models/message.py:121-128` `decode_sequence`), and pm-alf-gwy
uses it to tell a session about a lost fill (`_check_sequence`). The console
calls plain `decode` (`main.py:768-769`) and ignores it.

Repro: the engine side in its own process publishes 40 000 `trade.executed`
for other participants with 2 000 `order.fill.TRADER01` interleaved; the
console prints with real Rich output (to `/dev/null`):

| Publish rate | Own fills sent | `POS` net qty | Lost | Shown to the user |
|---|---|---|---|---|
| unthrottled (0.34 s, ≈124 000 msg/s) | 2 000 | 978 | **1 022** | nothing |
| 20 000 msg/s | 2 000 | 2 000 | 0 | — |
| 5 000 msg/s | 2 000 | 2 000 | 0 | — |

A lost fill leaves `POS` wrong and the order `NEW`/`PARTIAL` in `ORDERS` for
good. The sim's own open-burst rate was not measured here; P1 shows why the
console's tolerance drops further while it is printing.

**Fix.** See Q3: a deep RCVHWM, and a per-topic sequence check that prints a
red warning and re-requests `ORDERS` (and the position, WP-ACN04) on a gap.

### C2. Printing a table while the listener updates it raises *(repro)* — Med

The listener thread inserts into `order_cache`, `quote_leg_cache` and
`_positions` (`main.py:857-870`, `:1065-1076`, `:1298`), while the prompt
thread iterates the same dicts in Python code: `print_status` (`display.py:414`
`for order in order_cache.values()`), `print_positions` (`display.py:288-293`,
two comprehensions over `positions.items()`). An insertion during such a loop
raises `RuntimeError: dictionary changed size during iteration`, which leaves
the prompt loop exactly like H2.

Repro (Python 3.14.10, GIL enabled): a thread inserting orders into a
5 000-order cache while the main thread calls `print_status` for 5 s:

```text
print_status calls=1 RuntimeErrors=407
```

The load in the repro is artificial; in use the window is `STATUS` or `POS`
typed while acks or fills arrive (a combo's children, a kill switch, the
`order.orders` reply at connect). `print_orders` and `print_quote_legs` copy
the values first (C-level `sorted`/`list`) and were not seen to fail.

**Fix.** Copy before iterating (`list(d.values())` / `dict(d)` in the
printers), plus the loop guard from H2 as the backstop.

### C3. Two threads use the same ZeroMQ sockets — Low

`_set_drop_copy` (`main.py:449-451`) and `_query_position` (`:472-475`) run on
the prompt thread and call `setsockopt` on `_dc_sub_sock` and `sub_sock`,
which the listener thread is polling and reading at the same time
(`:747-806`). ZeroMQ sockets are not thread-safe; the file says so itself
for the heartbeat ("a ZMQ socket must not be shared across threads",
`:668-669`). Not reproduced: the race is in libzmq and rare, but its failure
mode is an assertion abort of the whole process.

`POS|GW=` subscribes right before sending the request (`:475-476`). pm-alf-gwy
gave up exactly this pattern because the reply can overtake the subscription
(`alf_gwy/gateway.py:350-356`). On loopback it did not happen here: 200 of 200
replies arrived *(repro)*, with the fake engine in its own process.

**Fix.** See Q4: subscribe once at start (`system.position_snapshot.` prefix
for `POS|GW=`, the own drop-copy topic), filter in the listener, and let the
prompt thread only flip flags.

### C4. `POS` after a restart shows nothing the engine holds — Med

`_positions` starts empty (`main.py:359-361`) and changes only on an
`order.fill` (`:917`). A restarted console asks the engine for its resting
orders (`:2019`) but not for its position, so `POS` prints "No positions."
for a participant who is long 100 AAPL. The guide's re-sync playbook says the
opposite: "Run `POS` to rebuild your session-local position view from current
stream" (trader console chapter line 950) and "`POS` helps detect drift
between expected and observed exposure" (line 957); a trader following it
concludes they are flat. The engine answers its own gateway's position request
with net quantity and average cost (`engine/main.py:2653-2664`); pm-alf-gwy's
`POS` uses that reply.

**Fix.** See Q5.

### C5. An unreachable engine is reported as a refusal, and failures exit 0 *(repro)* — Low

When `_authenticate` cannot send the connect (`main.py:620-633`) or times out
(`:662-664`), `run()` prints `self._auth_reason or f"Gateway not allowed: …"`
(`:2003`). The send-failure path sets no reason:

```text
$ pm-alf-console --id NOBODY        # no engine running
ERROR … gateway authentication failed to reach engine gateway_id=NOBODY (connection not established)
ERROR … gateway startup refused gateway_id=NOBODY reason=Gateway not allowed: NOBODY
Connection refused: Gateway not allowed: NOBODY
exit=0
```

The guide's triage table says an engine that is not running gives
`Gateway authentication timed out` (lines 170, 1133), and sends the user to
check `participants`. `main()` returns `None` in every case (`:2079-2088`), so
a refused id, an unreachable engine and a lost connection all exit 0; a
wrapper script or the training scripts cannot tell them from `EXIT`.

**Fix.** See Q6: say "engine not reachable" on that path; exit 1 for refusal,
unreachable and lost connection, 0 for `EXIT`/`QUIT`/Ctrl-D.

### C6. Stop triggers are never shown — Low

The engine publishes `order.triggered.<GW>` when a STOP/STOP_LIMIT/
TRAILING_STOP triggers (`spec/messages/order.yaml` `order_triggered`, fields
`becomes`, `trigger_price_ticks`); pm-alf-gwy and pm-balf-gwy relay it. The
console does not subscribe to it (`main.py:373-396`). The user sees nothing
until a fill; a STOP_LIMIT that triggers and rests shows in `ORDERS` as a
resting `STOP` with status `NEW` for the rest of the day.

**Fix.** Subscribe, print `TRIGGERED <id> @<trigger price> → <becomes>`, and
update the cached type.

### C7. A bad `INDEX|HISTORY` date silently becomes the default window *(repro)* — Low

`_parse_date` returns `None` for an unparseable date (`main.py:1989-1995`),
which the caller treats as "not given" (`:1423-1432`).
`INDEX|HISTORY|INDEX=IDX|FROM=2026-13-01` therefore requests the last 30 days
without a word, and `FROM=2026-11-10|TO=2026-11-01` is sent as an empty range.

**Fix.** Refuse an unparseable date and `FROM` after `TO` with a message.

### C8. `DC` gives no feedback, and completion misses commands *(repro)* — Low

`DC|STATE=ON` and `DC|STATE=OFF` print nothing (`main.py:1475-1490`); the
guide shows `[dim]DC ON[/dim]` and lists `DC ON` / `DC OFF` as "printed
immediately" (lines 523, 1018). The completer (`completer.py:14-32`) has no
`DC` and no `SESSION`; before `TYPE=` it offers `ID=` and `RTAG=` for `NEW`
(`completer.py:57-58`, keys of `_FIELD_COMPLETIONS`); combo legs offer no
`LEG<i>.STOP=` (`:260`) although `_send_combo` reads it (`main.py:1937`).

**Fix.** Print the new DC state; complete `DC|STATE=`, `SESSION`; drop
`ID=`/`RTAG=` from `NEW`; add `LEG<i>.STOP=`.

### C9. Prices are printed at two decimals — Low

`print_positions` (`display.py:317-324`), `print_remote_position` (`:371`),
`print_quote_legs` (`:186`) and `print_quote_bootstrap` (`:225-226`) format
prices with `.2f`. The training guide's startup config defines symbols with
`tick_decimals: 3` (`training-guide/010-configuring-startup.md`), so a quote at
10.125 is shown as 10.12 and an average cost loses its last digit. Fill and
amend lines print the raw float instead (`@149.8`, L006).

**Fix.** Format with the symbol's tick decimals (`get_tick_decimals`), one
extra digit for averages, as WP-MMB08 did for pm-mm-bot. This takes over the
console part of L006.

---

## 4. Performance findings

Nothing here matters for a human typing commands. The listener's throughput
matters because of C1.

### P1. Printing an own event costs 60× a trade *(measured)* — Low

| Message | Cost per message | Rate |
|---|---|---|
| `trade.executed` (other participants) | 5.9 µs | ≈170 000 msg/s |
| own `order.fill`, Rich print to `/dev/null` | 373 µs | ≈2 700 msg/s |

A trade only updates `_last_prices`, after about 15 failed substring checks
in `_handle_event`. An own event is formatted and printed by Rich through the
`_SysStdoutProxy`, slower still on a real terminal under `patch_stdout`. A
burst of own events (a `KILL` cancelling 2 000 orders prints 2 000 lines,
≈0.75 s) is when the market-wide trade feed overruns the 1000-message buffer
(C1). The cost does not grow with the session; `order_cache` and
`quote_leg_cache` grow with it but are only iterated on a command.

**Fix.** None beyond C1's buffer: the printing cost is the price of a
readable console.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `main.py:203-206` (`--drop-copy` help) | Prints a repository-relative path `See ../../../docs/books/…/060-drop-copy.md` in `--help`, meaningless to a user. |
| D2 | `main.py:1-50` (module docstring) | Calls the process "Gateway — user-facing terminal process" (the guide's first section is "`pm-alf-console` is not a gateway"); command list misses `CLEAR`; mixed indentation. |
| D3 | `main.py:331-333`, `:455-472` | "receiving (or timing out)" and "a stale or mistyped gateway id does not leave a permanent extra subscription": there is no timeout; the subscription goes only because the engine answers every id (C3 changes this code anyway). |
| D4 | `display.py:78-79` (`HELP`) | `TIF : DAY (default) GTC` omits `ATO`/`ATC`, which the parser accepts and the completer offers; `SMP : NONE (default)` is wrong: omitted means the participant's configured `smp_action`. |
| D5 | `display.py:82`, `:89` (`HELP`) | OCO line has no `LEG<n>_TRAIL`; combo line has no `LEG<i>.TYPE`, `LEG<i>.STOP`, `SMP`, `TAG`. |
| D6 | `pm_help/registry.py:200-204` | "Full command vocabulary" omits `STATUS`, `POS`, `POS\|GW=`, `SESSION`, `DC`, `QBOOT`, `INDEX`, `CLEAR`, and the OCO/COMBO forms of `NEW`. |
| D7 | trader console chapter lines 963, 1125-1127 | "prints events (fills, cancels, combo status changes, session transitions)": session transitions are not printed (the same chapter says so at line 1031). |
| D8 | trader console chapter line 975 | `EXPIRED <id> (DAY order — trading day ended)`: the code prints `(Trading day ended)` (`main.py:987-1000`). |
| D9 | trader console chapter lines 166, 1104-1114 | Subscription list omits `system.session_status.{ID}` (and will change with WP-ACN03/04/06); completion table to be updated with C8. |
| D10 | reference manual lines 591-628 | "Messages sent" lists 7 of the 19 the console sends (no amend, OCO, quote, kill, heartbeat, disconnect, position, session, bootstrap, index); "Messages subscribed" omits the cancel acks, `system.quote_bootstrap`, `system.session_status`, `system.position_snapshot`, the index and drop-copy sockets; runtime commands omit `STATUS`, `POS`, `SESSION`, `DC`, `QBOOT`, `INDEX`, `CLEAR`. |
| D11 | trader console chapter lines 655, 1049, 1067, 1140 | "Full order UUID": order ids are 32 hex characters, not UUIDs (`models/ids.py:16-24`); the chapter itself says "32-character order ID" at line 733. |

---

## 6. Verified as correct

- **Authentication.** The connect is resent until the ZMTP handshake allows
  it (`main.py:618-633`); the reply is matched on the exact topic
  (`:646`), so H1 does not reach authentication.
- **Engine loss.** `EVENT_DISCONNECTED` on `sub_sock` and a failed heartbeat
  or command send both log the session out once (`_engine_connection_lost`
  is idempotent via `_running`) and exit the prompt from its own loop with
  `call_soon_threadsafe`.
- **Order-id case.** Values for `ID`, `TAG`, `RTAG`, `COMBO_ID`, `OCO_ID`,
  `QUOTE_ID` keep their case (`_CASE_SENSITIVE_KEYS`); everything else is
  upper-cased, which is right for enums, symbols and gateway ids.
- **Ticks.** `NEW`, `QUOTE`, OCO legs and combo legs convert with
  `to_ticks_exact` and refuse off-grid prices locally. AMEND sends a display
  price; the engine converts it with `to_ticks_exact` itself
  (`engine/main.py:7096-7110`), so an off-grid amend is refused there.
- **Average-cost accounting.** `_update_position` (`main.py:1294-1328`)
  realises P&L on reductions, keeps the average on reductions, resets it on
  flat and takes the fill price on a flip; checked against hand-computed
  sequences (add, reduce, flip, close).
- **`order.orders` restore.** The connect-time reply is merged into the cache
  (`main.py:1030-1098`), quote legs included, so `ORDERS`, `AMEND` and
  `CANCEL` work after a restart.
- **`POS|GW=` reply matching.** A reply is accepted only on the outstanding
  topic, compared exactly (`main.py:488`); 200 of 200 replies arrived in
  the repro.
- **Prefix guard on drop copy.** `_handle_dc_event` compares the whole topic
  (`main.py:833-836`), so `DC_FILL` lines are not affected by H1.
- **No contract multiplier** exists in the codebase, so P&L as
  `(price − avg) × qty` is the engine's definition too.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | How to stop prefix leaks (H1): (a) keep the subscriptions, compare the topic to `<prefix><own id>` exactly in every gateway-scoped branch; (b) change the topic scheme to end with a delimiter; (c) refuse gateway ids that prefix another in config. | **(a)**: one comparison per handler, no wire change. (b) changes every producer and consumer of the gateway-scoped topics; (c) rejects configs the books already use. |
| Q2 | What a bad command line does (H2): (a) every numeric conversion and the message build inside the command's `try`, reported as a parse error, plus a guard around `_parse_and_send` that prints the error, logs it at ERROR with the traceback, and keeps the session; (b) only the guard; (c) only the per-field validation. | **(a)**. (b) alone prints Python messages ("could not convert string to float") and still leaves the ghost `PENDING` row; (c) alone leaves the next unforeseen exception (C2) ending the session. |
| Q3 | Lost own events (C1): (a) `rcvhwm=200_000` as pm-alf-gwy, plus a per-topic sequence check on the own topics that prints `WARNING: n event(s) lost on <topic> — ORDERS/POS re-synced` and re-requests orders and position; (b) (a) plus a separate SUB socket for `trade.executed` so the market feed can never evict own events; (c) only the deeper buffer. | **(a)**. (c) still loses silently, only later. (b) is stronger but adds a fourth socket for a case (a) already makes visible and recoverable. |
| Q4 | Cross-thread `setsockopt` (C3): (a) subscribe at start to `system.position_snapshot.` (all gateways; one message per query anyone makes) and to the own drop-copy topic, and filter in the listener by flags the prompt thread sets; (b) pass subscribe requests to the listener through a queue it drains each pass. | **(a)**: less code, and it also removes the subscribe-then-request race. Cost: the own drop-copy topic is received while DC is off, a handful of messages per own fill, discarded. |
| Q5 | `POS` after a restart (C4): (a) at connect and after a C1 gap, request the own `system.position_snapshot` and seed net quantity and average cost; realised P&L stays session-local and the table says "since connect"; (b) make `POS` always ask the engine, as pm-alf-gwy does, dropping local P&L; (c) docs only. | **(a)**: keeps the console's P&L view, fixes the number that matters. (b) removes realised/unrealised P&L that the training chapters use; (c) leaves a trader believing they are flat. |
| Q6 | Exit codes (C5): (a) 1 for refused, unreachable and lost connection, 0 for `EXIT`/`QUIT`/Ctrl-D/Ctrl-C at the prompt; (b) distinct codes per cause. | **(a)**: no caller distinguishes causes today; the printed reason does. |

---

## 8. Work packages

### WP-ACN01 — Only this gateway's own events reach its screen and caches (H1; after Q1)

**Tests first** (`tests/test_alf_console_routing.py`):

1. A `TRADER1` console receives `order.fill.TRADER10` (engine builder, real
   PUB/SUB): nothing printed, `_positions` empty, `order_cache` unchanged.
   (Fails today.)
2. The same for `order.ack`, `order.cancelled`, `order.amended`,
   `order.expired`, `order.orders`, `combo.ack`, `combo.status`, `oco.ack`,
   `oco.cancelled`, `quote.ack`, `quote.status`, the three cancel acks,
   `risk.kill_switch_ack`, `system.symbols`, `system.quote_bootstrap`,
   `system.session_status`, `index.history`, `index.error` for `TRADER10`
   (parametrised, `_handle_event` direct). (Fails today for most.)
3. `order.fill.TRADER1` is printed and booked, unchanged.
4. `trade.executed` and `index.update` (broadcast) still update last prices
   and the index cache, unchanged.

**Change.** In `_handle_event`, compare each gateway-scoped topic with the
exact `topic_<x>(self.gateway_id)` (precomputed once in `__init__`) instead of
substring tests; broadcast topics keep their exact constants.

**Exit criteria.** Tests 1–4 pass; `tests/test_alf_console_*.py` green.

### WP-ACN02 — No typed line or table print ends the session (H2, C2; after Q2)

**Tests first** (`tests/test_alf_console_input.py`):

1. Each input of the H2 table through `_parse_and_send`: no exception, one red
   message naming the field, nothing sent, no `PENDING` row added.
   (Fails today.)
2. `run()` with a scripted prompt `AMEND|ID=abc|PRICE=1O0.5`, `STATUS`,
   `EXIT`: `STATUS` runs, the engine receives exactly one
   `system.gateway_disconnect`, at the end. (Fails today.)
3. An unexpected exception raised by a patched handler: printed as an
   error, logged at ERROR with the traceback, prompt continues. (Fails today.)
4. `print_status`/`print_positions` while a thread inserts into the dicts
   (the review's 5 s loop, shortened): no `RuntimeError`. (Fails today.)
5. Valid `NEW`, `AMEND`, OCO, `QUOTE` lines send the same frames as today,
   unchanged.

**Change.** Move the numeric conversions (AMEND, TRAIL, OCO leg prices) and
`make_order_new_msg(...)` inside the command's `try`, catching
`ValueError`/`OverflowError` (`TickViolation` and `MessageValidationError` are
`ValueError`s); cache the order only after the frames are built. Wrap
`_parse_and_send` in `run()` with `except Exception` → red line + `log.exception`.
Copy dicts before iterating in `print_status` and `print_positions`.

**Exit criteria.** Tests 1–5 pass; suites green.

### WP-ACN03 — A burst never silently costs the console its own events, and only the listener touches its sockets (C1, C3, P1; after Q3, Q4)

**Tests first** (`tests/test_alf_console_delivery.py`, real sockets):

1. The C1 repro scaled to the test budget (engine side in a subprocess,
   unthrottled, ≥ 20 000 trades with 1 000 own fills): every own fill booked.
   (Fails today.)
2. A gap in `order.fill.<own>` sequence numbers (publisher with a skipped
   seq, or two messages dropped by a filter): one red `WARNING … lost` line,
   one `order.orders_request` (and one own `system.position_request` after
   WP-ACN04) pushed. (Fails today.)
3. `DC|STATE=ON`/`OFF` and `POS|GW=X` make no `setsockopt` call on any socket
   after `__init__` (spy on the sockets). (Fails today.)
4. `POS|GW=X` still prints X's reply and ignores a reply for Y; DC on/off
   still shows/hides `DC_FILL`, unchanged.

**Change.** `rcvhwm=200_000` on `sub_sock` and `_dc_sub_sock`; read the
trailer with `decode_sequence` for own-topic messages and keep the last seq
per topic; on a gap print the warning and re-request. Subscribe at start to
`PREFIX_POSITION_SNAPSHOT` and the own drop-copy topic; `_set_drop_copy` and
`_query_position` only set fields the listener reads.

**Exit criteria.** Tests 1–4 pass; suites green. Test 1's loss count is 0 at
the burst size used; record the measured rate.

### WP-ACN04 — `POS` shows what the engine holds, also after a restart (C4; after Q5)

**Tests first** (`tests/test_alf_console_positions.py`):

1. At connect the console pushes `system.position_request` for its own id.
   (Fails today.)
2. A `system.position_snapshot.<own>` reply with AAPL +100 @ 150.00 seeds
   `_positions`; `POS` shows +100 and 150.00, realised P&L `0.00`.
   (Fails today.)
3. A later own fill (SELL 40 @ 151.00) on top of the seed gives +60, realised
   +40.00. (Fails today.)
4. A `POS|GW=<own id>` query still prints the engine table, unchanged.

**Change.** Send the own position request after the orders request in
`run()`; the reply for the own id (not an outstanding `POS|GW=`) replaces
`net_qty`/`avg_cost` per symbol and keeps realised P&L. Title the table
"Positions (P&L since connect)".

**Exit criteria.** Tests 1–4 pass; suites green.

### WP-ACN05 — A refused or lost session says why and exits non-zero (C5; after Q6)

**Tests first** (`tests/test_alf_console_exit.py`):

1. Connect send never succeeds: prints `Engine not reachable …`, `main()`
   exits 1. (Fails today: "Gateway not allowed", 0.)
2. Auth rejected: prints the engine's reason, exits 1. (Fails today: 0.)
3. Engine connection lost during the session: exits 1. (Fails today: 0.)
4. `EXIT` and Ctrl-D: exit 0, unchanged.

**Change.** Set `_auth_reason` on the unreachable path; `run()` returns a
status; `main()` passes it to `sys.exit`.

**Exit criteria.** Tests 1–4 pass; suites green; `make completion` unchanged.

### WP-ACN06 — Stop triggers, dates, DC and prices are shown as they are (C6, C7, C8, C9)

**Tests first** (`tests/test_alf_console_display.py`,
`tests/test_alf_console_completer.py`):

1. `order.triggered.<own>` for a cached STOP_LIMIT: a `TRIGGERED` line with
   the trigger price, cached type becomes `LIMIT`. (Fails today.)
2. `INDEX|HISTORY|INDEX=X|FROM=2026-13-01` and `FROM` after `TO`: a red
   message, nothing sent. (Fails today.)
3. `DC|STATE=ON` prints `DC ON`; `OFF` prints `DC OFF`. (Fails today.)
4. Completer: `D`→`DC`, `SE`→`SESSION`, `NEW|` offers no `ID=`/`RTAG=`,
   combo offers `LEG0.STOP=`. (Fails today.)
5. A 3-decimal symbol: `POS` avg cost, `QLEGS` and `QBOOT` prices show 3
   decimals; 2-decimal symbols unchanged.

**Change.** Subscribe `topic_order_triggered`; refuse bad dates in the
`INDEX` branch; print the DC state; completer lists; format with
`get_tick_decimals` (averages one digit more). Update L006's status for the
console part.

**Exit criteria.** Tests 1–5 pass; suites green; `make completion` if help
changed.

### WP-ACN07 — Comments, help texts and guides say what the code does (D1–D11; after WP-ACN01–06)

**Tests first.** `tests/test_alf_console_help.py`: `HELP_TEXT` mentions
`ATO`, `ATC`, `LEG1_TRAIL`, `LEG<i>.STOP` and does not say `NONE (default)`;
`build_parser().format_help()` contains no `../`. (Fails today.)

**Change.** D1–D11 as listed in §5; the trader console chapter's subscription
list, triage table (C5 message), re-sync playbook (C4), DC example (C8), event
tables (`TRIGGERED`, the gap warning), completion table; the reference manual
tables; the pm-help registry notes. Re-walk the chapter's walkthrough and
re-sync playbook against the final code (lessons-learned §B1).

**Exit criteria.** Test passes; `make _check` clean; `mkdocs build` clean.

---

## 9. Out of scope, noted

- **`POS|GW=` for an unknown or disconnected id prints "flat".** The engine
  answers both with an empty snapshot (`engine/main.py:2649-2651`), so
  `POS|GW=MM_APPL_01` (a typo) or a market maker that is offline both print
  `flat (no open positions)`. This is L030's engine behaviour; the console
  case is added to L030 rather than fixed here.
- **`-q` is the default** (`main.py:224`, `:266-269`). L034 asks for one
  decision for every process; not changed here so this entry point does not
  drift from the others.
- **Float formatting of prices (L006).** The console part is taken over by
  WP-ACN06 (C9); `pm-admin`'s part stays in L006.
- **`ORDERS` sorts by `HH:MM:SS`** (`display.py:595`), so GTC orders from
  earlier days restored at connect interleave with today's. Cosmetic; not a
  defect.
