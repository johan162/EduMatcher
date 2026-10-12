# Deterministic Verification of the Matching Engine

!!! note "Learning objectives"
    After reading this page you will understand:

    - Why a matching engine is hard to verify deterministically — and what makes it
      different from testing a pure function
    - What "paper trading" means in the context of algorithmic verification, and why
      it produces a reliable oracle
    - How each of the four verification tools works and how they interact
    - The specific traps that real-time clocks, UUIDs, and distributed state set for
      anyone who wants to replay a set of orders and compare results
    - How the toolset sidesteps those traps — and where residual assumptions remain



## Why verification is hard

### The matching engine is not a pure function

A pure function always returns the same output for the same input.
A matching engine is **not** pure:

- Orders carry UUIDs generated at submission time — two runs produce different IDs.
- The engine tracks wall-clock timestamps for event ordering and expiry.
- `TIF=GTC` (Good Till Cancelled) orders are saved to disk; a second run inherits
  the state of the first unless that file is deleted.
- The engine runs as a separate OS process communicating over ZeroMQ; network
  scheduling and OS scheduling can re-order message delivery.
- STOP and STOP_LIMIT orders only trigger when the engine's internal `last_price`
  crosses the stop level — that internal price is built up incrementally from the
  same trade sequence, so a single out-of-order delivery poisons every subsequent
  STOP evaluation.

Any of these effects can cause two "identical" order streams to produce different
books, even if the matching algorithm is perfectly correct.

### Replay vs. re-simulation

There are two ways to verify a matching engine:

| Approach | How | Risk |
|----------|-----|------|
| **Replay** | Record the exact bytes sent to the live engine, re-send them later, compare | Message timing; GTC state; clock drift |
| **Re-simulation** | Run the same orders through a parallel implementation of the algorithm | The parallel implementation may have its own bugs |

EduMatcher uses a **hybrid**: orders are generated once as a FIX text file (the
single source of truth), then played through two separate execution paths:

1. **Paper trader** — calls `OrderBook.process()` directly in-process, no ZMQ,
   no clocks, no GTC persistence.  This is the oracle.
2. **Live engine** — receives the same orders over ZMQ, runs the full production
   path, then exposes book state via a snapshot API.

If the two books agree at price-level granularity, the engine is verified.

!!! warning "What this does **not** verify"
    The toolset compares **resting book state** and **last trade prices**.
    It does not verify fill attribution (which gateway received which fill), the
    order of individual trade events, or P&L computations.  Those require
    additional test fixtures (see `tests/test_clearing_ticker_gateway.py`).



## The verification flow

```
gen_verification_set.py
  │
  ├─ writes ──▶  data/verify/mm_orders.fix             (market-maker seeds)
  ├─ writes ──▶  data/verify/test_orders.fix           (new/amend/cancel flow)
  ├─ writes ──▶  data/verify/verify_engine_config.yaml (regenerated every run)
  └─ writes ──▶  data/verify/paper_result.json         ◀── ORACLE
                                                               │
                                                  compare_results.py
                                                               │
replay_to_engine.py ──▶  live engine ──▶  data/verify/engine_result.json
```

`tools/verify_matching.sh` orchestrates all five steps in sequence.



## Tool 1 — `gen_verification_set.py`

**Location:** `tools/gen_verification_set.py`
**Role:** Generate the FIX input files and run the paper trade to produce the
oracle result.

### What it builds

The generator creates two FIX files, one YAML config, and one JSON file:

| File | Contents |
|------|----------|
| `mm_orders.fix` | 56 market-maker limit orders that seed initial liquidity on four symbols |
| `test_orders.fix` | *N* lines (default 10 000): ~70% new single-leg orders, ~30% `AMEND`/`CANCEL` against something already resting |
| `verify_engine_config.yaml` | The engine config this run has to be replayed against — regenerated every time (see [The verification config](#the-verification-config)) |
| `paper_result.json` | Final book state for each symbol after processing all orders in-process |

### Market-maker seed orders

Each symbol receives 5 bid levels and 5 ask levels centred on a reference
mid-price, plus extra depth orders to give each level more than one order in
the queue:

| Symbol | Mid | Half-spread | Bid L1 | Ask L1 |
|--------|-----|-------------|--------|--------|
| AAPL | 150.00 | 0.25 | 149.75 | 150.25 |
| AMAZ | 180.00 | 0.25 | 179.75 | 180.25 |
| MSFT | 420.00 | 0.50 | 419.50 | 420.50 |
| GOOG | 160.00 | 0.25 | 159.75 | 160.25 |

MSFT uses a wider half-spread (0.50) because at higher prices a sub-cent spread
is unrealistic — this also exercises the stop-price arithmetic with a different
scale.

A seed block looks like this in `mm_orders.fix`:

```
# --- AAPL market-maker seed ---
NEW|ID=mm-AAPL-000|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=149.75|TIF=DAY
NEW|ID=mm-AAPL-001|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=500|PRICE=150.25|TIF=DAY
NEW|ID=mm-AAPL-002|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=300|PRICE=149.50|TIF=DAY
NEW|ID=mm-AAPL-003|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=300|PRICE=150.50|TIF=DAY
...
```

Every `NEW` line names its own order with an `ID=` field — readable,
`mm-<symbol>-NNN` ids for the seed orders — so that a later `AMEND` or
`CANCEL` line can refer back to it (see
[Problem 1](#problem-1-order-ids-now-reproducible-by-design) below).

Comment lines (starting with `#`) are silently skipped by both the paper trader
and the replay client.

### Random test orders: new, amend, or cancel

Each of the *N* test lines (`--count`, default 10 000) does one of two things:

- **70% of the time** (or whenever nothing is resting yet) it submits a brand
  new order, from the same weighted distribution of order types as before:

  | Type | Weight | Notes |
  |------|--------|-------|
  | `LIMIT` | 35% | Price chosen near or away from market |
  | `MARKET` | 22% | No price field — sweeps whatever is resting |
  | `ICEBERG` | 13% | Large total qty with small `VISIBLE` slice |
  | `FOK` | 10% | Fill-or-Kill — cancels if not immediately fully filled |
  | `IOC` | 10% | Immediate-or-Cancel — partial fill allowed |
  | `STOP` | 5% | Triggers when `last_price` crosses the stop level |
  | `STOP_LIMIT` | 5% | Stop that converts to a limit, not a market |

  60% of limit-family orders are "near market" (price within 3 half-spreads of mid),
  making a high fill rate likely and stress-testing deep-book mechanics.

- **30% of the time** (`AMEND_SHARE`), it instead acts on an order that is
  resting *right now* — picked at random from the live set the generator is
  tracking as it paper-trades — and emits an `AMEND` or `CANCEL` line against
  it instead of a new `NEW`:

  | Outcome | Weight | What it exercises |
  |---------|--------|--------------------|
  | Reprice | 30% | `amend_order`'s re-queue path; see "aggressive" below |
  | Reduce quantity | 20% | A reduction keeps time priority |
  | Increase quantity | 20% | An increase loses time priority |
  | Reprice **and** resize | 10% | Both of the above together |
  | Cancel | 20% | Removes the order; frees it from the live set |

  Only `LIMIT` and `ICEBERG` orders ever rest long enough to be amendable — a
  `MARKET`/`FOK`/`IOC` order never rests, and a pending `STOP` lives in a
  separate heap the amend path does not reach — so only those two types are
  ever chosen as an amend/cancel target.

  Of the reprices, 35% deliberately land *through* the opposite side's best
  price rather than nudging by a cent or two. That turns the amend
  marketable: the engine pulls the re-queued order back out and runs it
  through matching instead of just re-resting it — cancel/replace semantics,
  so an amend can never leave the book crossed. The other 65% are small
  nudges (±0.01 to ±0.03) that keep the order resting and exercise
  re-queueing and the priority rules instead.

A typical block in `test_orders.fix`, showing one of each kind:

```
NEW|ID=3f7a1c9b2e4d6801b3f5a9c0d1e2f7a4|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=500
NEW|ID=9c1e4a7f0b3d6289c4e7a0f3b6d9e2c5|SYM=GOOG|SIDE=BUY|TYPE=LIMIT|QTY=250|PRICE=159.23
NEW|ID=0a2d5c8f1b4e7390d5f8b1e4a7c0f3d6|SYM=MSFT|SIDE=BUY|TYPE=ICEBERG|QTY=900|PRICE=419.03|VISIBLE=50
NEW|ID=6e9f2b5c8a1d4073e8b1f4c7a0d3e6f9|SYM=AMAZ|SIDE=SELL|TYPE=STOP|QTY=450|STOP=179.60
NEW|ID=2b5e8c1f4a7d0396f1c4e7b0a3d6f9c2|SYM=GOOG|SIDE=SELL|TYPE=STOP_LIMIT|QTY=200|STOP=159.50|PRICE=159.25
AMEND|ID=9c1e4a7f0b3d6289c4e7a0f3b6d9e2c5|PRICE=159.18
CANCEL|ID=0a2d5c8f1b4e7390d5f8b1e4a7c0f3d6
```

Order ids are random 128-bit hex, generated from the same `--seed`-ed RNG as
everything else — not `Order.create()`'s own UUID (more on this under
[Problem 1](#problem-1-order-ids-now-reproducible-by-design)).

### The paper trader

After writing both FIX files, the generator processes **the same text** through
`OrderBook` instances — one per symbol — without any networking. Simplified,
dropping the bookkeeping that tracks which orders are still resting (needed
so an `AMEND`/`CANCEL` line can find its target):

```python
books = {sym: OrderBook(sym) for sym in SYMBOLS}
for line in mm_lines + test_lines:
    verb, kv = parse_line(line)
    if verb == "NEW":
        books[symbol_of(kv)].process(parse_fix_line(line))
    elif verb == "CANCEL":
        books[symbol].cancel_order(kv["ID"])
    elif verb == "AMEND":
        books[symbol].amend_order(kv["ID"], new_price=..., new_qty=...)
```

`OrderBook.process()`, `.cancel_order()`, and `.amend_order()` all return
synchronously.  There are no sockets, no threads, no timers.  The result is
deterministic for a given seed — generation and paper-trading happen in the
*same* pass, because an amendment has to name an order that is resting at
that exact point in the stream, and only the book being built knows which
orders those are.

### Determinism is guaranteed by the seed

The `--seed` flag is passed directly to `random.Random`.  The same seed always
produces the same FIX files — new orders, amendments and cancellations alike —
which always produces the same paper result:

```bash
# Reproducible run
poetry run python tools/gen_verification_set.py --seed 42 --count 1000

# Different population, still reproducible
poetry run python tools/gen_verification_set.py --seed 7 --count 500
```

The seed is not stored in the output files.  If you lose track of which seed was
used to produce a `paper_result.json`, regenerate it — the FIX files are the
authoritative input.

### Typical output

```
[GEN] Generating and paper-trading 1000 line(s) …
[GEN] Wrote 56 MM orders  → data/verify/mm_orders.fix
[GEN] Wrote engine config    → data/verify/verify_engine_config.yaml
[GEN] Wrote 1000 test lines  → data/verify/test_orders.fix
      769 new, 238 amend, 49 cancel → 879 trades
  AAPL    bids=12 levels  asks=14 levels  last=150.22
  AMAZ    bids=8 levels  asks=17 levels  last=180.30
  MSFT    bids=16 levels  asks=13 levels  last=418.83
  GOOG    bids=9 levels  asks=25 levels  last=160.07
[GEN] Saved paper result     → data/verify/paper_result.json
[GEN] Done — run replay_to_engine.py to get the engine result.
```

(Real numbers for `--seed 42 --count 1000`, reproduced exactly on every run
with that seed.) There is no "skipped" count any more — the four `#` comment
header lines in `mm_orders.fix` are silently skipped while building the MM
book, and `replay_to_engine.py`'s own parse-error counter (below) is what
surfaces them later.



## Tool 2 — `replay_to_engine.py`

**Location:** `tools/replay_to_engine.py`
**Role:** Connect to a running engine as gateway `VERIFY01`, send every order
from the FIX files (waiting for each ACK), then request and save book snapshots.

### Prerequisites

`gen_verification_set.py` writes a fresh `verify_engine_config.yaml` on every
run (admitting only gateway `VERIFY01`, same four symbols) — it still has to
be **deployed** before the engine will use it, and then the engine started:

```bash
poetry run pm-config-deploy data/verify/verify_engine_config.yaml
poetry run pm-engine
```

No process takes a config path as an argument, so this deploy step is what
makes the just-generated config the one the engine actually loads; skip it
and the engine keeps whatever configuration was deployed before.

### Protocol

The replay client is a thin ZeroMQ wrapper:

```
                   PUSH ──────────────────▶  Engine PULL
Client (VERIFY01)                            Engine
                   SUB  ◀──────────────────  Engine PUB
```

Before sending any orders it authenticates: it PUSHes a `gateway_connect` for
`VERIFY01` and waits (up to 3 000 ms) on the SUB socket for
`system.gateway_auth.VERIFY01` to come back accepted.

Then, for each dataset line:

1. **`NEW`** — encode the `Order` as `make_order_new_msg(order.to_dict())`,
   `push_sock.send_multipart(frames)`, then poll SUB for
   `order.ack.VERIFY01` (up to 2 000 ms) and match its `order_id` against the
   order just sent.
2. **`AMEND`** — send `make_order_amend_msg(order_id, "VERIFY01", price=…,
   qty=…)` and wait for either `order.amended.VERIFY01` (accepted) or an
   `order.ack.VERIFY01` carrying `accepted=False` (refused) for that
   `order_id`.
3. **`CANCEL`** — send `make_order_cancel_msg(order_id, "VERIFY01")` and wait
   the same way on `order.cancelled.VERIFY01`.

Only once a line's confirmation arrives does the client send the next line.

This **synchronous send-and-wait loop** is the single most important design
choice in the replay tool.  Without it, the engine's internal message queue can
reorder lines, breaking STOP trigger sequences and letting an `AMEND` or
`CANCEL` overtake the line it targets — either way making the result
non-deterministic.

!!! warning "Why ACK matching matters for STOPs"
    A STOP order on AAPL triggers when `last_price` crosses its stop level.
    If AAPL-LIMIT orders are sent ahead of the stop without waiting for their
    ACKs, the engine may process them in a different order than the paper trader
    did.  The `last_price` diverges, and the STOP may never trigger (or trigger
    too early).  The ACK loop enforces the same ordering in both paths.

### Snapshot collection

After all orders are sent, the client pauses 0.5 s (configurable via
`DRAIN_PAUSE_S`) to let the engine finish any async work, then sends a
`book.snapshot_request` message for each symbol:

```python
push_sock.send_multipart(make_book_snapshot_request_msg("AAPL"))
# Engine publishes the snapshot to topic  book.AAPL
snap = wait_for_topic("book.AAPL", timeout_ms=5000)
```

The snapshot is normalised to the same `{bids, asks, last_price, ...}` shape
used by the paper result, then saved to `data/verify/engine_result.json`.

### Typical output

(Real output for the `--seed 42 --count 1000` dataset generated above, with
the engine running with no competing resting orders — a "rej" line for
`NEW`/`AMEND`/`CANCEL` all count toward the same `rejected` tally.)

```
[REPLAY] Gateway VERIFY01 authenticated.
[REPLAY] … 500 lines sent (500 acc, 0 rej)
[REPLAY] … 1000 lines sent (1000 acc, 0 rej)
[REPLAY] Sent 1056 lines in 0.59s  (1056 accepted, 0 rejected, 4 parse errors)
[REPLAY] Pausing 0.5s for engine to drain …
[REPLAY] Requesting book snapshots …
  AAPL    bids=12 levels  asks=14 levels  last=150.22
  AMAZ    bids=8 levels  asks=17 levels  last=180.3
  MSFT    bids=16 levels  asks=13 levels  last=418.83
  GOOG    bids=9 levels  asks=25 levels  last=160.07
[REPLAY] Saved engine result → data/verify/engine_result.json
[REPLAY] Done — run compare_results.py to verify.
```

Progress prints every 500 lines (not every 100), and the "4 parse errors" here
are the same four `#` comment lines in `mm_orders.fix` seen in Tool 1 — this
tool's own parser skips them too, but the summary line is the only place that
counts them. Same `--seed 42 --count 1000` run throughout, so the book state
(and `compare_results.py`'s verdict below) match Tool 1's example exactly.



## Tool 3 — `compare_results.py`

**Location:** `tools/compare_results.py`
**Role:** Load both JSON files, compare them field by field, and print a PASS or
FAIL verdict with a full diff.

### What is compared

For each symbol, the comparison checks:

| Field | Comparison |
|-------|------------|
| Bid levels | Price and total visible qty at each level, sorted high→low |
| Ask levels | Price and total visible qty at each level, sorted low→high |
| `last_price` | Last trade price (both sides) |
| `last_buy_price` | Last price where the aggressor was a BUY |
| `last_sell_price` | Last price where the aggressor was a SELL |

### What is deliberately **not** compared

- **Order IDs** — the paper trader uses `gateway_id="PAPER01"` and the engine
  uses `"VERIFY01"`.  Even if the IDs matched, comparing them would be wrong
  because individual orders can be partially filled and recombined differently.
- **Number of resting orders per level** — only total visible qty matters for
  the book state.  The paper trader and engine may have placed depth orders at
  the same price as separate entries; the snapshot already aggregates them.
- **Fill counts / trade events** — these are in-flight and not captured in the
  snapshot.

### Tolerance flag

For quantities, the default is an exact match.  If floating-point rounding in
the engine produces a minor deviation, use `--tolerance`:

```bash
# Allow up to 0.5% quantity discrepancy per level
poetry run python tools/compare_results.py --tolerance 0.005
```

Two other flags exist for ad-hoc use: `--paper FILE`/`--engine FILE` point at
a different pair of result files, and `--symbols SYM [SYM …]` restricts the
comparison to a subset of the four.

### Reading the output

Before the per-symbol breakdown, the tool prints a compact side-by-side
table — bid/ask level counts and `last_price` for both sides, one row per
symbol, with a `✓`/`✗` glyph summarising each row. Then, for each symbol:

A passing run (real output, same `--seed 42 --count 1000` dataset as the Tool
1 and Tool 2 examples above):

```
── AAPL ──────────────────────────────────
  ✓  PASS  — 12 bid level(s), 14 ask level(s), last=150.22

── AMAZ ──────────────────────────────────
  ✓  PASS  — 8 bid level(s), 17 ask level(s), last=180.3

═══  RESULT: PASS  ═══
```

A failing run with a qty mismatch looks like this (illustrative — not from a
real failing dataset):

```
── AAPL ──────────────────────────────────
  ✗  BID[2] qty @ 149.50: paper=450, engine=400
  ✗  last_price: paper=149.55, engine=149.75

═══  RESULT: FAIL  ═══
```

Note the per-symbol headers use light dashes (`──`), not the heavy `━━━` that
`verify_matching.sh`'s own step headers use (see below) — the two scripts
format their output independently.

Exit code is `0` on PASS and `1` on FAIL, making it composable in CI pipelines.



## Tool 4 — `verify_matching.sh`

**Location:** `tools/verify_matching.sh`
**Role:** Orchestrate all steps in a single shell command.

```bash
./tools/verify_matching.sh
```

The script performs five steps:

1. **Generate** — run `gen_verification_set.py` to produce the FIX files,
   the (re)generated `verify_engine_config.yaml`, and the oracle.
2. **Start engine** — resolve the engine's real data directory, delete any
   stale GTC/book-stats persistence files in *that* directory, deploy
   `verify_engine_config.yaml` as the active configuration
   (`pm-config-deploy`), then launch `pm-engine` in the background and wait
   2 s for it to bind.
3. **Replay** — run `replay_to_engine.py` against the running engine.
4. **Stop engine** — send SIGINT and wait for it to exit.
5. **Compare** — run `compare_results.py`.

### Command-line flags

```bash
./tools/verify_matching.sh                     # seed=42, 10 000 lines
./tools/verify_matching.sh --seed 7            # reproducible with a different population
./tools/verify_matching.sh --count 200         # faster smoke test
./tools/verify_matching.sh --skip-gen          # reuse existing .fix files (re-run engine only)
./tools/verify_matching.sh --tolerance 0.005   # pass 0.5% qty tolerance to compare
./tools/verify_matching.sh --pull tcp://localhost:5555 --pub tcp://localhost:5556
                                                # non-default engine addresses
```

`--pull`/`--pub` are passed straight through to `replay_to_engine.py`; both
default to the engine's real PULL/PUB addresses (5555/5556).

### Clean-state guarantee

Stale GTC state is the most common cause of spurious failures. Naively
deleting `data/gtc_orders.json` et al. relative to the repository root used
to be exactly that kind of bug: in a source checkout the engine's real data
directory is `src/data/`, not `data/` (see
[Where your data directory actually is](010-development-practice.md#where-your-data-directory-actually-is)) —
so the old version of this step silently cleaned a directory the engine never
read, and every run "started clean" while actually inheriting the previous
run's resting orders. The script now asks the code where the data directory
really is, rather than assuming:

```bash
DATA_DIR="$(poetry run python -c 'from edumatcher.config import DATA_DIR; print(DATA_DIR)')"
rm -f "$DATA_DIR/gtc_orders.json" \
      "$DATA_DIR/gtc_combos.json" \
      "$DATA_DIR/book_stats.json"
```

If you are running the script inside a CI job that also runs the main test
suite, make sure the test suite finishes (and the engine stops) before
`verify_matching.sh` starts — otherwise the GTC files written by the previous
run will corrupt the initial book state.



## The hardest problems: time, identity, and state

This section documents the traps that made the toolset non-trivial to build.
Understanding them is useful when you extend the verification suite or adapt
it to a different system.

### Problem 1 — Order ids, now reproducible by design

`Order.create()` itself mints a fresh random UUID on every call, which would
make `--seed 42` produce a different dataset on every run — fatal once
amendments and cancellations need to name the order they act on. The
generator works around this by minting its *own* deterministic id
(`_order_id()`, seeded from the same `random.Random`) and overwriting
`order.id` with it before the line is written; the FIX line then carries
that id explicitly (`NEW|ID=<id>|...`), and both `replay_to_engine.py` and
the live engine (`Order.from_dict`, reading straight off the wire) adopt it
unchanged. So a `--seed 42` run really does produce exactly the same 1 056
order ids every time, in both the paper result and the engine result.

That still doesn't make `order_id` safe to compare directly, for an
unrelated reason: the book snapshot used for comparison never exposes ids in
the first place. **Solution (unchanged):** compare at price-level aggregate.
The snapshot API returns `{price, qty}` pairs, not order ids — two different
orders resting at $149.50 with total visible qty 450 are equivalent for
book-state purposes regardless of what either side happened to call them.

### Problem 2 — TIF=DAY orders expire at session end

`DAY` orders live only within the current session.  The engine's scheduler
marks them expired when the session transitions to `POST_TRADING` or `CLOSED`.

If the engine session ends between sending the last order and requesting the
snapshot, all resting `DAY` orders vanish — and the book will appear empty.

**Solution:** the generated config sets `sessions_enabled: false`. That
single line means no `pm-scheduler` is expected and the engine starts
straight in `CONTINUOUS` — rather than the `true`-default behaviour of
starting `CLOSED` and waiting for one to open the market — and simply stays
there, since nothing ever schedules a transition out of it. All test orders
use `TIF=DAY` (the default), which in a perpetual `CONTINUOUS` session never
expires.

!!! tip "GTC orders add a different complication"
    `TIF=GTC` orders survive session transitions by being written to
    `gtc_orders.json`.  The script's clean-state step deletes that file before
    each run, ensuring the engine starts from a blank slate.  Without this step,
    GTC orders from a previous run would sit on the book and cause the MM seed
    orders to fill against unexpected resting liquidity.

### Problem 3 — STOP prices depend on last_trade_price sequence

A STOP BUY at $150.50 only triggers if a trade prints at or above $150.50.
Whether that trade happens at all depends on the exact order in which prior
orders arrived.  A single out-of-order message can shift `last_price` by one
tick and prevent or trigger an entire cascade of stops.

**Solution:** The replay client uses a strict synchronous send-and-wait loop.
No new line — `NEW`, `AMEND`, or `CANCEL` — is sent until the engine has
confirmed (or timed out on) the previous one.  This enforces the same
processing sequence as the paper trader, which applies one dataset line at a
time in a tight loop.

### Problem 4 — Gateway IDs differ between paper and engine

The paper trader assigns `gateway_id="PAPER01"` to every order.  The live
engine is configured to accept only `gateway_id="VERIFY01"`.

At first glance this might seem to mean the two paths process different orders.
In practice, `gateway_id` is stored on the `Order` object but plays no role in
matching logic — it is used only for ACK routing and fill attribution.  Two
orders identical in symbol, side, type, price, and qty will produce identical
book outcomes regardless of `gateway_id`.

### Problem 5 — The drain window

The engine processes orders asynchronously via a ZeroMQ PULL socket.  Even
after the last ACK is received by the replay client, the engine may still be:

- Evaluating pending STOP triggers
- Writing fills back to the PUB socket

If a snapshot is requested before this work completes, the snapshot will be
stale.

**Solution:** A 0.5 s pause (`DRAIN_PAUSE_S`) is inserted between the last ACK
and the first snapshot request.  This is a heuristic — it works reliably on
modern hardware for 1 000 orders, but could theoretically fail on a very heavily
loaded machine.  The snapshot timeout is set to 5 000 ms as an additional
safety net.

### Problem 6 — Iceberg visible-qty refresh

An iceberg order has a `total_qty` and a `visible_qty`.  When the visible slice
is fully consumed, the engine replenishes it from the hidden reserve.  The
replenishment creates a *new* queue position for the refreshed slice.

In the paper trader, this happens inline inside `book.process()`.  In the
engine, it is triggered by the same `process()` call but may interact with
subsequent orders differently if message timing varies.

The comparison aggregates total visible qty at each price level, not per-order
qty.  As long as the total resting quantity at $419.03 is 450 in both cases, the
iceberg's internal refresh state does not matter.



## The verification config

`data/verify/verify_engine_config.yaml` is **not** a hand-maintained file —
`gen_verification_set.py` writes a fresh copy of it (`build_engine_config()`)
on every run, from the same `SYMBOLS`/`REF_PRICE` tables the FIX files are
built from, so the two can never drift apart. It used to be a real file
tracked outside the generator, gitignored under `data/**` and never actually
committed — so a fresh checkout failed at the "start engine" step with
nothing to deploy. Real output, verbatim:

```yaml
# Generated by tools/gen_verification_set.py -- do not edit.
# Regenerated on every run, from the same SYMBOLS and REF_PRICE the
# orders are built from.

# The engine is the whole market here: no scheduler runs, so session
# handling has to be off or the engine sits in CLOSED and rejects
# every order with MARKET_CLOSED.
sessions_enabled: false

participants:
  - id: VERIFY01

symbols:
  AAPL:
    reference_price: 150.00
  AMAZ:
    reference_price: 180.00
  MSFT:
    reference_price: 420.00
  GOOG:
    reference_price: 160.00
```

Key decisions:

- Only `VERIFY01` is allowed — any existing production gateway that happens to
  be connected will be rejected, preventing order bleed.
- No `market_maker_orders` stanza — liquidity is injected via the FIX file
  itself, so the paper trader and engine see identical seeds.
- `sessions_enabled: false` — the engine starts straight in `CONTINUOUS` and
  stays there indefinitely (see [Problem 2](#problem-2-tifday-orders-expire-at-session-end)),
  avoiding `TIF=DAY` expiry.



## Running the full suite

```bash
# One-shot end-to-end verification (takes ~10 s on a laptop)
./tools/verify_matching.sh

# Faster smoke test with fewer lines
./tools/verify_matching.sh --count 100

# Regression: fix the seed, run on every commit
./tools/verify_matching.sh --seed 42 --count 10000

# Reuse the existing FIX files to re-test after an engine code change
./tools/verify_matching.sh --skip-gen
```

Expected end-to-end output for a passing run (real, `--seed 42`, default
`--count 10000` — elapsed time measured directly at ~10.6 s total, so the
"~10 s on a laptop" estimate above still holds even though the default line
count is ten times what it used to be):

```
━━━  STEP 1 — Generate verification dataset (seed=42, count=10000)  ━━━
[GEN] Generating and paper-trading 10000 line(s) …
[GEN] Wrote 56 MM orders  → data/verify/mm_orders.fix
[GEN] Wrote engine config    → data/verify/verify_engine_config.yaml
[GEN] Wrote 10000 test lines  → data/verify/test_orders.fix
      7106 new, 2380 amend, 570 cancel → 9020 trades
  AAPL    bids=56 levels  asks=65 levels  last=150.37
  AMAZ    bids=77 levels  asks=55 levels  last=179.92
  MSFT    bids=102 levels  asks=81 levels  last=419.92
  GOOG    bids=69 levels  asks=73 levels  last=160.21
[GEN] Saved paper result     → data/verify/paper_result.json
[GEN] Done — run replay_to_engine.py to get the engine result.

━━━  STEP 2 — Start matching engine  ━━━
[VERIFY] Engine data directory: /path/to/checkout/src/data
[VERIFY] Deploying verify_engine_config.yaml …
[VERIFY] Starting engine …
[VERIFY] Waiting for engine to bind (2 s) …
[VERIFY] Engine PID=84231 is running.

━━━  STEP 3 — Replay orders to engine  ━━━
[REPLAY] Gateway VERIFY01 authenticated.
[REPLAY] … 500 lines sent (500 acc, 0 rej)
...
[REPLAY] Sent 10056 lines in 5.94s  (10056 accepted, 0 rejected, 4 parse errors)
[REPLAY] Pausing 0.5s for engine to drain …
[REPLAY] Saved engine result → data/verify/engine_result.json

━━━  STEP 4 — Shut down engine  ━━━
[VERIFY] Sending SIGINT to engine …

━━━  STEP 5 — Compare paper vs engine  ━━━
  ✓  PASS  — 56 bid level(s), 65 ask level(s), last=150.37
  ✓  PASS  — 77 bid level(s), 55 ask level(s), last=179.92
  ✓  PASS  — 102 bid level(s), 81 ask level(s), last=419.92
  ✓  PASS  — 69 bid level(s), 73 ask level(s), last=160.21

═══  RESULT: PASS  ═══

✓  Verification PASSED — engine output matches paper trade.
```



## Summary

| Problem | Root cause | Solution |
|---------|-----------|----------|
| Order id comparison | Book snapshots don't expose ids at all | Compare at price-level aggregate (the generator's own ids *are* reproducible, for `AMEND`/`CANCEL`'s sake, but that's beside the point) |
| `TIF=DAY` expiry | Scheduler fires session transition | `sessions_enabled: false` → engine starts and stays `CONTINUOUS` |
| GTC state leak | Previous run writes to disk | Delete GTC/book-stats files in the engine's *real* data directory before each run |
| STOP trigger sequence | `last_price` depends on arrival order | Synchronous send-and-wait loop, for `NEW`, `AMEND`, and `CANCEL` alike |
| Different `gateway_id` | Engine rejects PAPER01 | Use `VERIFY01` in engine config; ID has no effect on matching |
| Async drain window | Engine still evaluating after last confirmation | 0.5 s pause + 5 s snapshot timeout |
| Iceberg refresh position | Hidden reserve replenishment | Aggregate visible qty per price level |



## What next?

- [Order Types](../../participant-guide/part-2-orders/020-order-types.md) — the full mechanics of each order type that the
  generator exercises
- [Messages](../../protocols-and-clients/part-5-message-reference/010-message-reference.md) — the ZeroMQ message protocol used by the replay client
- [Architecture](../part-1-architecture/010-architecture-overview.md) — how the engine, gateway, and ZMQ bus fit
  together
