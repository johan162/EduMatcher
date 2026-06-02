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
  ├─ writes ──▶  data/verify/mm_orders.fix      (market-maker seeds)
  ├─ writes ──▶  data/verify/test_orders.fix    (1 000 random orders)
  └─ writes ──▶  data/verify/paper_result.json  ◀── ORACLE
                                                        │
                                           compare_results.py
                                                        │
replay_to_engine.py ──▶  live engine ──▶  data/verify/engine_result.json
```

`verify_matching.sh` orchestrates all four steps in sequence.



## Tool 1 — `gen_verification_set.py`

**Location:** `tools/gen_verification_set.py`
**Role:** Generate the FIX input files and run the paper trade to produce the
oracle result.

### What it builds

The generator creates two FIX files and one JSON file:

| File | Contents |
|------|----------|
| `mm_orders.fix` | 56 market-maker limit orders that seed initial liquidity on four symbols |
| `test_orders.fix` | *N* random single-leg orders (default 1 000) |
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
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=149.75|TIF=DAY
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=500|PRICE=150.25|TIF=DAY
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=300|PRICE=149.50|TIF=DAY
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=300|PRICE=150.50|TIF=DAY
...
```

Comment lines (starting with `#`) are silently skipped by both the paper trader
and the replay client.

### Random test orders

The generator draws from a weighted distribution of order types to produce a
realistic workload:

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

A typical block in `test_orders.fix`:

```
NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=500
NEW|SYM=GOOG|SIDE=BUY|TYPE=LIMIT|QTY=250|PRICE=159.23
NEW|SYM=MSFT|SIDE=BUY|TYPE=ICEBERG|QTY=900|PRICE=419.03|VISIBLE=50
NEW|SYM=AMAZ|SIDE=SELL|TYPE=STOP|QTY=450|STOP=179.60
NEW|SYM=GOOG|SIDE=SELL|TYPE=STOP_LIMIT|QTY=200|STOP=159.50|PRICE=159.25
```

### The paper trader

After writing both FIX files, the generator processes **the same text** through
`OrderBook` instances — one per symbol — without any networking:

```python
books = {sym: OrderBook(sym) for sym in SYMBOLS}
for line in mm_lines + test_lines:
    order = parse_fix_line(line, gateway_id="PAPER01")
    if order:
        books[order.symbol].process(order)
```

`OrderBook.process()` returns `(trades, events)` synchronously.  There are no
sockets, no threads, no timers.  The result is deterministic for a given seed.

### Determinism is guaranteed by the seed

The `--seed` flag is passed directly to `random.Random`.  The same seed always
produces the same FIX file, which always produces the same paper result:

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
[GEN] Wrote 56 MM orders  → data/verify/mm_orders.fix
[GEN] Wrote 1000 test orders  → data/verify/test_orders.fix
[GEN] Running paper trade …
[PAPER] Processed 1056 orders (4 skipped) → 490 trades  (9.8 ms)
  AAPL    bids=31 levels  asks=35 levels  last=149.55
  AMAZ    bids=44 levels  asks=23 levels  last=180.02
  MSFT    bids=26 levels  asks=46 levels  last=420.38
  GOOG    bids=29 levels  asks=31 levels  last=160.16
[GEN] Saved paper result     → data/verify/paper_result.json
```

The "4 skipped" are the `#` comment header lines in `mm_orders.fix`.



## Tool 2 — `replay_to_engine.py`

**Location:** `tools/replay_to_engine.py`
**Role:** Connect to a running engine as gateway `VERIFY01`, send every order
from the FIX files (waiting for each ACK), then request and save book snapshots.

### Prerequisites

The engine must already be running with the verification config:

```bash
poetry run pm-engine --config data/verify/verify_engine_config.yaml
```

The verification config (`data/verify/verify_engine_config.yaml`) allows only
gateway `VERIFY01` and defines the same four symbols.

### Protocol

The replay client is a thin ZeroMQ wrapper:

```
                   PUSH ──────────────────▶  Engine PULL
Client (VERIFY01)                            Engine
                   SUB  ◀──────────────────  Engine PUB
```

Sequence for each order:

1. Encode the `Order` as `make_order_new_msg(order.to_dict())`
2. `push_sock.send_multipart(frames)`
3. Poll the SUB socket for `order.ack.VERIFY01` — wait up to 2 000 ms
4. Match the `order_id` in the ACK payload against the sent order
5. Only advance to the next order once the ACK is received

This **synchronous send-ack loop** is the single most important design choice
in the replay tool.  Without it, the engine's internal message queue can reorder
orders, breaking STOP trigger sequences and making the result non-deterministic.

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

```
[REPLAY] Gateway VERIFY01 authenticated.
[REPLAY] … 100 orders sent (89 acc, 11 rej)
[REPLAY] … 200 orders sent (178 acc, 22 rej)
...
[REPLAY] Sent 1056 orders in 4.12s  (941 accepted, 115 rejected, 4 parse errors)
[REPLAY] Pausing 0.5s for engine to drain …
[REPLAY] Requesting book snapshots …
  AAPL    bids=31 levels  asks=35 levels  last=149.55
  AMAZ    bids=44 levels  asks=23 levels  last=180.02
  MSFT    bids=26 levels  asks=46 levels  last=420.38
  GOOG    bids=29 levels  asks=31 levels  last=160.16
[REPLAY] Saved engine result → data/verify/engine_result.json
```



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

### Reading the output

A passing run:

```
━━━  AAPL  ━━━
  ✓  PASS  — 31 bid level(s), 35 ask level(s), last=149.55

━━━  AMAZ  ━━━
  ✓  PASS  — 44 bid level(s), 23 ask level(s), last=180.02

═══  RESULT: PASS  ═══
```

A failing run with a qty mismatch:

```
━━━  AAPL  ━━━
  ✗  BID[2] qty @ 149.50: paper=450, engine=400
  ✗  last_price: paper=149.55, engine=149.75

═══  RESULT: FAIL  ═══
```

Exit code is `0` on PASS and `1` on FAIL, making it composable in CI pipelines.



## Tool 4 — `verify_matching.sh`

**Location:** `verify_matching.sh` (repo root)
**Role:** Orchestrate all steps in a single shell command.

```bash
./verify_matching.sh
```

The script performs five steps:

1. **Generate** — run `gen_verification_set.py` to produce the FIX files and
   oracle.
2. **Clean state** — delete any stale GTC persistence files
   (`gtc_orders.json`, `gtc_combos.json`, `book_stats.json`).
3. **Start engine** — launch `pm-engine` with `verify_engine_config.yaml` in
   the background and wait 2 s for it to bind.
4. **Replay** — run `replay_to_engine.py` against the running engine.
5. **Stop engine, compare** — send SIGINT to the engine, then run
   `compare_results.py`.

### Command-line flags

```bash
./verify_matching.sh                     # seed=42, 1 000 orders
./verify_matching.sh --seed 7            # reproducible with a different population
./verify_matching.sh --count 200         # faster smoke test
./verify_matching.sh --skip-gen          # reuse existing .fix files (re-run engine only)
./verify_matching.sh --tolerance 0.005   # pass 0.5% qty tolerance to compare
```

### Clean-state guarantee

Stale GTC state is the most common cause of spurious failures.  The script
explicitly removes these files before starting the engine:

```bash
rm -f data/gtc_orders.json \
      data/gtc_combos.json \
      data/book_stats.json
```

If you are running the script inside a CI job that also runs the main test
suite, make sure the test suite finishes (and the engine stops) before
`verify_matching.sh` starts — otherwise the GTC files written by the previous
run will corrupt the initial book state.



## The hardest problems: time, identity, and state

This section documents the traps that made the toolset non-trivial to build.
Understanding them is useful when you extend the verification suite or adapt
it to a different system.

### Problem 1 — Order IDs are not reproducible

Every call to `Order.create()` generates a fresh UUID.  Running the same FIX
file twice produces 1 056 different UUIDs.

**Consequence:** You cannot compare `order_id` fields between the paper result
and the engine result.

**Solution:** Compare at price-level aggregate.  The snapshot API returns
`{price, qty}` pairs, not order IDs.  Two different sets of orders resting at
$149.50 with total visible qty 450 are equivalent for book-state purposes.

### Problem 2 — TIF=DAY orders expire at session end

`DAY` orders live only within the current session.  The engine's scheduler
marks them expired when the session transitions to `POST_TRADING` or `CLOSED`.

If the engine session ends between sending the last order and requesting the
snapshot, all resting `DAY` orders vanish — and the book will appear empty.

**Solution:** The verification engine config starts the engine in `CONTINUOUS`
session state with no scheduled session transitions.  All test orders use
`TIF=DAY` (the default), which in a perpetual `CONTINUOUS` session never
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

**Solution:** The replay client uses a strict synchronous ACK loop.  No new
order is sent until the engine has acknowledged (or timed-out on) the previous
one.  This enforces the same processing sequence as the paper trader, which
calls `book.process()` one order at a time in a tight loop.

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

`data/verify/verify_engine_config.yaml` is a minimal engine configuration that
restricts the run to a controlled environment:

```yaml
gateways:
  alf:
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
- No session schedule — the engine stays in `CONTINUOUS` indefinitely, avoiding
  `TIF=DAY` expiry.



## Running the full suite

```bash
# One-shot end-to-end verification (takes ~10 s on a laptop)
./verify_matching.sh

# Faster smoke test with fewer orders
./verify_matching.sh --count 100

# Regression: fix the seed, run on every commit
./verify_matching.sh --seed 42 --count 1000

# Reuse the existing FIX files to re-test after an engine code change
./verify_matching.sh --skip-gen
```

Expected end-to-end output for a passing run:

```
━━━  STEP 1 — Generate verification dataset (seed=42, count=1000)  ━━━
[GEN] Wrote 56 MM orders  → data/verify/mm_orders.fix
[GEN] Wrote 1000 test orders  → data/verify/test_orders.fix
[GEN] Running paper trade …
[PAPER] Processed 1056 orders (4 skipped) → 490 trades  (9.8 ms)
...
━━━  STEP 2 — Start matching engine  ━━━
[VERIFY] Starting engine with verify_engine_config.yaml …
[VERIFY] Engine PID=84231 is running.

━━━  STEP 3 — Replay orders to engine  ━━━
[REPLAY] Gateway VERIFY01 authenticated.
...
[REPLAY] Saved engine result → data/verify/engine_result.json

━━━  STEP 4 — Shut down engine  ━━━
[VERIFY] Sending SIGINT to engine …

━━━  STEP 5 — Compare paper vs engine  ━━━
  ✓  PASS  — 31 bid level(s), 35 ask level(s), last=149.55
  ✓  PASS  — 44 bid level(s), 23 ask level(s), last=180.02
  ✓  PASS  — 26 bid level(s), 46 ask level(s), last=420.38
  ✓  PASS  — 29 bid level(s), 31 ask level(s), last=160.16

═══  RESULT: PASS  ═══

✓  Verification PASSED — engine output matches paper trade.
```



## Summary

| Problem | Root cause | Solution |
|---------|-----------|----------|
| Non-reproducible order IDs | UUIDs generated at runtime | Compare at price-level aggregate |
| `TIF=DAY` expiry | Scheduler fires session transition | `CONTINUOUS` session, no schedule |
| GTC state leak | Previous run writes to disk | Delete GTC files before each run |
| STOP trigger sequence | `last_price` depends on arrival order | Synchronous send-ACK loop |
| Different `gateway_id` | Engine rejects PAPER01 | Use `VERIFY01` in engine config; ID has no effect on matching |
| Async drain window | Engine still evaluating after last ACK | 0.5 s pause + 5 s snapshot timeout |
| Iceberg refresh position | Hidden reserve replenishment | Aggregate visible qty per price level |



## What next?

- [Order Types](../user-guide/04-order-types.md) — the full mechanics of each order type that the
  generator exercises
- [Messages](../user-guide/09-messages.md) — the ZeroMQ message protocol used by the replay client
- [Architecture](../architecture/01-architecture.md) — how the engine, gateway, and ZMQ bus fit
  together
