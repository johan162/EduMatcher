# pm-mm-bot Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/mm_bot/` at `16d71c69` (v0.79.0): `bot.py` (2 063
lines, the state machine and event loop), `pricer.py` (535, the three pricing
strategies), `main.py` (611, the `pm-mm-bot` CLI), `config.py` (294, the YAML
loader), `params.py` (246, parameter tiers and validation), `resolve.py`
(106, the precedence merge) and `cli_scope.py` (89, the `--symbol` scope
splitter). Nothing else imports the package. The engine code the bot talks to
(`_handle_quote_new`, `_on_quote_leg_filled`, `_publish_dispatch`,
`_handle_quote_cancel`, `_cancel_symbol_quotes`, the halt/resume handlers,
`_handle_symbols_request`, `_handle_quote_bootstrap_request`) was read where it
decides the bot's behaviour. It was not reviewed as code of its own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the `pm-help` entry, the participant guide chapter
(`participant-guide/part-3-market-making/030-the-market-maker-bot.md`), the
reference manual entry and the training chapters 020/210 say what the code
does.

**Previous work:** `docs-design/EduMatcher-MM-Bot-review.md` (v1.5.0, phases A
and B plus the multi-symbol plan §5a), `EduMatcher-mm-bot-multi.md` (the
two-tier parameters and the config-file schema) and `EduMatcher-MM-bots.md`.
Their fixes are in place and are not repeated here: `register_tick_decimals`
on the symbols reply, the config file and strategy factory, one process for
many symbols with per-symbol failure isolation, quote ids minted by the bot
and matched by id, the engine's orphaned-leg cancel on replace. For-Later
L006 (raw float prices, partly the bot's) and L014 (an `--anchor-sim` start
reference) name this component; see D9 and §9.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `16d71c69` that wire
a real `MMBot` to a real `Engine` in one process: the bot's PUSH frames go to
`Engine._dispatch_pull_message`, and the engine's PUB frames go to
`MMBot._dispatch` when the bot subscribes to the topic. Takers, halts and
resumes are real `order.new`, `risk.symbol_halt` and `risk.symbol_resume`
messages from configured `TRADER` and `ADMIN` participants. Config findings
were reproduced through the real `main()`. *(measured)* means timed on this
host (Xeon W-2295, 36 threads) with `timeit` against a bot holding 1, 30 and
300 quoting symbols. The other findings are by inspection, with line numbers
given.

Status: **Done, uncommitted.** WP-MMB01–08 completed 2026-11-15 in order,
each test-first and verified with `make _check` and the full suite (last run:
14 548 passed, 1 skipped). Decisions Q1–Q5 taken as recommended (the user
asked for all WPs in one go). Beyond the plan: the periodic QLEGS check had
C1's primary-symbol fallback too and is now gateway-wide (WP-MMB03); the B1
re-walk found training chapter 02 relying on the unenforced obligation C4
removed, fixed in WP-MMB04. Behaviour visible to users: a flat config file is
refused; a missing symbols reply is a start-up failure; the bot asks the
engine for its position at start-up; QBOOT/QLEGS are asked once per gateway;
a refused quote is a WARNING once per reason.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (orders resting in the engine's book, the bot's
   tracked position against the engine's ledger, messages the bot sends, log
   records and their level, CLI exit code).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_mm_bot*.py` and
   `tests/test_mm_quotes_engine.py` with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

The defects in H1, H2, C1 and C2 come from the *order* in which the engine
publishes, which the existing unit tests choose themselves (they deliver
`order.fill` before `quote.status`; the engine does the opposite). Their tests
must therefore run the real engine. WP-MMB01 adds
`tests/test_mm_bot_engine_wired.py` with a fixture that builds an `Engine` the
way `tests/test_mm_quotes_engine.py::_make_engine` does (plus a `TRADER` and an
`ADMIN` participant) and an `MMBot` with a recording PUSH socket, and a
`pump()` helper that moves frames both ways and calls `MMBot._tick()`. Later
WPs reuse it. Time is advanced by patching `edumatcher.mm_bot.bot.time.monotonic`.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-MMB01 | Every fill of the bot's own legs is counted | H2, D5 | Q1 | 1 d | ☑ | 2026-11-15 |
| 2 | WP-MMB02 | A halted or paused symbol always comes back, and never quotes while paused | H1, C2 | WP-MMB01 | 0.5 d | ☑ | 2026-11-15 |
| 3 | WP-MMB03 | Every reply is applied to the symbol it belongs to | C1, C9, D1 | WP-MMB01 | 0.5 d | ☑ | 2026-11-15 |
| 4 | WP-MMB04 | Obligations are applied only when enforced; a refused quote is visible and backs off | C3, C4, D10, D11 | Q3, Q4 | 0.5 d | ☑ | 2026-11-15 |
| 5 | WP-MMB05 | Start-up uses the engine's facts: symbol metadata and the current position | C5, C6 | Q2, WP-MMB03 | 0.5 d | ☑ | 2026-11-15 |
| 6 | WP-MMB06 | Configuration is validated before anything starts; SIGTERM is honoured during start-up | C7, C8, C10 | Q5 | 0.5 d | ☑ | 2026-11-15 |
| 7 | WP-MMB07 | Message dispatch costs the same for 1 or 300 symbols | P1 | WP-MMB03 | 0.25 d | ☑ | 2026-11-15 |
| 8 | WP-MMB08 | Comments, help texts, pm-help, guide and reference manual | D2–D4, D6–D9 | WP-MMB01–07 | 0.5 d | ☑ | 2026-11-15 |

Suggested order: **WP-MMB01 → WP-MMB02 → WP-MMB03 → WP-MMB04 → WP-MMB05 →
WP-MMB06 → WP-MMB07 → WP-MMB08**. WP-MMB01 and WP-MMB02 are the two defects
that make the bot do something other than what it says on every run: it
ignores its own fills, and it walks away from a symbol after any halt. Both
need the wired test fixture WP-MMB01 builds. WP-MMB03 changes the same
id-to-symbol maps as WP-MMB01, and WP-MMB07 changes the dispatch WP-MMB03
touches. WP-MMB08 goes last so every text describes the code as it ends up.

Estimated sequential effort: about 4.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **pricing** is sound. `QuotePricer`'s tick rounding and two-tick minimum
spread, the `inventory_skew` formula and the `passive` plan reproduce every
worked example in the guide exactly (all eight rows of the passive table and
the skew example, §6). The parameter layer is careful: one module owns the
tiers, every merged value is validated with the symbol named in the message,
and the precedence ladder is implemented as documented. Quote ids are minted
by the bot, so acks and statuses are matched by id rather than by arrival
order.

The defects are in five places:

- **The bot never sees its own fills (H2).** Since 2026-10-23 (`5b2aea31`,
  "pull quote sibling at the fill") the engine publishes `quote.status
  INACTIVE_*_FILLED` before the `order.fill` that caused it, and says so in
  its own docstring. The bot clears the quote's leg ids on the status, so the
  fill that follows matches nothing and is dropped. In a wired repro the
  engine's ledger says 400 long, the bot says 0. `inventory_skew` never
  skews, `passive` never fades (the `mm-demo` profile's teaching point), and
  the guide's "the two positions always agree" is false.
- **A halt is a one-way door (H1, C2).** After a circuit-breaker or operator
  halt and resume, the symbol sits in `WAITING_FOR_SESSION` with nothing
  scheduled, and nothing ever moves it on while the session stays
  `CONTINUOUS`. The bot stops quoting that symbol for the rest of the day.
  A quote in flight at a phase change also rests through the auction.
- **Replies reach the wrong symbol (C1, C9).** A `quote.status` with an id the
  bot has forgotten is applied to the *first* symbol, which then drops its
  live quote's tracking and re-quotes. Start-up waits take the first reply
  for the gateway, whichever symbol it is for.
- **The bot does not use what the engine tells it (C3–C6).** It applies an
  MM obligation the engine does not enforce, ignores the minimum size it is
  told, retries a quote the engine will always refuse four times a second
  with the reason logged only at INFO, quotes with guessed tick sizes when the
  symbols reply is late, and starts `inventory_skew` flat whatever it holds.
- **Configuration edges (C7, C8, C10).** A quoted number in the `gateway:`
  block gives a traceback, `logging.level: verbose` is accepted, NaN is a
  valid gap, and the legacy flat file turns `id_suffix: 01` into
  `MM_AAPL_1`.

Severity key: **High**: the bot silently stops making the market it was
started to make, or trades on a position it does not know. **Med**: a wrong
quote, a lost quote, a wrong figure, or a failure invisible at the default
log level. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Session | After a halt and resume the symbol stays in `WAITING_FOR_SESSION` with no reissue scheduled; nothing moves it on while the session is `CONTINUOUS`. 30 s after the resume: no quote, empty book *(repro)* | MMB02 |
| H2 | High | Fills | The engine publishes `quote.status INACTIVE_*` before the `order.fill`; the bot has cleared the leg ids and drops the fill. Two taker sells of 100 and 300: engine position 400, bot position 0; `passive` fade never starts *(repro)* | MMB01 |
| C1 | Med | Routing | A `quote.status` with an unknown `quote_id` is applied to the primary symbol: MSFT's replaced-quote `CANCELLED` clears AAPL's tracking and makes AAPL re-quote *(repro)* | MMB03 |
| C2 | Med | Session | A phase change while a `quote.new` is in flight pauses without cancelling; the accepted ack then sets `QUOTING`, and the quote rests through the auction *(repro)* | MMB02 |
| C3 | Med | Rejects | A quote the engine always refuses (size below `mm_min_qty`) is retried every `reissue_delay_ms` forever: 41 rejects in 10 s, each logged at INFO only, invisible at the default WARNING *(repro)* | MMB04 |
| C4 | Med | Obligation | The bot applies `mm_max_spread_ticks` although `enforce_mm_obligation` is false: `--gap 0.30` is excluded on the default 20-tick value; the default gap and the `passive` band are derived from it *(repro)* | MMB04 |
| C5 | Med | Start-up | When the symbols reply times out (fixed 3 s), every symbol starts with tick size 0.01 and no existence check; a 4-decimal symbol is quoted at 1/100 of its price | MMB05 |
| C6 | Med | Position | The tracked position starts at 0 at every start; a restart with inventory runs `inventory_skew` flat, and fills on an adopted quote during the start-up waits are dropped | MMB05 |
| C7 | Low | Config | `gateway.startup_session_timeout_sec: "5"` → `TypeError` traceback; `logging.level`/`target` are not validated; `label`/`engine_pull` may be numbers; NaN and inf pass every range check (`--gap nan` crashes at the first quote) *(repro)* | MMB06 |
| C8 | Low | Config | The legacy flat file: `id_suffix: 01` → `MM_AAPL_1`; `retreat_ticks`, `anchor_sim`, `gateway_id` are "unknown keys"; `symbol:` plus `symbols:` silently drops `symbol` *(repro)* | MMB06 |
| C9 | Low | Start-up | QBOOT and QLEGS are asked per symbol and the wait takes the first reply for the *gateway*: a late reply is taken as the next symbol's; 2N serial round trips at start-up | MMB03 |
| C10 | Low | Signals | SIGINT/SIGTERM during start-up only clear a flag that start-up never reads; the bot finishes start-up, sends its quotes, then cancels them | MMB06 |
| P1 | Low | Dispatch | Every message is matched by building three topics per quoted symbol: 62 µs per fill, status or trade at 300 symbols, against 1 µs for one *(measured)* | MMB07 |
| D1–D11 | — | Comments | See §5 | MMB08 (D1: MMB03; D5: MMB01; D10, D11: MMB04) |

---

## 3. Correctness findings

### H1. A halted symbol never comes back *(repro)* — High

`bot.py:1511-1529` `_handle_circuit_breaker_halt`/`_resume`;
`bot.py:1488-1509` `_handle_session_state`; `bot.py:1608-1680` `_tick_symbol`.

A halt cancels the symbol's quote, sets `PAUSED` and clears `reissue_at`. The
resume sets `WAITING_FOR_SESSION` and nothing else. From there:

- the reissue timer only fires when `reissue_at` is set (`bot.py:1612`), and
  nobody sets it;
- the heartbeat guard only acts in `QUOTING`, `REISSUING` or `REPRICING`
  (`bot.py:1661`);
- drift, `requote_due` and QLEGS only act in `QUOTING`;
- a `session.state` to `CONTINUOUS` only revives `PAUSED` (`bot.py:1498`),
  and while the market stays open no such transition comes.

Reproduced with the wired engine (an `ADMIN` `risk.symbol_halt`, then
`risk.symbol_resume`, then 30 s of bot time with ticks every 0.5 s):

| step | bot state | `reissue_at` | MM01's resting orders |
|---|---|---|---|
| quoting | `QUOTING` | — | BUY 99.95 × 500, SELL 100.05 × 500 |
| after the halt | `PAUSED` | `None` | none |
| after the resume | `WAITING_FOR_SESSION` | `None` | none |
| 30 s later | `WAITING_FOR_SESSION` | `None` | none |

The symbol has no market maker until the session next leaves and re-enters
`CONTINUOUS`, normally the next day. Nothing is logged at WARNING; the health
beacon still counts the symbol in `mmbot.symbols_active`. Every circuit
breaker trip in a sim run, every timed reopen, and the halt/resume runbook in
training chapter 21 (`210-automation-commandclient-mm-bot.md`, Exercise 2)
trigger it. The guide's state diagram and its "it resumes on the matching
resume event" describe the intended behaviour, not this one.

**Fix.** On resume, schedule an immediate reissue when the session is a
quoting session (as `PAUSED → CONTINUOUS` already does); on a transition into
`CONTINUOUS`, revive `WAITING_FOR_SESSION` as well as `PAUSED`.

### H2. The bot drops every fill of its own quote legs *(repro)* — High

`bot.py:1347-1377` `_handle_quote_status`; `bot.py:1394-1462`
`_handle_order_fill`; `bot.py:1172-1181` `_clear_quote_state`;
`engine/order_book.py:2132-2136`; `engine/main.py:3588-3593`.

Under `INACTIVATE_ON_ANY_FILL` (the policy the guide recommends) the book
calls the engine's quote hook *during* the sweep, so the sibling's
`order.cancelled` and the `quote.status INACTIVE_*_FILLED` are published
before `_publish_dispatch` publishes the fills. The engine documents this:
"Consumers must not infer the causal order solely from receipt order"
(`engine/main.py:3588-3593`, introduced with `5b2aea31` on 2026-10-23). The
wire order for one taker sell, as published:

```
order.ack.T1
order.cancelled.MM01        (the ask, pulled by the hook)
quote.status.MM01 INACTIVE_BID_FILLED
order.fill.T1 FILLED
order.fill.MM01 PARTIAL     (the bot's bid)
trade.executed
```

On the status the bot calls `_clear_quote_state`, which forgets
`bid_order_id`/`ask_order_id`. The fill then matches no leg; because the
symbol now has no leg ids, it is buffered in `_pending_fills`
(`bot.py:1410-1418`); at the next `quote.ack` it is re-dispatched against the
*new* quote's ids, matches nothing again, and is discarded. The same happens
to fills on the hit leg's remainder, which the engine leaves resting until
the reissue replaces it.

Reproduced with `--strategy inventory_skew --max-position 1000`, a 500 × 500
quote at 99.95/100.05 and `--reissue-delay-ms 200`:

| step | engine ledger (MM01, AAPL) | bot `net_position` | bot's next quote |
|---|---|---|---|
| taker sells 100 at 99.95 | +100 | 0 | — |
| taker sells 300 into the remainder, before the reissue | +400 | 0 | — |
| reissue | +400 | **0** | 99.95 / 100.05 (unskewed; +400 should give 99.93 / 100.03) |

With `passive` (`--fade-ticks 3 --fade-sec 20`), after a full fill of the bid
the reissued bid is at home (99.95) instead of faded to 99.92, and
`_fade_until["BID"]` is still `0.0`: `on_fill` is never called. The `mm-demo`
process profile (`--fade-ticks 3 --fade-sec 20`, reference manual
`010-processes-environment-and-ports.md:3799`) is meant to show exactly that
fade to students. The own-leg quantities `passive` subtracts from book
snapshots are never reduced either.

The 516 existing tests pass because they deliver `order.fill` before
`quote.status` themselves.

**Fix (see Q1).** Keep a bounded map from every leg order id the bot has
quoted (current and retired) to its symbol and side, and resolve fills
through it rather than through the current quote's ids. Clearing the quote
state must not forget where earlier legs belonged.

### C1. A stale `quote.status` is applied to the first symbol *(repro)* — Med

`bot.py:1356-1357`.

```python
symbol = self._quote_id_to_symbol.get(quote_id, self._primary_symbol)
```

`_clear_quote_state` removes the quote's id from `_quote_id_to_symbol`
(`bot.py:1175-1176`), and several paths clear the state while the engine
still holds the quote: a QLEGS divergence (`bot.py:1725, 1742, 1761`), the
cancel-confirmation timeout (`bot.py:1630`), a halt or a phase change. When
the engine's `CANCELLED` for that quote arrives (from the replace-in-slot of
the reissue, or from the cancel), its id is unknown and the status is applied
to the primary symbol.

Reproduced with a two-symbol bot (AAPL first, MSFT second), both quoting:
MSFT's QLEGS-divergence path clears MSFT and reissues. The engine replaces
MSFT's old quote and publishes `CANCELLED "Replaced by new quote"` with
MSFT's old id. AAPL, which is `QUOTING` with a quote id, takes it: its
tracking is cleared and it is re-quoted (two `quote.ack`s for AAPL instead of
one). Between the two, fills on AAPL's real legs match nothing (H2's
mechanism). On a one-symbol bot the fallback is harmless; on a multi-symbol
bot one symbol's housekeeping disturbs another's quote, which the guide says
never happens ("a fill, cancel, drift, or QLEGS divergence on one symbol
never touches another symbol's quoting").

**Fix.** An unknown id is ignored (counted at DEBUG), never mapped to the
primary symbol. Forget a quote id only when the engine reports the quote
gone, not when the bot stops tracking it. `quote.ack` now carries `symbol`
(`models/generated/quote.py:524`), so the ack needs no fallback at all.

### C2. A quote in flight at a phase change rests through the auction *(repro)* — Med

`bot.py:1503-1509`, `bot.py:1327-1340`.

On a non-quoting phase, `_handle_session_state` cancels only symbols in
`QUOTING` or `REPRICING`. A symbol in `REISSUING` (quote sent, ack pending) is
set to `PAUSED` without a cancel. The engine accepts quotes in every phase
except `CLOSED` (`models/session.py:49-51`), so the ack is positive, and
`_handle_quote_ack` sets `QUOTING` regardless of the current state.

Reproduced: a drift reprice sends a new quote; `session.state
CLOSING_AUCTION` reaches the bot before the ack. Result: the bot is `QUOTING`,
and BUY 100.95 × 500 / SELL 101.05 × 500 rest in the book 20 s into the
auction, where the guide promises "cancel any live quote; wait". The legs take
part in the uncross. If the bot re-quotes during that phase (a drift, a
fill), the reissue timer finds a non-quoting session and sets
`WAITING_FOR_SESSION` (`bot.py:1633-1636`), which is H1's dead end. The halt
handler already cancels in `REISSUING` (`bot.py:1518`); the session handler
does not.

**Fix.** Cancel on a non-quoting phase in `REISSUING` too, and treat an
accepted ack that arrives while `PAUSED` as a quote to cancel, not a reason to
quote.

### C3. A quote the engine always refuses is retried forever, invisibly *(repro)* — Med

`bot.py:1341-1345`, `bot.py:699-700`.

A rejected ack logs `quote REJECTED: <reason>` through `_log`, which is INFO,
and schedules a retry after `reissue_delay_ms`. Nothing counts rejections or
slows down. Reproduced with an engine enforcing `mm_min_qty: 1000` and the
default `--qty 500`: 41 `quote.ack accepted=false "Quote size must be >= 1000"`
in 10 s of bot time, every one at INFO, so with the default WARNING level the
operator sees a running bot and an empty book. The guide's troubleshooting row
for `quote REJECTED` assumes the line is visible.

The bot receives `mm_min_qty` in the symbols reply (`engine/main.py:2541-2542`)
and ignores it, so this one cause could be refused at start-up, like a gap
that violates `mm_max_spread_ticks`. A halted symbol (`... halted — quotes
rejected`) and a closed market reach the same loop.

**Fix (see Q4).** Check `qty` against an enforced `mm_min_qty` at start-up
(exclude the symbol with the reason). Log the first rejection of each reason
per symbol at WARNING and repeats at DEBUG until a quote is accepted, and
back off the retry.

### C4. The bot applies an obligation the engine does not enforce *(repro)* — Med

`bot.py:921-925`, `bot.py:1902-1917`, `pricer.py:393-395`.

The engine's symbols reply carries `enforce_mm_obligation`,
`mm_max_spread_ticks` and `mm_min_qty` for every symbol whenever the gateway
is a configured participant (`engine/main.py:2516-2542`), with the
participant defaults (20 ticks, 100) when the config sets nothing
(`engine/config_loader.py:49-50`). The bot reads `mm_max_spread_ticks` and
never looks at `enforce_mm_obligation`. Reproduced with
`enforce_mm_obligation: false`:

| bot settings | result |
|---|---|
| `--gap 0.30` | symbol excluded: `--gap exceeds mm_max_spread_ticks obligation (0.300000 > 20 * 0.010000)` |
| no `--gap`, participant `mm_max_spread_ticks: 1000` | gap derived as 5.00 (the documented default is 0.10) |

The `passive` band is narrowed by the same unenforced number
(`pricer.py:393-395`). The guide's own wording ("the engine rejects any quote
wider than it") is true only when the obligation is enforced (D10).

**Fix (see Q3).** Read `enforce_mm_obligation`; when it is false, keep the
values out of `_SymbolState` so no check, default or band uses them.

### C5. A late symbols reply makes the bot guess every tick size — Med

`bot.py:886-931` `_request_symbols`; `bot.py:1897`.

`_request_symbols` waits a fixed 3 s (not configurable) and returns `[]` on a
timeout. `_startup_one_symbol` then skips its existence check
(`if symbols_seen and symbol not in symbols_seen`), so every symbol continues
with the dataclass defaults: tick size 0.01, no obligation, and no
`register_tick_decimals`. `_send_quote` converts with `to_ticks`, which falls
back to 2 decimals, and sends `tick_decimals: 2`; the engine reads only the
tick integers (`engine/main.py:4121-4141`, see §9 L032). On a symbol with
`tick_decimals: 4` a 100.00 mid is quoted as 10 000 ticks, i.e. 1.0000. A
symbol the engine does not know is only discovered through C3's rejection
loop. The timeout is logged at INFO ("symbols request timed out").

**Fix.** A missing symbols reply is a start-up failure (exit 1, logged at
WARNING), as a failed authentication is.

### C6. The tracked position starts at zero at every start — Med

`bot.py:228-234`, `bot.py:980-990` `_buffer_event`.

`net_position` is "purely local bookkeeping — the bot never queries the
engine for it". After a restart, `inventory_skew` quotes as if flat whatever
the gateway holds; with `--tif GTC` or an adopted quote (QBOOT) the restart
is exactly the case the bot is built to survive. During the start-up waits
(`_request_bootstrap`, `_request_qlegs`, `_wait_for_session`) `_buffer_event`
keeps only `session.state`, book snapshots and trades; an `order.fill` on an
adopted quote's legs is dropped. The engine answers `system.position_request`
with the gateway's per-symbol net quantity and average cost
(`models/generated/system.py:6127-6139`, `message.py:1902`); the snapshot
"has no consumer in `src/`".

**Fix (see Q2).** Ask for the gateway's position at the end of start-up and
seed each symbol's `net_position`/`avg_cost` from it. Fills published before
the snapshot are in it; later ones arrive after it on the same PUB stream.

### C7. Gateway and logging values are not validated *(repro)* — Low

`main.py:411-437` `_resolve_gateway_settings`; `main.py:526-534`;
`params.py:124-133`.

Only Tier-2 values pass through `validate_symbol_params`. Tier-1 values from
the config file are copied onto `args` as they are. Reproduced through
`main()`:

| input | result |
|---|---|
| `gateway: {startup_session_timeout_sec: "5"}` | `TypeError: '<=' not supported between instances of 'str' and 'int'` traceback at `main.py:530` |
| `logging: {level: verbose}` | accepted; `_configure_logging` silently uses WARNING |
| `logging: {target: syslog}` (by inspection) | passed to `resolve_handler` unchecked |
| `gateway: {label: 7, engine_pull: 5555}` | gateway `MM_7_01`; `engine_pull=5555` (an int) reaches `make_pusher` |
| `--gap nan` | accepted (`nan <= 0` is false); `QuotePricer` accepts it; `math.floor(nan)` raises `ValueError` at the first quote and the bot exits with a traceback |
| `--gap inf`, `--heartbeat-interval-sec inf`, `--fade-sec nan`, `--startup-session-timeout-sec nan` | all accepted; the last makes the session wait end at once |

`params.py` defines `LOG_TARGET_CHOICES` and `LOG_LEVEL_CHOICES` and nothing
uses them. The CLI rejects `--log-level debug` while the file accepts any
case (and any word).

**Fix.** Validate the Tier-1 block like Tier 2 (types, ranges, the two enums),
and reject non-finite numbers in `_as_float`.

### C8. The legacy flat config file has its own defects *(repro)* — Low

`config.py:49-74`, `config.py:157-170`.

| legacy file | result |
|---|---|
| `symbol: AAPL` + `id_suffix: 01` | gateway `MM_AAPL_1` (the v1 loader refuses an unquoted suffix, `config.py:186-190`; the flat loader does not); authentication then fails |
| `strategy: passive` + `fade_ticks: 3` | `unknown key(s): fade_ticks`; `_ALLOWED_KEYS` predates the passive knobs, `anchor_sim` and `gateway_id` |
| `symbol: AAPL` + `symbols: MSFT,TSLA` | quotes MSFT and TSLA; `symbol` is dropped without a word |

The guide says the flat format "still loads unchanged … and behaves exactly
as it did". The project rule is no backwards compatibility (Q5).

**Fix (see Q5).** Remove the flat format, or give it the v1 validation.

### C9. Start-up replies are matched by gateway, not by symbol — Low

`bot.py:933-978`, `bot.py:1955-1970`.

`_request_bootstrap(symbol)` and `_request_qlegs(symbol)` each send one
request and return the first message on `system.quote_bootstrap.<GW>` or
`system.quote_legs.<GW>`. A reply that arrives after its symbol's
`bootstrap_timeout_sec` (default 1 s) is taken as the next symbol's. For QBOOT
that is mostly harmless (`_try_adopt_from_bootstrap` filters by symbol, so the
next symbol misses its own adoption); for QLEGS a foreign symbol's legs make
the adopted quote look divergent and clear it (`bot.py:1963-1970`), so the
bot quotes on top of its own resting quote until the engine's replace cleans
up. With `--all-symbols` (150 symbols in the training setup) start-up is 300
blocking round trips, and every unanswered one costs a full timeout. Both
engine handlers accept an empty `symbol` and answer for the whole gateway
(`engine/main.py:2954-2963`, `3029`).

**Fix.** One QBOOT and one QLEGS for the gateway at start-up, distributed by
each entry's `symbol`.

### C10. SIGTERM is not honoured during start-up — Low

`bot.py:1801-1805`, `bot.py:1814-1866`.

`run()` installs handlers that set `_running = False`. Start-up
(`_authenticate`, `_request_symbols`, the per-symbol waits, the session wait,
and `_resolve_initial_state`, which sends the first quotes) never reads the
flag. A stop during start-up is acted on only when the main loop starts; the
bot then cancels the quotes it has just sent. With C9's per-symbol timeouts
that can be minutes at `--all-symbols` scale.

**Fix.** Check `_running` between start-up steps and in the waits' loops;
exit 0 without quoting.

---

## 4. Performance findings

None of this matters for the one- to three-symbol bots in the training
chapters. It matters for `--all-symbols` (the `mm-demo` profile, the AI-sim
container), where the bot receives every `trade.executed` on the exchange.

### P1. Dispatch cost grows with the number of symbols *(measured)* — Low

`bot.py:1541-1592`.

`_dispatch` finds a symbol by building `topic_book_snapshot(sym)` for each
quoted symbol and comparing; a message that is not a book snapshot then does
the same for `topic_circuit_breaker_halt` and `topic_circuit_breaker_resume`.
A fill, a quote status or a trade therefore builds and compares 3 × N strings.

| symbols | `book.<last>` | `trade.executed` | `order.fill` | `_tick()` (every 50 ms) |
|---|---|---|---|---|
| 1 | 1.5 µs | 1.0 µs | 1.8 µs | 0.7 µs |
| 30 | 3.6 µs | 7.1 µs | 7.9 µs | 9.3 µs |
| 300 | 22.9 µs | 61.6 µs | 62.2 µs | 90.4 µs |

The cost grows with the number of symbols, not with history. At 300 symbols
and 2 000 messages a second that is about 12 % of a core spent matching
topics; `_tick` is 0.2 %. `_buffer_event` (`bot.py:985-988`) has the same
loop.

**Fix.** Precompute a `topic → (kind, symbol)` dict at socket set-up.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `bot.py:397-402`, `bot.py:1290-1299`, `bot.py:411-416` | "quote.ack … carry quote_id but not symbol"; `quote.ack` has carried `symbol` since `f8ff0bda` (`models/generated/quote.py:524`). The FIFO fallback it justifies is not needed. |
| D2 | `main.py:122-126` | `--max-position` help: "unused by every other strategy". `validate_symbol_params` rejects it with any other strategy (`params.py:211-215`); the guide and reference manual already say "rejected otherwise". |
| D3 | `main.py:291-296`, guide CLI table, reference manual | `-q`: "Reduce output to warnings/errors". The default is already WARNING (`main.py:337-340`); `-q` changes nothing. |
| D4 | guide "Understanding bot output" | Says failure paths "log at `ERROR`" and shows `INFO … [AAPL] startup failed: …`. Start-up failures are logged at WARNING as `startup warning: [AAPL] startup failed: …` (`bot.py:702-705`). |
| D5 | guide "Querying a bot's position" | "the two should always agree, since both are derived from the same fill stream". False today (H2) and after every restart (C6). |
| D6 | guide "Per-symbol settings" list and the `defaults:` fields table | The list omits `--anchor-sim` and the five `passive` flags; the table omits `anchor_sim`. Both are per-symbol (`params.py:24-44`). |
| D7 | `pm_help/registry.py:1062-1129`; reference manual `010-processes-environment-and-ports.md:434` | pm-help: "quoting bot for one symbol", "Run multiple instances … to cover several symbols"; options lack `--symbols`, `--all-symbols`, `--config`, `--strategy`, `--label`, `--max-position` and the passive flags. The process table: "for a single symbol". |
| D8 | `pricer.py:16-23` | `PricingStrategy`: "``QuotePricer`` (below) is today's only implementation." There are three. |
| D9 | `bot.py:1043`, `bot.py:1234`, `bot.py:1285` | Debug lines print raw floats (`book mid=150.51999999999998`), For-Later L006's bot part. Prices should use the symbol's `tick_decimals`. |
| D10 | guide "Gap validation", "Interaction with the MM spread obligation" | "the engine rejects any quote wider than it" and the validation rules hold only when `enforce_mm_obligation` is true (C4). |
| D11 | guide "Troubleshooting", row `quote REJECTED` | The line is INFO and invisible without `-v` (C3). |

---

## 6. Verified as correct

- **Pricing arithmetic.** `QuotePricer` rounds bid half-up and ask half-down
  to the tick and enforces the two-tick minimum; the guide's `inventory_skew`
  worked example (mid 150.00, +500 of 1 000 → 149.92 / 150.02) and all eight
  rows of the `passive` worked-examples table come out exactly, run through
  the real `InventorySkewPricer` and `PassivePricer`.
- **Precedence and tiers.** `resolve_symbol_params` applies ranks 1–5 as
  documented; `gap_was_explicit` is true exactly when a rank 1–4 source set
  `gap`; a gateway-wide flag inside a symbol scope is hoisted with a warning;
  `--symbol`/`--symbols`/`--all-symbols`/`symbols:` exclusions give usage
  errors.
- **Quote ids.** Minted per quote (`bot.py:1132`), echoed by the engine on the
  ack, the legs and the status; indexed at send time so a reject before the
  ack resolves. The index is bounded (`max(32, 8 × N)`).
- **Replace semantics with the engine.** A reissue after a partial fill
  leaves exactly the new quote's two legs in the book (the engine's
  orphaned-leg cancel, previous review §4 item 3): verified in the wired runs.
- **Cancel-timeout recovery.** A cancel that is never confirmed is replaced
  after `cancel_timeout_sec`, and a fill does not overwrite that timer
  (`bot.py:1461-1462`).
- **Engine heartbeat.** One heartbeat per `GATEWAY_HEARTBEAT_INTERVAL_SEC`
  (60 s) after authentication; the guide's "once a minute … three missed
  beats" matches.
- **Poll cadence.** The poll timeout is half the shortest per-symbol interval
  with a 50 ms floor and a 500 ms cap when a health reporter is attached;
  `_tick` runs at most every 50 ms.

---

## 7. Decisions

All five taken as recommended on 2026-11-15 (the user asked for WP-MMB01–08
in one go).

| # | Question | Recommendation |
|---|---|---|
| Q1 | How should the bot attribute a fill that arrives after its quote was retired (H2)? (a) A bounded map of every leg order id it has quoted → (symbol, side), consulted before the current quote's ids. (b) Ask the engine to publish `order.fill` before the quote hook's messages. (c) Delay clearing the leg ids until the fill arrives. | **(a)**. It is local to the bot and correct whatever order the engine uses, including fills on a hit leg's remainder during the reissue delay. (b) contradicts the engine's deliberate mid-sweep hook (the sibling must not trade later in the same sweep) and its documented contract. (c) has no event to wait for: a status says nothing about how many fills follow. |
| Q2 | Should the bot seed its position from the engine at start-up (C6)? (a) Yes, via `system.position_request` at the end of start-up, for every symbol. (b) No; document that `inventory_skew` restarts flat. | **(a)**. A restart with inventory is the normal case for a GTC or adopted quote, and the engine's ledger is the truth the guide tells operators to check (`POS|GW=`). With `--gateway-id` shared by people (the `mm-demo` `MM01`), the ledger includes their orders too, which is the position the gateway actually carries. (b) leaves the strategy wrong after every restart. |
| Q3 | When `enforce_mm_obligation` is false, should the bot still use `mm_max_spread_ticks` and `mm_min_qty` (C4)? (a) No: ignore both. (b) Yes, as an advisory default for the gap only, never as a refusal. | **(a)**. The engine does not apply them, so the bot refusing a gap or narrowing a band for them is a restriction nobody configured. (b) keeps a hidden default that changes with an unrelated participant setting (`gap` 5.00 in the repro). |
| Q4 | How should repeated rejections behave (C3)? (a) WARNING for the first rejection of each reason per symbol, DEBUG for repeats, a WARNING again after the next accepted quote; retry delay doubles per consecutive rejection up to `heartbeat_interval_sec`. (b) Only the logging change. (c) Stop quoting the symbol after N rejections. | **(a)**. The operator sees the reason once, the engine is not hit four times a second forever, and a transient refusal (a closed market) still recovers within one heartbeat interval. (c) turns a transient refusal into H1's silent stop. |
| Q5 | The legacy flat config format (C8): (a) remove it (project rule: no backwards compatibility), updating the guide's "Legacy flat files" section; (b) keep it and give it the v1 validation. | **(a)**. Nothing in the repo or the training chapters uses it (all examples and exercises are `version: 1`); fixing it means maintaining two loaders. A flat file then fails with the usual "unknown key" message pointing at `version: 1`. |

---

## 8. Work packages

### WP-MMB01 — Every fill of the bot's own legs is counted (H2, D5; after Q1)

**Tests first** (`tests/test_mm_bot_engine_wired.py`, new, with the wired
fixture described under the delivery rule):

1. `inventory_skew`, 500 × 500 quote; a taker sells 100 into the bid → after
   `pump()`, the bot's `net_position` equals the engine's
   `_gateway_positions["MM01"]["AAPL"]` (+100). (Fails today: 0.)
2. Same, then a second taker sells 300 into the remainder before the reissue
   → both +400. (Fails today.)
3. After test 2's reissue, the new quote is skewed: bid and ask below the
   flat 99.95/100.05 by the formula's amount. (Fails today.)
4. `passive` with `fade_ticks 3`: a full fill of the bid → the reissued bid is
   99.92. (Fails today: 99.95.)
5. A fill whose `order_id` was never quoted by this bot is not counted.
   Unchanged.
6. The retired-leg map holds at most a bounded number of entries after 1 000
   quote cycles.

**Change.** A bounded `OrderedDict` of leg order id → (symbol, side), filled
from every accepted ack and every adopted QBOOT quote, consulted by
`_symbol_for_order_id`/`_handle_order_fill` before the current quote's ids;
`_clear_quote_state` no longer affects fill attribution. Keep the pre-ack
buffer only for fills on an order id that is not yet known. D5's sentence in
the guide stays true once WP-MMB05 seeds the position; reword it then.

**Exit criteria.** Tests 1–6 pass; `tests/test_mm_bot*.py`,
`tests/test_mm_quotes_engine.py` green.

**Outcome (2026-11-15).** `MMBot._leg_to_symbol` (an `OrderedDict` of leg
order id → (symbol, side), capped at `max(64, 16 × symbols)`) is filled by
`_index_legs` from every accepted ack and every adopted QBOOT quote.
`_leg_for_order_id` (replacing `_symbol_for_order_id`) looks there first and
then at the symbol's current quote, which the unit tests still set without an
ack; the fill handler takes the side from it. The own-leg quantities
`passive` subtracts are reduced only for a leg of the current quote. To drive
the real start-up from tests, `_run_loop` was split into `_start_up()` (steps
1–7, returns an exit code or None) and the loop; behaviour unchanged.
`tests/test_mm_bot_engine_wired.py` is new: a fixture wiring the bot's
PUSH/SUB to a real `Engine`, a fake clock patched into `mm_bot.bot` and
`mm_bot.pricer`, and a poller that advances the clock by its timeout. Tests 1–4
failed first for the reason in H2 (bot position 0 vs engine 100/400, an
unskewed and an unfaded reissue); test 4 first failed on the test passing the
passive knobs as constructor kwargs, corrected to per-symbol `overrides`;
test 6 failed on the missing index. D5 is reworded in WP-MMB05, once the
position is also seeded. Full suite: 14 519 passed, 1 skipped.

### WP-MMB02 — A halted or paused symbol always comes back, and never quotes while paused (H1, C2)

**Tests first** (`tests/test_mm_bot_engine_wired.py`):

1. Halt and resume AAPL through the engine while the session is
   `CONTINUOUS` → within one tick after the resume the bot has sent a quote
   and two legs rest in the book. (Fails today.)
2. Halt, then `session.state CLOSING_AUCTION`, then resume → no quote; then
   `CONTINUOUS` → quote. (Unchanged in outcome; guards the fix.)
3. A drift reissue in flight when `session.state CLOSING_AUCTION` arrives →
   after the ack the bot has sent `quote.cancel`, is `PAUSED`, and the book
   holds none of its legs. (Fails today.)
4. A symbol in `WAITING_FOR_SESSION` when the session enters `CONTINUOUS`
   quotes. (Fails today.)

**Change.** `_handle_circuit_breaker_resume` schedules `reissue_at = now`
when the session is quoting; `_handle_session_state` treats
`WAITING_FOR_SESSION` like `PAUSED` on a transition into a quoting session
and cancels in `REISSUING` on the way out; `_handle_quote_ack` cancels an
accepted quote that arrives while `PAUSED`. Re-walk training chapter 21's
Exercise 2 (halt, cancel, verify, resume): with a bot running, the book is no
longer empty after the resume, so its expected output may need a note.

**Exit criteria.** Tests 1–4 pass; suites as above green.

**Outcome (2026-11-15).** `_handle_circuit_breaker_resume` schedules an
immediate reissue when the session is quoting and the symbol has a mid; a
transition into `CONTINUOUS` revives `WAITING_FOR_SESSION` as well as
`PAUSED`; a non-quoting phase also cancels a symbol in `REISSUING`; an
accepted ack that arrives while `PAUSED` indexes the legs (WP-MMB01) and
cancels the quote instead of setting `QUOTING`. Tests 1, 3 and 4 failed first
for the reasons in H1 and C2 (no quote 0 s/30 s after the resume; `QUOTING`
with legs resting in the auction); test 2 passed before and after. The
fixture's `pump()` now ticks once even with nothing queued, as the real loop
does after every poll. Training chapter 21 re-walked: no bot runs during
Exercise 2 (the bot starts in Exercise 4), so its expected output stands.
Full suite: 14 523 passed, 1 skipped.

### WP-MMB03 — Every reply is applied to the symbol it belongs to (C1, C9, D1)

**Tests first** (`tests/test_mm_bot_engine_wired.py`,
`tests/test_mm_bot_multi.py`):

1. Two symbols quoting; MSFT's QLEGS-divergence path reissues → AAPL keeps its
   quote id and receives no new `quote.new`. (Fails today.)
2. A `quote.status` with an id the bot never sent changes no symbol. (Fails
   today: the primary is cleared.)
3. A `quote.ack` is attributed by its `symbol` when its id is unknown.
4. Start-up with three symbols sends exactly one `system.quote_bootstrap_request`
   and one `system.quote_legs_request`, both with an empty symbol, and adopts
   each symbol's active quote from the one reply. (Fails today: three each.)
5. A QBOOT reply arriving after the timeout does not clear another symbol's
   adopted quote. (Fails today.)

**Change.** Remove the primary-symbol fallback from `_handle_quote_status`
and the FIFO fallback from `_handle_quote_ack` (use `symbol`); keep a quote's
id in `_quote_id_to_symbol` until a terminal status for it arrives (bounded as
now). Replace the per-symbol QBOOT/QLEGS waits with one gateway-wide request
each. Fix D1's comments with the code.

**Exit criteria.** Tests 1–5 pass; suites as above green.

**Outcome (2026-11-15).** `quote.ack` is matched by its id, else by its
`symbol` (every engine ack path sends both, `engine/main.py`, 13 of 13
`_quote_ack` calls); the send-order FIFO `_pending_ack_symbols` is gone. A
`quote.status` is resolved through `_symbol_for_quote_id` and acts only on
the symbol's current quote: the acked `quote_id` or the new
`_SymbolState.sent_quote_id` (the quote in flight, for a lost ack); anything
else is ignored and counted. Start-up sends one QBOOT and one QLEGS with an
empty symbol (`_adopt_existing_quotes`), waits for the longest
`bootstrap_timeout_sec`, and checks each adoption against that symbol's legs
only. Beyond the plan: the periodic QLEGS check had the same primary-symbol
fallback (`_reconcile_qlegs`: "falling back to the primary symbol for a reply
with no legs"), and the reply names no symbol, so an empty reply for MSFT
cleared AAPL. The periodic request is now gateway-wide too (one per tick when
any symbol is due), and the reply reconciles every quoting symbol; both
requests ask for `ACTIVE`, since the `recent` history was never used. Tests
1–4 failed first for the reasons in C1/C9 (AAPL re-quoted; the primary
cleared; the ack routed by FIFO to AAPL; three requests of each). Test 5 is
superseded: with one request there is no "next symbol" to take a late reply.
A sixth wired test (MSFT's `CANCELLED` lost; the periodic check restores MSFT
and leaves AAPL) was added after the fix and was not run against the old
code. Thirteen tests in `test_mm_bot.py` sent acks, statuses or QLEGS legs
without the `quote_id`/`symbol` the engine always sends; they now carry them,
and one test in `test_mm_bot_multi.py` no longer clears the removed FIFO. The FIFO
test became `test_quote_acks_with_unknown_ids_are_routed_by_symbol`, and
`test_a_qlegs_snapshot_for_an_untracked_symbol_is_ignored` now includes
AAPL's own leg (in a gateway-wide reply, a missing symbol means a missing
quote). D1's comments replaced with the code. Full suite: 14 528 passed, 1
skipped.

### WP-MMB04 — Obligations are applied only when enforced; a refused quote is visible and backs off (C3, C4, D10, D11; after Q3, Q4)

**Tests first** (`tests/test_mm_bot.py`, `tests/test_mm_bot_engine_wired.py`):

1. Symbols reply with `enforce_mm_obligation: false, mm_max_spread_ticks: 20`
   and `--gap 0.30` → the symbol starts. (Fails today: excluded.)
2. Same reply, no `--gap` → gap 0.10; the `passive` band is not narrowed.
   (Fails today with `mm_max_spread_ticks: 1000`: gap 5.00.)
3. `enforce_mm_obligation: true`, `mm_min_qty: 1000`, `--qty 500` → the symbol
   is excluded at start-up with a WARNING naming the minimum. (Fails today.)
4. An engine that rejects every quote for 10 s of bot time → one WARNING
   record with the reason, the others at DEBUG, and at most
   ⌈log2(heartbeat/delay)⌉ + 10 s/heartbeat attempts. (Fails today: 41
   attempts, 41 INFO records.)
5. After an accepted quote, a new rejection logs a WARNING again.
6. Enforced obligation, `--gap 0.30` → excluded as today. Unchanged.

**Change.** Store the obligation values only when `enforce_mm_obligation` is
true; check `qty` against `mm_min_qty`; a per-symbol consecutive-reject
counter that latches the WARNING and doubles the retry delay up to
`heartbeat_interval_sec`, reset on an accepted ack. Update the guide's gap
validation, passive obligation and troubleshooting passages (D10, D11).

**Exit criteria.** Tests 1–6 pass; suites as above green.

**Outcome (2026-11-15).** `_request_symbols` stores `mm_max_spread_ticks`
and the new `_SymbolState.mm_min_qty` only when the reply's
`enforce_mm_obligation` is `true`; start-up excludes a symbol whose `qty` is
below an enforced `mm_min_qty`. A rejected ack logs
`[GW] [SYM] quote REJECTED: <reason>` at WARNING the first time per reason
(per symbol, until the next accepted quote) and at DEBUG after that; the retry
delay is `max(reissue_delay, 50 ms) × 2^(n−1)`, capped at
`heartbeat_interval_sec`, and both reset on an accepted ack. The 50 ms floor
keeps `--reissue-delay-ms 0` from retrying on every tick. Test 4 drives the
refusals by tightening the engine's participant config after start-up (a
quote the bot cannot fix by itself). Tests 1–5 failed first for the reasons in
C3/C4 (start-up refused `--gap 0.30`; gap 5.00; no start-up check of
`mm_min_qty`; 20 INFO records); test 6 passed before and after. Four older
tests sent an obligation without `enforce_mm_obligation: true`; they now
carry the flag the engine sends when it enforces. A ledger entry was added for
the new WARNING (`log_ledger/entries/mm_bot.yaml`; `test_log_ledger` caught
it). Docs: the guide's gap validation, passive obligation, refresh-trigger and
troubleshooting passages (D10, D11, plus "Per-symbol failure isolation"); the
reference manual's passive row. **Follow-up found by the B1 re-walk:** training
chapter 02 told students that a gap over 20 ticks is refused, and its Exercise
8 tip demonstrated failure isolation with TSLA at `gap: 0.50`; its
configuration does not enforce the obligation, so neither holds any more. The
note now says the limit binds only with `enforce_mm_obligation: true`, and the
tip uses a symbol the exchange does not list (`NVDA: {}`), with the bot's
actual WARNING lines. Full suite: 14 534 passed, 1 skipped.

### WP-MMB05 — Start-up uses the engine's facts: symbol metadata and the current position (C5, C6; after Q2)

**Tests first** (`tests/test_mm_bot.py`, `tests/test_mm_bot_engine_wired.py`):

1. No symbols reply within the timeout → `run()` returns 1 and a WARNING says
   so; no `quote.new` was sent. (Fails today: it quotes.)
2. The engine holds +300 AAPL for the gateway before the bot starts →
   after start-up `net_position == 300` and `avg_cost` equals the engine's,
   and an `inventory_skew` first quote is skewed. (Fails today: 0.)
3. A fill on an adopted quote's leg during start-up is reflected in the
   position after start-up. (Fails today.)
4. A position snapshot that does not arrive in time leaves the position at 0
   with a WARNING; start-up continues.

**Change.** `_request_symbols` failure ends start-up. At the end of start-up,
send `make_position_request_msg(gateway_id)` and seed every symbol from
`system.position_snapshot.<GW>` (overwrite). Update the `_SymbolState`
comment ("never queries the engine") and the guide's inventory-skew sentence
("it does not ask the engine") and D5.

**Exit criteria.** Tests 1–4 pass; suites as above green.

**Outcome (2026-11-15).** An empty or missing symbols reply ends start-up
(`startup failed: no symbol list from the engine`, exit 1), and every symbol
must then appear in the list. After the QBOOT/QLEGS step, `_seed_positions`
sends `system.position_request` for the gateway, waits as long as the other
start-up replies, and overwrites each symbol's `net_position`/`avg_cost` from
`system.position_snapshot.<GW>` (now subscribed), passing the position to an
`inventory_skew` pricer; without a reply it warns and stays at 0. The start-up
waits now hand `order.fill` to the fill handler (`_buffer_event`), so a fill
on an adopted quote after the snapshot is counted; one before it is replaced
by the snapshot. Tests 1–4 failed first for the reasons in C5/C6 (start-up
quoted without a symbol list; positions 0 against the engine's 300 and 200;
no warning). The fixture gained `lost_requests` and `before_send` hooks.
Texts: the `_SymbolState` comment, the guide's inventory-skew sentence and
D5's paragraph, and the `system.position_snapshot` spec note ("This pair has
no consumer in `src/`"), regenerated with `pm-msgen generate` (message
reference and `models/generated/system.py`). Full suite: 14 538 passed, 1
skipped.

### WP-MMB06 — Configuration is validated before anything starts; SIGTERM is honoured during start-up (C7, C8, C10; after Q5)

**Tests first** (`tests/test_mm_bot_config.py`, `tests/test_mm_bot.py`):

1. `gateway: {startup_session_timeout_sec: "5"}` → exit 1 with a message
   naming the key; no traceback. (Fails today: `TypeError`.)
2. `logging: {level: verbose}` and `logging: {target: syslog}` → exit 1 naming
   the allowed values. (Fails today.)
3. `gateway: {label: 7}` and `gateway: {engine_pull: 5555}` → exit 1. (Fails
   today.)
4. `--gap nan`, `--gap inf`, `--fade-sec nan`, `--startup-session-timeout-sec
   nan` → exit 1. (Fails today.)
5. Q5 (a): a flat file (`symbol: AAPL`) → exit 1 with a message pointing at
   `version: 1`. (Fails today: loads.) Q5 (b) instead: the three C8 cases are
   refused or applied correctly.
6. `_running` cleared during the QBOOT wait → `run()` returns 0 and no
   `quote.new` was sent. (Fails today.)

**Change.** A `validate_gateway_params` beside `validate_symbol_params`
(types, ranges, `LOG_LEVEL_CHOICES`, `LOG_TARGET_CHOICES`, case-normalised
level); `_as_float` rejects non-finite values. Per Q5, delete
`load_config_file`, `_ALLOWED_KEYS`, `_from_legacy_flat` and
`_normalize_symbols_value`, and the guide's "Legacy flat files" section (or
validate them). Start-up checks `_running` between steps and in each wait.

**Exit criteria.** Tests 1–6 pass; `make completion` if help texts change;
suites as above green.

**Outcome (2026-11-15).** `params.validate_gateway_params` checks the
resolved Tier-1 values (strings for `label`, `gateway_id`, `id_suffix`,
`engine_pull`, `engine_pub`; positive finite timeouts; `LOG_LEVEL_CHOICES`,
case-insensitive in the file and upper-cased; `LOG_TARGET_CHOICES`; a
non-negative failover timeout). `main._resolve_gateway_settings` calls it, and
a failure is the existing `invalid configuration: %s` (exit 1); the separate
`invalid startup value: …` check and its ledger entry are gone. `_as_float`
refuses NaN and infinities, so every Tier-2 number is finite. Per Q5 the flat
loader is removed (`load_config_file`, `_ALLOWED_KEYS`, `_from_legacy_flat`,
`_looks_like_v1`, `_normalize_symbols_value`): every file goes through the
`version: 1` loader, and a flat key at the top level gets a pointer
(`'gap' is a per-symbol setting; move it under 'defaults:' …`, `'symbol' is
not a key; list the symbols under 'symbols:'`). C10: a `_stop_requested` flag,
set by the signal handler and `shutdown()`, ends every start-up wait, and
`_start_up` returns 0 before any quote is sent; a separate flag because many
unit tests call the start-up steps with `_running` still false. Tests failed
first for the reasons in C7/C8/C10 (a `TypeError` traceback, accepted values,
flat files loaded, start-up continuing after the stop); the zero-timeout case
failed on wording only. `tests/test_mm_bot_config.py` was rewritten around
`load_bot_config`; five `main()` tests now use `version: 1` files, the
comma-string test became a refusal test, and three tests about the flat
format were deleted. Guide: "Legacy flat files" replaced by "The old flat
layout"; the errors table and a troubleshooting row updated (messages checked
against the real `main()`). `make completion` produced no change. Full suite:
14 545 passed, 1 skipped.

### WP-MMB07 — Message dispatch costs the same for 1 or 300 symbols (P1)

**Tests first** (`tests/test_mm_bot_multi.py`):

1. A 300-symbol bot dispatches a book snapshot, a halt and a resume to the
   right symbol. Unchanged.
2. `_dispatch` of `trade.executed` on a 300-symbol bot calls
   `topic_book_snapshot` zero times (patched counter). (Fails today: 300.)

**Change.** Build `topic → (kind, symbol)` once in `_setup_sockets` (and for
the tests' direct construction) and use it in `_dispatch` and
`_buffer_event`.

**Exit criteria.** Tests pass; `order.fill`/`trade.executed` dispatch at 300
symbols within 2× the 1-symbol time on this host (measured before/after as in
§4; the target is a guess from the dict lookup's cost).

**Outcome (2026-11-15).** `MMBot.__init__` builds `_symbol_topics`
(topic → ("book" | "halt" | "resume", symbol)) once; `_dispatch` and
`_buffer_event` look a topic up there, and `_symbol_for_book_topic`/
`_symbol_for_topic` are gone. Order fills were already O(1) since WP-MMB01's
leg index. Test 2 failed first (300 topics built per trade); test 1 passed
before and after. Measured with the §4 benchmark, same host:

| symbols | `book.<last>` | `trade.executed` | `order.fill` | `_tick()` |
|---|---|---|---|---|
| 1 | 1.3 µs | 0.6 µs | 1.5 µs | 0.6 µs |
| 30 | 1.4 µs | 0.6 µs | 1.5 µs | 9.5 µs |
| 300 | 1.4 µs (was 22.9) | 0.6 µs (was 61.6) | 1.5 µs (was 62.2) | 94.4 µs |

The exit criterion (within 2× of one symbol) is met. `_tick` still grows with
the number of symbols (it visits each), at 0.2 % of a core every 50 ms; it was
not in scope. Full suite: 14 547 passed, 1 skipped.

### WP-MMB08 — Comments, help texts, pm-help, guide and reference manual (D2–D4, D6–D9)

**Tests first.** `tests/test_shell_completion.py` and the pm-help registry
tests stay green; a test that `pm-help pm-mm-bot` lists `--symbols`,
`--all-symbols`, `--config` and `--strategy`. (Fails today.)

**Change.** D2 and D3 in `main.py` help (D3: make `-q` mean ERROR, or drop
the "reduce output" wording; WARNING is already the default), the guide and
the reference manual; D4's sample output; D6's list and table; D7 in
`pm_help/registry.py` and the reference process table; D8 in `pricer.py`; D9
by formatting prices with `tick_decimals` in the bot's log lines (and note
L006's bot part as done). Re-read the guide's state diagram, "Session state
handling", "Per-symbol failure isolation" and the troubleshooting table
against the code after WP-MMB01–07, and training chapters 020 and 210.
Regenerate completion (`make completion`) if help texts change.

**Exit criteria.** Every D item resolved or noted as superseded; `make
_check` and the full suite green.

**Outcome (2026-11-15).** D2: `--max-position` help says "an error with any
other strategy". D3: pm-mm-bot's `-q` help, guide and reference rows now say
"Explicit WARNING (the default)", the reference manual's existing wording for
another tool; behaviour unchanged, because every `pm-*` process treats `-q` the
same way and changing one would make the bot the odd one out — the shared
help text went to For-Later **L034**. D4: the guide's output section says
which messages are WARNING, and both sample logs were rewritten from the code
(symbol tags, the `startup warning:` prefix, real order: exclusion before the
other symbols' references; the obligation sample states it is enforced). D6:
the per-symbol list names `--anchor-sim` and the passive knobs; the
`defaults:` table has `anchor_sim`. D7: the pm-help entry covers several
symbols, `--symbols`, `--all-symbols`, `--config`, `--strategy`, `--label`,
`--max-position` and the passive knobs; the reference manual's process table
and see-also say "one or more symbols". D8: `PricingStrategy` names its three
implementations and their optional hooks. D9: the bot's price log lines use
`_price_text` (tick precision; a mid one digit more); L006's detail notes the
bot part as done. Also from the re-read: the guide's state diagram, start-up
sequence (one QBOOT/QLEGS, the position step, the 3 s symbols failure),
session/halt passage and shutdown (a stop during start-up); and
`--bootstrap-timeout-sec` help/rows (it now bounds the gateway-wide start-up
replies). Training chapters 020 and 210 re-walked: 020 fixed under
WP-MMB04's follow-up, 210's sample lines match. The new pm-help test failed
first (`--symbols` missing); `make completion` regenerated the zsh script.
Full suite: 14 548 passed, 1 skipped.

---

## 9. Out of scope, noted

- **The engine does not check a quote's `tick_decimals` (L032).**
  `_handle_quote_new` reads `bid_price_ticks`/`ask_price_ticks` and ignores the
  payload's `tick_decimals` (`engine/main.py:4121-4141`). A client whose tick
  registry is wrong (C5 is one way) rests a quote at 1/100 or 100× of the
  intended price without a reject. Order paths may share this; the engine
  owns the check. Added as For-Later **L032**.
- **For-Later L014** (start from the market model's value with
  `--anchor-sim`) is a feature, not a defect; it stays open.
- **For-Later L006** covers the consoles and `pm-admin` too; only the bot's
  log lines are in D9 (done).
- **For-Later L034** (added in WP-MMB08): `-q` selects WARNING, the default,
  in every `pm-*` process while the help says "Reduce output"; pm-mm-bot's
  text was reworded, the others need one decision for all.
- **`--initial_min`/`--initial_max`** are the only underscore flags of the
  command. Renaming them changes the interface; left as is.
- **The health beacon** reports `mmbot.symbols_active` (symbols that passed
  start-up), not symbols with a live quote. After H1 and C3 are fixed the
  difference is transient; a "quoting" gauge would be a new feature.
- **`docs-design/EduMatcher-MM-Bot-review.md` §4 item 3** says "`pm-mm-bot`
  itself required no changes" for the partial-fill fix; since `5b2aea31` the
  ordering it relied on has changed (H2). A historical design record, not
  corrected here.
