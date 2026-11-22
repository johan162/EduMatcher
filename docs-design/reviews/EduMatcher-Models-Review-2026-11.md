# Shared Models Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/models/` at `641688d6` (v0.83.4), without
`generated/`: `message.py` (2 283 lines, the bus framing and the `make_*_msg`
builders over the generated module), `order.py` (363, `Order` and the order
enums), `combo.py` (238), `quote.py` (244, `QuoteIndex` and its history),
`envelope.py` (209, ULIDs and the causal envelope), `trade.py` (204),
`price.py` (201, tick conversion), `feed_schema.py` (105), `order_fields.py`
(102, the per-type field rule), `ids.py` (54), `session.py` (51),
`mm_obligation.py` (47), `clock.py` (39), `participant.py` (33),
`instrument.py` (25), `reject.py` (19). Every process imports this package.
Engine code was read where it decides how a model behaves: the inbound
decoders (`Engine._handle_new_order`, `_validate_new_order`,
`_handle_combo_order`, `_handle_amend`, the quote and OCO `_*_ticks` readers,
the dispatcher `_dispatch`), `order_to_display_dict`/`ack_detail`, the tick
registration in `_restore_gtc`/`_load_config`, `_tick_scale_mismatch`, and
`engine/persistence.py`'s `_checked_order`. On the client side the readers
were `api_gateway/translate.py`, `alf_gwy/gateway.py` and
`clearing/main.py::_trade_from_payload`. None of those was reviewed as code
of its own.

**Focus:** correctness, edge-case handling, performance on the hot path, and
whether the docstrings, comments and the architecture book, operator guide
and participant guide passages that quote these modules say what the code
does.

**Previous work:** the integer-tick migration (design §15.2: engine-inbound
messages carry ticks; `to_ticks` lost its int passthrough), L012
(`check_type_fields` refuses a type the record cannot carry), L022
(`last_trade_id`), L032 (`_tick_scale_mismatch`), WP-API16 (`order_fields.py`
as the one rule for every transport), X11 (insertion-ordered `QuoteIndex`
keys), S22 (tick prices canonical on the ack), the messaging review's PUB
trailer (`seq|eseq|envelope` in one frame, WP-MSG01–04) and the engine
review's WP-ENG02 (a malformed payload gets the structure's own refusal).
Their fixes are in place and are not repeated here.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with scratch scripts against the tree at
`641688d6`: engine findings through the real `Engine` built by
`tests/engine_harness.make_engine`, REST findings through the real FastAPI
app (`tests/api_gateway_harness.make_app`/`call`), the config finding through
`load_engine_config` and `pm-cverifier`. *(measured)* means timed on this
host (36 cores, pinned to 8 with `taskset -c 28-35`, niced). One finding
(the float-ticks census in §3 H1) comes from a scratch pytest plugin that
wrapped `price.from_ticks` and logged every float argument during the full
suite (15 366 tests). The other findings are by inspection, with line numbers
given.

Status: **Open.** Decisions Q1–Q4 are needed before WP-MOD01 to WP-MOD04.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (the ack or reject on the bus, what rests in the book,
   the `trade.executed` payload, the HTTP status, whether a config loads).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_models_*.py`,
   `tests/test_engine_*.py`, `tests/test_api_gateway_*.py`,
   `tests/test_alf_gwy_*.py` and `tests/test_config_*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Engine tests use `tests/engine_harness.py` (`make_engine`, `connect`,
`order_payload`, `msgs`) and send the payload a raw client would send, edited
after `order_payload` builds it. REST tests use `tests/api_gateway_harness.py`
(`make_app`, `call`) with the `_Engine` double of
`tests/test_api_gateway_writes.py`. Pure conversion tests call
`models.price` directly after `clear_tick_registry()`/`register_tick_decimals`.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-MOD01 | The engine refuses an order or combo whose ticks or quantities are not integers, and `from_ticks` takes ticks only | H1, D8 | Q1, Q2 | 1 d | ☐ | |
| 2 | WP-MOD02 | Every price on a 0–8 decimal grid is accepted, and a non-finite or overflowing price is a tick violation | C1, C2 | Q4 | 0.5 d | ☐ | |
| 3 | WP-MOD03 | Prices format exactly, and no model API carries a wrong scale or vouches for code production does not run | C3, C4 | Q3 | 0.5 d | ☐ | |
| 4 | WP-MOD04 | Docstrings, comments and the guides say what the models do | D1–D7, D9–D12 | all | 0.5 d | ☐ | |

Suggested order: **WP-MOD01 → 02 → 03 → 04**. WP-MOD01 first because it is
the one finding that can put a wrong price on `trade.executed`. WP-MOD02
next: it turns away valid orders and valid configs at 6–8 decimals.
WP-MOD03 is hygiene, and waits on Q3 because it may delete public helpers.
The text-only WP-MOD04 is last so the texts describe the final code.

Estimated sequential effort: about 2.5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The models are small and mostly sound. The tick scale an order carries can
never disagree with the registry for a running engine: scales are registered
once at start-up, and a restored or submitted order at another scale is
refused (§6). The clock never goes backwards and the ULID stays monotonic
across a clock step. The PUB trailer is told apart from a PUSH envelope
without ambiguity. `Order.from_dict` keeps an omitted `SMP=` distinct from an
explicit `NONE`. `QuoteIndex` iterates in insertion order and bounds its
history. `check_type_fields` is the same verdict on every transport. None of
that needs another look.

The defects are in four places:

- **The engine's order decoder takes whatever types arrive (H1).**
  `Order.from_dict` and `ComboLeg.from_dict` copy fields without checking
  them, and `from_ticks` returns a float unchanged on the theory that a float
  is "already display". A raw `order.new` with `price_ticks: 9900.5` rests
  off-grid, and when it trades, `trade.executed` prints **price 9900.5**
  (the real price is 99.005) beside `price_ticks` 9900. The quote and OCO
  handlers refuse non-integer ticks; `order.new` and `order.combo` were
  missed.
- **The exact tick check refuses valid prices at 6–8 decimals (C1).** The
  tolerance is an absolute 10⁻⁶ ticks, below the float rounding of the
  scaled value once that passes about 4·10⁹. At 8 decimals, 11–16 % of
  correctly typed prices from 100 upward are refused. An 8-decimal config
  with `last_buy_price: 1234.56789012` does not load.
- **A non-finite or huge price is not a tick violation (C2).** It raises
  `OverflowError`/`ValueError`. REST answers `"price": 1e308` with an
  unhandled exception (a 500), and the engine answers such an amend as its
  own internal error.
- **Small traps (C3, C4).** `format_price_ticks` goes through a float and is
  inexact beyond 2⁵³ ticks. `Trade.tick_decimals` is always 2 on the engine's
  trades, and `Trade.to_dict`, which no production code calls, writes it.

Severity key: **High**: money or a price published wrong without a warning.
**Med**: a valid request or config refused; a figure that misleads.
**Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Inbound decode | A raw `order.new` with `price_ticks: 9900.5` rests off-grid and prints `trade.executed` price 9900.5 (true 99.005), `price_ticks` 9900; qty `5.5`/`True` accepted, qty `"10"` raises *(repro)* | MOD01 |
| C1 | Med | Tick check | `to_ticks_exact_at` refuses valid prices: 8 dp, 11–16 % from 100 up; 6 dp, 2–4 % from 10 000 up; an 8-dp config does not load *(repro)* | MOD02 |
| C2 | Low | Tick check | `inf`/`nan`/`1e308` raise `OverflowError`/`ValueError`, not `TickViolation`: REST 500, engine amend answered as an internal error *(repro)* | MOD02 |
| C3 | Low | Formatting | `format_price_ticks` is inexact beyond 2⁵³ ticks (8 dp: from 90 071 992.55) *(repro)* | MOD03 |
| C4 | Low | Trade model | `Trade.tick_decimals` is always 2 on engine trades; `Trade.to_dict` writes it and drops `match_type`/`auction_id`/`trigger_order_id`; `make_fill_msg` is test-only | MOD03 |
| D1–D12 | — | Comments | See §5 | MOD01, MOD04 |

---

## 3. Correctness findings

### H1. The engine's order decoder accepts float ticks and non-integer quantities, and a float tick prints a wrong trade price *(repro)* — High

`order.py:312-363` `Order.from_dict`, `combo.py:322-334` `ComboLeg.from_dict`,
`price.py:169-181` `from_ticks`.

`Order.from_dict` writes each payload value straight into its slot
(`o.price_ticks = d.get("price_ticks")`, `o.quantity = d["quantity"]`). It is
the engine's decoder for `order.new` (`engine/main.py:2102`), and nothing
between it and the book checks a type: `_validate_new_order`
(`main.py:1989-2061`) compares values (`<= 0`) but never asks whether they are
integers. `ComboLeg.from_dict` is the same for `order.combo`
(`main.py:6057`).

`from_ticks` then hides the mistake. A float argument is returned unchanged,
"assumed to already be in display units" for "staged migration behavior"
(`price.py:172-176`). The migration is finished (`to_ticks` lost its own
passthrough for the same reason, `price.py:66-73`), so the only floats left
are wrong ones, and `from_ticks` turns a float tick count into a display
price 10^tick_decimals too large.

Repro (real engine, AAPL at 2 decimals; a GW02 bid whose `price_ticks` was
edited to `9900.5`, then a GW01 sell at 99.00):

| Event | Field | Value | Should be |
|---|---|---|---|
| `order.ack.GW02` | `accepted` | `True` | refused |
| `order.ack.GW02` | `price` / `price_ticks` | `9900.5` / `9900.5` | — |
| book | resting bid `price_ticks` | `9900.5` (off the grid) | — |
| `trade.executed` | `price` | **`9900.5`** | 99.005 at best |
| `trade.executed` | `price_ticks` | `9900` | disagrees with `price` |
| `order.fill.GW01` | `fill_price` | `99.005` | disagrees with the print |

pm-clearing books a trade from `trade.executed.price`
(`clearing/main.py:175-189`), so the print above is settled at 9 900.50 a
share: a 100-fold price on a 2-decimal symbol, with no warning anywhere. The
same payload with other values (same harness):

| Field edited | Value | Outcome |
|---|---|---|
| `quantity`/`remaining_qty` | `10.5` | accepted, rests 10.5 |
| `quantity`/`remaining_qty` | `True` | accepted as quantity 1 |
| `quantity`/`remaining_qty` | `"10"` | `TypeError` in `_validate_new_order`; the dispatcher (`main.py:7900-7916`) answers it as the engine's own internal error |
| combo leg `price_ticks` / leg `quantity` | `9900.5` / `5.5` | `combo.ack` accepted; AAPL rests at 9900.5; MSFT rests 5.5 while its `order.ack` says `qty: 5` |

**Who can send this.** None of the in-house producers. They build `order.new`
through the generated `make_order_new`, whose `from_dict` coerces with
`int()` (`generated/order.py:97`), or through ALF's own checked path. The
engine's PULL socket, though, takes any client that bypasses a gateway, and
the engine is documented as "the backstop for all of them (and for any client
that bypasses one)" (`main.py:2014`, WP-API16). The rule already exists
twice: `_handle_quote_new`'s `_quote_ticks` (`main.py:4327-4340`) and
`_handle_oco_order`'s `_leg_ticks` (`main.py:6859`) refuse a non-integer
tick, citing design §15.2. The persistence restore has its own type guard
(`persistence.py:133-152`, `_checked_order`). `order.new` and `order.combo`
are the two inbound paths without one.

**The test suite relies on the passthrough.** A scratch plugin that logged
every float reaching `from_ticks` during the full suite found 13 call sites
hit, all from engine tests that send float "ticks" in hand-built payloads
(`price_ticks: 100.0` meant as display 100.00) in `test_new_order_types.py`,
`test_engine_handlers.py`, `test_engine_handlers2.py`, `test_auction.py`,
`test_engine_final_gaps.py` and `test_engine_coverage_final.py`. No
production path passed a float. Those tests encode the defect.

**Fix.** Refuse non-integer ticks and quantities where the payload is decoded
(Q1), so the engine's existing `except (KeyError, ValueError)` turns them
into a malformed-order reject. Make `from_ticks` take ticks only (Q2), and
correct the six test files.

---

### C1. The exact tick check refuses valid prices at 6–8 decimals *(repro)* — Med

`price.py:106-137` `_TICK_EPSILON`, `to_ticks_exact_at`.

```python
scaled = price * 10**tick_decimals
ticks = round(scaled)
if abs(scaled - ticks) > _TICK_EPSILON:   # 1e-6, absolute, in ticks
    raise TickViolation(...)
```

The comment says the window between 10⁻⁶ and half a tick "is where float
arithmetic lands". It is, but only while `scaled` is small. The rounding
error of `price * 10**d` is about one ulp of `scaled`, and one ulp passes
10⁻⁶ once `scaled` passes about 4.5·10⁹. At 8 decimals that is a price of
about 45. Repro: 20 000 correctly typed prices per decade (the price formatted
to exactly `d` decimals and parsed, as a client sends it):

| tick_decimals | [1,10) | [10,100) | [100,1k) | [1k,10k) | [10k,100k) | [100k,1M) | [1M,10M) |
|---|---|---|---|---|---|---|---|
| 4 | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % | 12.3 % |
| 6 | 0 % | 0 % | 0 % | 0 % | 3.0 % | 2.4 % | 4.2 % |
| 8 | 0 % | 0 % | 11.3 % | 15.6 % | 14.5 % | 11.5 % | 14.8 % |

Example: `1234.56789012` at 8 decimals is refused as "not a multiple of
BTCX's tick size 0.00000001".

The same function guards every entry: REST, the ALF console, the config
loader, pm-cverifier and pm-config-gen (`to_ticks_exact` and
`to_ticks_exact_at` callers). An engine config with `BTCX: {tick_decimals:
8, last_buy_price: 1234.56789012}` is refused by `load_engine_config`
("last_buy_price: 1234.56789012 is not a multiple of BTCX's tick size
0.00000001") and by `pm-cverifier` (`S078`). `tick_decimals` 0–8 is the
documented range (operator guide `005-the-configuration-file.md:267`,
reference manual known limitations line 37).

**Fix.** Scale the tolerance with the value: accept when `|scaled - ticks| ≤
max(10⁻⁶, 2·ulp(scaled))`. Measured on 189 000 cases (0–8 decimals, prices
from 1 up to 10⁷): no valid typed price refused, and no half-tick price
accepted. A 4·ulp window wrongly accepted 1 437 half-tick prices at 8 decimals
from 10⁶ up. See Q4.

---

### C2. A non-finite or overflowing price is not a tick violation *(repro)* — Low

`price.py:133-137`, `price.py:79`.

`round(inf)` raises `OverflowError` and `round(nan)` raises `ValueError`.
Neither is a `TickViolation`, and `1e308 * 100` is `inf`. Repro:

| Path | Input | Result |
|---|---|---|
| REST `POST /api/v1/orders` (real app) | `"price": 1e308` (valid JSON) | `OverflowError` escapes the app: a 500 |
| REST | `"price": 100.005` | 400 `TICK_VIOLATION`, as designed |
| engine `order.amend` (raw) | `"price": 1e308` | `OverflowError` from `to_ticks_exact` (`main.py:7437`); the dispatcher answers it as an internal error |

The REST schema (`api_gateway/schemas.py:104`, plain `float`) also accepts
`Infinity` and `NaN` and passes them to `translate.py`. The ALF gateway
already compensates with its own `except OverflowError`
(`alf_gwy/gateway.py:2391`) and the console with an `isfinite` check
(`alf_console/main.py:321`). Each edge rediscovers the same gap.

**Fix.** `to_ticks_exact_at` raises `TickViolation` when `scaled` is not
finite. Every edge that already maps `TickViolation` then answers correctly.

---

### C3. `format_price_ticks` is inexact beyond 2⁵³ ticks *(repro)* — Low

`price.py:198-201`. It formats `from_ticks(ticks) = ticks / 10**d` as a float.

| ticks (8 dp) | `format_price_ticks` | exact |
|---|---|---|
| 123 456 789 012 345 678 | `1234567890.12345672` | `1234567890.12345678` |
| 9 999 999 999 999 999 | `100000000.00000000` | `99999999.99999999` |

The ALF gateway prints `STOP` and `TRADE_PRICE` with it
(`alf_gwy/gateway.py:2096-2102`). At 8 decimals the error starts at about
90 million; at 2 decimals it is beyond any real price. It is cheap to be
exact with integer `divmod`.

**Fix.** Format from the integer: sign, `divmod(abs(ticks), 10**d)`,
zero-padded fraction.

---

### C4. `Trade.tick_decimals` is wrong on every engine trade, and two model APIs vouch for nothing — Low

`trade.py:436`, `trade.py:528-547`, `message.py:489-530`.

- `Trade.create` defaults `tick_decimals=2` and the engine never passes one
  (`order_book.py:2028-2042`). `to_wire` knows and reads the registry instead
  (`trade.py:499-504`). The field is still a public attribute holding a wrong
  value for every non-2-decimal symbol.
- `Trade.to_dict` writes that wrong `tick_decimals` and omits `match_type`,
  `auction_id` and `trigger_order_id`, so `from_dict(to_dict(t))` loses
  them. No production code calls it (only `test_trade_id.py` and
  `test_clearing_ticker_gateway.py`).
- `make_fill_msg` has no production caller. The engine builds fills with
  `make_order_fill_unchecked` directly (`main.py:3875`), while eight test
  files exercise `make_fill_msg`. Those tests pass whatever the engine does.

None of these is wrong on the wire today. Each is a trap for the next
caller. See Q3.

**Fix.** Pass the book's scale to `Trade.create` and drop the default, or
remove the field. Remove `Trade.to_dict` and `make_fill_msg`, or make them
complete and used (Q3).

---

## 4. Performance findings

Nothing here is a finding. The hot-path costs, for the decisions above
(*measured*, best of 5 × 300 000, lambda overhead of about 40 ns included):

| Call | ns |
|---|---|
| `Order.from_dict` | 891 |
| `Order.from_dict` + 8 `type(v) is int` checks in a wrapper | 1 178 |
| `to_ticks_exact` | 287 |
| `to_ticks` | 137 |
| `from_ticks` | 156 |
| `new_ulid` | 1 041 |
| `now_ns` | 217 |
| `new_order_id` | 183 |

The wrapper's +287 ns is an upper bound for H1's type checks. Inline checks
in `from_dict` cost less. That is about 1 % of the engine's per-order budget
(engine latency review). None of these costs grows with history or with the
day.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `message.py:1-22` | The module docstring says every message is two frames (topic, payload). Since WP-MSG01 there is a third, the trailer (`seq|eseq|envelope` on PUB, the envelope on PUSH). The topic list says `order.expired` is "DAY order expired at shutdown"; DAY orders now expire at the close (`main.py:6454-6457`), ATO/ATC at the end of their auction, and a shutdown persists DAY orders. |
| D2 | `message.py:161-172` | `encode_with_envelope` says it is for "notably the gateways", and has a doubled "The The". No production code calls it; PUSH envelopes are stamped in `messaging/bus.py:267-340`. `Envelope.root`, `caused` and `to_frame` are likewise test-only. |
| D3 | `message.py:734-748` | `make_quote_legs_msg`: "recent rows do not carry live qty/remaining/status: that detail is not retained once an order leaves the book." They do: `bid_leg`/`ask_leg` snapshots (`quote.py:76-96`, `main.py:3358-3359`). |
| D4 | `instrument.py:1-16` | Says `engine/main.py` sets `InstrumentState` and `engine/collar.py` reads it. Nothing in `src/` imports it (the engine keeps `_halted_symbols`); the operator guide (`040-risk-controls.md:110-126`) already says so. |
| D5 | `message.py:2219-2228` | The `make_log_*` helpers "exist for the client half — log viewers and CLIs". No production code calls any of the five. |
| D6 | `ids.py:28-30` | Order ids are "minted independently by five processes (ALF, BALF and REST gateways, the console, the AI trader)". The AI trader does not mint (it goes through ALF); the engine does (seed orders, combo children via `Order.create`/`ComboOrder.create`). |
| D7 | `feed_schema.py:1-14` | Lists the `session.state` payload as defined here; the module has only `TradeExecutedPayload`. |
| D8 | `price.py:169-174` | `from_ticks`: "If a float is passed, it is assumed to already be in display units ... staged migration". The cause of H1; goes with WP-MOD01. |
| D9 | `quote.py:70-73` | "the four positional fields above"; there are five. |
| D10 | `session.py:7` | "Transitions are driven by the session scheduler (pm-scheduler) process." An operator also drives them (`make_session_transition_msg`'s interactive `reply_to`, pm-opctl-cli/pm-admin). |
| D11 | architecture book `020-guided-tour.md:1078-1085` | Says `VALID_TRANSITIONS` stops the engine bypassing the opening auction because "every trading day begins with an opening auction". `PRE_OPEN → CONTINUOUS` is allowed (`session.py:31`). |
| D12 | `order.py:89-94, 128`; `message.py:65-82` | The `Order` docstring's status line omits `EXPIRED`; the PERF note counts "5 enum constructions" (there are six maps). The `orjson` `ImportError` fallback "for minimal envs" is dead: `orjson` is a hard dependency (`pyproject.toml:35`). |

---

## 6. Verified as correct

- **Tick scale is fixed for a run.** `register_tick_decimals` runs only in
  `_restore_gtc` and `_load_config` at start-up (`main.py:1228, 1707`), and
  `_tick_scale_mismatch` (`main.py:6125`) refuses a restored order
  (`main.py:2010`), a submitted order (`main.py:2005-2013`), a combo leg
  (`main.py:6090`) and a quote (`main.py:6848`) at any other scale. So the
  registry scale `to_wire`, `make_ack_msg` and `order_to_display_dict` use
  always equals the order's own `tick_decimals`.
- **`now_ns`** never returns a value at or below the last one, across
  threads, and recovers once the wall clock catches up.
- **`new_ulid`** stays monotonic when the clock steps back (keeps `_last_ms`
  and steps the random part). `Envelope.from_frame` returns `None` rather than
  raising on a bad frame.
- **PUB trailer vs PUSH envelope.** `_publisher_trailer` needs two all-digit
  fields before the envelope; a PUSH envelope starts with a 26-character
  ULID, so the two are not confused in practice.
- **`Order.from_dict`'s SMP handling**: absent or `null` stays `None`, an
  unknown value raises.
- **`QuoteIndex`**: per-gateway and per-symbol key dicts stay in step with
  `_index` on `put`/`remove`/`cancel_all_*`; history is bounded per gateway.
- **`check_type_fields`** gives the same verdict for every transport and for
  the engine backstop (`main.py:2013-2029`).
- **Trade ids**: `set_run_seq` bounds and the 9-digit counter give
  `NNNNNN-NNNNNNNNN`, unique and sortable across restarts.
- **`VALID_TRANSITIONS`** is enforced on transitions and on announcements
  (`main.py:6399, 6512`) and by the verifier (`cverifier/layer3_semantic.py:656`).
- **In-house producers** of `order.new` go through `make_order_new`, which
  coerces with `int()`, so they cannot hit H1.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Where does the engine refuse non-integer ticks and quantities in `order.new`/`order.combo`? (a) in `Order.from_dict`/`ComboLeg.from_dict`, raising `ValueError`; (b) a new first step in `_validate_new_order`; (c) decode through the generated `OrderNew.from_dict` + `validate()`. | **(a)**: it is the decoder, so the engine's existing `except (KeyError, ValueError)` (`main.py:2103`) and the combo handler's catch turn it into a malformed-order reject, and the restore path gets it too. (b) is too late: `"10" <= 0` raises `TypeError` before any value check. (c) coerces `10000.5` to `10000` with `int()`, which hides the mistake instead of refusing it. Cost about +100–290 ns per order (§4). |
| Q2 | `from_ticks` with a float: (a) raise `TypeError`; (b) keep returning it unchanged. | **(a)**. The migration it served is finished, `to_ticks` dropped its own passthrough for the same reason, and the project keeps no compatibility code. Six engine test files must send integer ticks. |
| Q3 | The test-only or never-wired model API: `Trade.to_dict`, `make_fill_msg`, `encode_with_envelope`, `Envelope.root/caused/to_frame`, the `make_log_*` helpers, `InstrumentState`, `MMPState` and the MMP fields of `MarketMakerObligation`. (a) delete the two that mislead (`Trade.to_dict`, `make_fill_msg`, moving their tests to what production runs), fix the texts of the rest; (b) delete all of them; (c) keep all, fix texts only. | **(a)**. `Trade.to_dict` and `make_fill_msg` let tests pass on code the engine never runs. The rest are honest once their docstrings are fixed, and the participant guide (`020-market-making.md:303-323`) and operator guide teach `MMPState` and `InstrumentState` as data models. (b) means rewriting those chapters for no runtime gain. |
| Q4 | The tolerance of the exact tick check: (a) `max(1e-6, 2·ulp(scaled))`; (b) parse `repr(price)` as a `Decimal` and test its exponent, falling back to 10⁻⁶; (c) keep 10⁻⁶ and document a price limit per decimal count. | **(a)**: measured 0 wrong refusals and 0 wrong acceptances over 189 000 cases, one line, and it keeps the `100 - 3*0.01` bot case. (b) gives the same verdict at about 5× the cost on every order. (c) refuses valid prices inside the documented 0–8 range. |

---

## 8. Work packages

### WP-MOD01 — The engine refuses an order or combo whose ticks or quantities are not integers, and `from_ticks` takes ticks only (H1, D8; after Q1, Q2)

**Tests first** (`tests/test_models_inbound_types.py`, engine harness):

1. `order.new` with `price_ticks: 9900.5` → `order.ack` `accepted: False`,
   `reject_code` `INVALID_VALUE` (or the malformed code `_reject` uses);
   nothing rests; no `trade.executed`. (Fails today.)
2. The same with `stop_price_ticks`, `trail_offset_ticks` or `visible_qty` a
   float → refused. (Fails today.)
3. `quantity`/`remaining_qty` of `10.5`, `True` or `"10"` → refused with a
   client reject, never the dispatcher's internal-error answer. (Fails today.)
4. `order.combo` with a leg `price_ticks: 9900.5` or `quantity: 5.5` →
   `combo.ack` `accepted: False`; no leg rests. (Fails today.)
5. `from_ticks(100.0, "AAPL")` raises `TypeError`; `from_ticks(10000,
   "AAPL") == 100.0`. (Fails today.)
6. A valid integer order and combo are accepted and trade exactly as before,
   unchanged.
7. A persisted GTC file with integer fields restores unchanged.

**Change.** In `Order.from_dict` check, before assigning, that the integer
fields (`quantity`, `remaining_qty`, `ts_ns`, `tick_decimals`, and the four
optional tick/qty fields when not `None`) are `int` and not `bool`; raise
`ValueError` naming the field. The same in `ComboLeg.from_dict`
(`quantity`, `tick_decimals`, `price_ticks`, `stop_price_ticks`). Remove the
float branch of `from_ticks` and fix its docstring (D8). Change the six engine
test files from H1 to send integer ticks. Measure `Order.from_dict` before
and after.

**Exit criteria.** Tests 1–7 pass; `tests/test_engine_*.py`,
`tests/test_new_order_types.py`, `tests/test_auction.py`,
`tests/test_persistence*.py` and the full suite green; `Order.from_dict` at
most +150 ns (a guess, to be confirmed by the before/after numbers).

---

### WP-MOD02 — Every price on a 0–8 decimal grid is accepted, and a non-finite or overflowing price is a tick violation (C1, C2; after Q4)

**Tests first** (`tests/test_models_price.py`; REST in
`tests/test_api_gateway_writes.py`; config in `tests/test_config_price_units.py`):

1. For every `tick_decimals` 0–8 and decades 1 to 10⁷, a seeded sample of
   typed on-grid prices converts to the exact tick count. (Fails today at
   6 and 8 decimals.)
2. The same sample offset by half a tick raises `TickViolation`, unchanged.
3. `100 - 3*0.01` at 2 decimals → 9997, unchanged; `100.005` → `TickViolation`,
   unchanged.
4. `inf`, `-inf`, `nan` and `1e308` raise `TickViolation`. (Fails today.)
5. REST `POST /api/v1/orders` with `"price": 1e308` → 400
   `TICK_VIOLATION`, nothing sent to the engine. (Fails today: 500.)
6. `load_engine_config` loads `BTCX: {tick_decimals: 8, last_buy_price:
   1234.56789012}`; `pm-cverifier` reports no `S078` for it. (Fails today.)

**Change.** In `to_ticks_exact_at`: raise `TickViolation` when `scaled` is
not finite; compare against `max(_TICK_EPSILON, 2 * math.ulp(scaled))`.
Update the `_TICK_EPSILON` comment.

**Exit criteria.** Tests 1–6 pass; `tests/test_config_*.py`,
`tests/test_cverifier*.py`, `tests/test_api_gateway_*.py`,
`tests/test_alf_*.py` and the full suite green.

---

### WP-MOD03 — Prices format exactly, and no model API carries a wrong scale or vouches for code production does not run (C3, C4; after Q3)

**Tests first** (`tests/test_models_price.py`, `tests/test_trade_id.py`):

1. `format_price_ticks(123456789012345678, sym8)` ==
   `"1234567890.12345678"`; negative ticks and 0 decimals format correctly.
   (Fails today.)
2. A trade the engine mints on a 4-decimal symbol has `tick_decimals == 4`
   (or the field is gone, per Q3). (Fails today.)
3. The fill-shape assertions now in `make_fill_msg` tests hold on the
   engine's real `order.fill` frames, unchanged in content.

**Change.** Exact integer formatting in `format_price_ticks`. Pass the book's
scale into `Trade.create` and drop the default. Per Q3 (a): delete
`Trade.to_dict` and `make_fill_msg`, moving their tests to `Trade.to_wire`
and to engine-published fills.

**Exit criteria.** Tests 1–3 pass; `tests/test_alf_gwy_*.py`,
`tests/test_clearing_*.py` and the full suite green.

---

### WP-MOD04 — Docstrings, comments and the guides say what the models do (D1–D7, D9–D12)

**Tests first.** None: text only. Every changed passage is checked against
the code it describes, and any doc transcript touched is re-run, not edited
by hand.

**Change.** Fix each item in §5 except D8 (WP-MOD01). For D11, say that
`VALID_TRANSITIONS` forbids jumping from `CLOSED`, and that a day may open
straight into `CONTINUOUS` from `PRE_OPEN`. Re-check the architecture book's
quotes of `models/price.py` and `models/order.py` against WP-MOD01–03.

**Exit criteria.** `make _check` green; `mkdocs build` clean; full suite green.

---

## 9. Out of scope, noted

- **Engine inbound rounding of admin and amend values** (L043): the
  price-level orders filter converts with nearest-tick `to_ticks`
  (`main.py:3130-3132`), so `100.005` silently shows the 100.00 or 100.01
  level; an amend's `qty` is coerced with `int()` (`main.py:7349-7353`), so
  `10.7` becomes 10. Both should refuse, like `to_ticks_exact`. Engine code,
  not a model.
- **The generated `from_dict` truncates float ticks** (`generated/order.py:97`,
  `int(p["price_ticks"])`): a producer computing `10000.5` sends 10000 without
  an error. In-house producers compute integers, so it is latent. It belongs
  to the msgen review (CR16) and is part of L043.
- **pm-clearing recomputes ticks from the display price**
  (`clearing/main.py:183-185`) instead of reading `price_ticks`. It is exact
  below 2⁵³ ticks, so it is not a defect; after WP-MOD01 the two cannot
  disagree.
