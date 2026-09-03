Version: 1.0.0

Date: 2026-09-03

Status: Measurement report — findings are reproducible; the headline recommendation is a test fix, not an engine fix

# EduMatcher — Order-Entry Hot Path Performance Analysis

## Table of Contents

1. [Summary](#1-summary)
2. [Scope: what "latency" means here](#2-scope-what-latency-means-here)
3. [Method and the honesty caveat](#3-method-and-the-honesty-caveat)
4. [Finding 1 — the benchmark number is bimodal](#4-finding-1--the-benchmark-number-is-bimodal)
5. [Finding 2 — a real regression, but a modest one](#5-finding-2--a-real-regression-but-a-modest-one)
6. [The latency budget, ingress to book](#6-the-latency-budget-ingress-to-book)
7. [Where the gateway leg goes](#7-where-the-gateway-leg-goes)
8. [Where the engine leg goes](#8-where-the-engine-leg-goes)
9. [What the recent changes actually cost](#9-what-the-recent-changes-actually-cost)
10. [Recommendations](#10-recommendations)
11. [Fixing the benchmark itself](#11-fixing-the-benchmark-itself)
12. [Reproducing these measurements](#12-reproducing-these-measurements)

---

## 1. Summary

Three things are true at once, and they have been conflated:

1. **The 10 000 TPS figure is not a stable measurement of anything.** In the
   exact configuration `make test-perf` uses — every published frame retained
   by the mock socket, garbage collection enabled — throughput on one machine,
   one commit, one workload varied between **12 361 and 35 377 TPS across
   three consecutive repeats**. Disable *either* the frame retention *or* the
   GC and the same workload is stable at 42 000–45 000 TPS with a spread under
   6%. The benchmark is measuring its own heap as much as the engine.

2. **There is a real regression, and it is about 20–25%, not 5×.** The
   2026-07-05 tree measures 43 500–45 300 TPS on the same host where HEAD
   measures 34 500–36 000. That is worth recovering, and §7–§8 say where it
   is, but it does not explain a fall from 50 000 to 10 000.

3. **The benchmark does not measure the leg you asked about.** `test_perf.py`
   times `Engine._handle_new_order` only. Measured ingress-to-book, the ALF
   gateway costs **31.8 µs** against the engine's **22 µs** — the untimed leg
   is the larger one.

**The single most valuable change is to §11's benchmark fix**, because until
the number is stable, no optimisation can be shown to have worked. After that,
§10 lists roughly **13 µs/order** of measured recovery against a 54 µs budget —
and about **10 µs of that is in the gateway leg**, the one no test currently
times.

> **This report could not reproduce 10 000 TPS.** On the sandbox used here,
> HEAD runs the unmodified `make test-perf` workload at 33 000–37 000 TPS.
> The Intel Mac's 10 000 corresponds exactly to the *bad mode* of the bimodal
> behaviour in Finding 1 — which is the most likely explanation, but it is a
> hypothesis this environment cannot confirm. §12 gives the commands to settle
> it on the machine that shows the problem.

---

## 2. Scope: what "latency" means here

The requested measurement is **from an order arriving at the ALF gateway until
it is resting in the book or matched**. That path is:

```
client TCP line
   │
   ▼  ALF gateway process ─────────────────────────── measured: 31.8 µs median
   ├─ parse_alf_line                                  3.4 µs
   ├─ field validation, tick check, tag validation
   ├─ Order.create (incl. uuid4)                      5.1 µs
   ├─ Order.to_dict                                   1.8 µs
   └─ make_order_new  → validate → to_dict → orjson   8.7 µs
   │
   ▼  ZMQ PUSH → PULL ───────────────────────── not measured here; ~10–30 µs
   │              (loopback, per test_perf.py's own header)
   │
   ▼  Engine process ──────────────────────────────── measured: ~22 µs
   ├─ Order.from_dict                                 1.0 µs
   ├─ gateway/symbol/session/halt/collar gates
   ├─ _validate_new_order
   ├─ book.process → _sweep / _rest                   matching
   └─ publish ack + fills + trade.executed            3 orjson frames
   │
   ▼  order is resting or matched
```

**In-process total ≈ 54 µs, plus one wire hop.** At 54 µs the ceiling is
~18 500 orders/s single-threaded end-to-end, or ~45 000/s if you count only
the engine as the current benchmark does.

`test_perf.py` covers only the third box. Its own module docstring says so, and
that is a reasonable scope for engine optimisation work — but it means the
number has never included the leg that turns out to be larger.

---

## 3. Method and the honesty caveat

**Environment.** All numbers here come from a Linux cloud container with
Python 3.13, not from the Intel Mac that shows the problem. Two consequences:

- **Absolute throughput does not transfer.** This host runs HEAD at 33 000–
  37 000 TPS where the Intel Mac reports 10 000.
- **Ratios, shares and per-call costs do transfer**, because they are
  properties of the code, not the clock. Every recommendation in §10 is stated
  as a ratio or a per-call cost for that reason.

**Noise.** The host is a shared vCPU and single runs are unreliable — one early
single run of HEAD produced 10 158 TPS and a later run of the same commit
produced 37 322. Every headline number below is the **spread across at least
three repeats**, and the internally-controlled comparisons (same process, same
run, one variable changed) are the ones load-bearing for the conclusions.

**A caveat on the historical comparison.** The 2026-07-05 tree generates
**7 421 trades** on the benchmark workload where HEAD generates **4 945**. The
workloads are therefore not identical, and the July tree was doing *more*
matching work per order, which makes the measured regression a lower bound
rather than an exact figure. The cause is a change in `_seed_liquidity`'s
resulting book, not in matching semantics — self-match prevention was checked
and resolves to `NONE` on this workload, so it is not a factor. Worth
confirming before treating 20–25% as precise.

---

## 4. Finding 1 — the benchmark number is bimodal

This is the most important result in the report, and it is an
internally-controlled experiment: one process, one workload of 20 000 orders,
one variable changed at a time, repeated three times.

| Configuration | run 1 | run 2 | run 3 | spread |
|---|---:|---:|---:|---:|
| **Retain frames + GC on** — *what `make test-perf` does* | 32.1 µs | **80.9 µs** | 28.3 µs | **2.9×** |
| Drain publisher, GC on | 23.5 µs | 23.3 µs | 24.5 µs | 1.05× |
| Retain frames, GC off | 22.4 µs | 22.4 µs | 23.6 µs | 1.05× |
| Drain publisher, GC off | 22.1 µs | 22.1 µs | 23.4 µs | 1.06× |

*(µs per order; 80.9 µs = 12 361 TPS, 22.1 µs = 45 269 TPS.)*

**Only the benchmark's own configuration is unstable.** Removing either half
of it — the retention or the GC — collapses the variance to nothing and lands
at a consistent 22–24 µs/order.

### Why

`_DummySocket.send_multipart` is a list append, and the list is never drained:

```python
@dataclass
class _DummySocket:
    sent: list[list[bytes]] = field(default_factory=list)

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)
```

Over a 10 000-order run the engine publishes ~2.5 messages per order, so the
harness accumulates **25 000 frames** — 25 000 lists, each holding two `bytes`
objects, all permanently reachable. A real ZMQ socket hands the frames to the
transport and forgets them.

Those objects survive every gen-0 collection, get promoted, and make each
subsequent collection more expensive. Whether the run lands in the fast or the
slow mode depends on **where in the timed section a generation-2 collection
falls** — which is why the same code on the same machine gives 12 361 or
35 377 with nothing changed.

Tracking cost against book depth in a single run shows the transition
directly:

| Orders processed | Retained frames | µs/order (harness retains) | µs/order (publisher drains) |
|---:|---:|---:|---:|
| 0–5 000 | 12 437 | 30.3 | 21.8 |
| 5 000–10 000 | 24 859 | 36.0 | 21.9 |
| 10 000–15 000 | 37 410 | **111.4** | 23.5 |
| 15 000–20 000 | 49 895 | **125.0** | 23.7 |
| 20 000–25 000 | 62 386 | **121.8** | 24.8 |
| 25 000–30 000 | 74 988 | **131.1** | 25.7 |
| 30 000–35 000 | 87 548 | **111.6** | 26.5 |
| 35 000–40 000 | 100 000 | **108.5** | 22.3 |

With the publisher draining, cost is **flat across the whole run** while the
book grows to 20 000 resting orders — so the matching engine itself has no
depth-related scaling problem in this range. With frames retained, cost steps
up 4× and stays there.

**This does not mean the engine has no GC cost in production.** It means the
benchmark adds a large one that production does not have, and that the added
cost is what makes the number jump around.

---

## 5. Finding 2 — a real regression, but a modest one

Same host, same test, five repeats each:

| Tree | Runs (TPS) | Representative |
|---|---|---:|
| 2026-07-05 (`9ac2486d`) | 43 485, 45 284, 44 974, 18 347*, 35 828 | **≈ 45 000** |
| HEAD (`a1c14cb6`) | 34 576, 34 784, 36 037, 35 117, 35 909 | **≈ 35 000** |

\* the 18 347 is the bimodal collapse of Finding 1, not a separate effect.

**≈ 20–25% slower**, subject to §3's caveat that the July tree was doing more
matching per order. A coarse walk of the intervening commits (best-of-three at
each point) shows a gradual slide rather than one bad commit — consistent with
accumulated feature work in `_handle_new_order`, which grew from 424 to 473
lines while `engine/main.py` as a whole went from 4 068 to 5 889 lines.

There is **no cliff attributable to a single change**, and in particular the
final four commits — the reject-code, cancel-reason and tick-validation work —
measure 37 227 / 37 268 / 36 761 / 35 444 TPS, i.e. flat within noise. §9
confirms that from the other direction by pricing those changes individually.

---

## 6. The latency budget, ingress to book

Median of 50 000 iterations each, warm.

| Stage | Cost | Share of in-process path |
|---|---:|---:|
| ALF gateway: `_handle_client_line` for a `NEW` | **31.8 µs** (p90 40.3) | 59% |
| ZMQ PUSH→PULL hop | ~10–30 µs (not measured here) | — |
| Engine: `_handle_new_order` to published ack | **22.1 µs** | 41% |
| **In-process total** | **≈ 54 µs** | 100% |

> **After items 3, 4 and 5 (2026-09-03): the gateway leg is 17.3 µs**, p90
> 21, three runs of 50 000 iterations each with a spread under 1%. The
> in-process total is **≈ 39 µs**, and the gateway is no longer the larger
> leg. The engine leg is unchanged, as expected — none of the three changes
> touches it.
>
> The 15 µs saved exceeds the 8.7 µs the three items sum to individually,
> because they overlap: the unchecked builder skips `OrderNew.from_dict`
> entirely, so item 3's saving on this path is subsumed by item 4's rather
> than adding to it. Do not read the individual figures as a decomposition of
> the 15.

The asymmetry is the headline: **the gateway costs more than the engine**, and
no existing test measures it. Optimisation attention has gone to the engine
because that is what `test_perf.py` reports.

---

## 7. Where the gateway leg goes

Profile shares over 20 000 `NEW` lines, plus isolated per-call costs measured
separately (profiler overhead inflates absolutes ~2–3×, so shares and isolated
costs are quoted rather than profiled absolutes).

| Component | Isolated cost | Note |
|---|---:|---|
| `make_order_new` — **validating** builder | **8 723 ns** | `make_order_new_unchecked` is **2 324 ns** |
| `Order.create` | 5 099 ns | of which `uuid.uuid4()` is **2 942 ns** |
| `parse_alf_line` | 3 351 ns | 19 `.strip()` and 13 `.upper()` calls per line |
| `Order.to_dict` | 1 833 ns | |
| `cast(X \| None, …)` in generated `from_dict` | **1 107 ns** | hoisted alias: **58 ns**; no cast: 35 ns |
| `to_ticks_exact` | 338 ns | `to_ticks` was 239 ns — the tick check costs 99 ns |

### The three findings worth acting on

**a. The gateway validates twice and serialises three times.** The path is
`Order.create` → `Order.to_dict()` → `OrderNew.from_dict()` → `validate()` →
`OrderNew.to_dict()` → `orjson.dumps()`. The order is materialised as a dict
three times and validated by the generated builder after the gateway has
already validated every field itself (`_parse_side`, `_parse_order_type`,
`_required_str`, `_ticks`, `_optional_tag`) — and before the engine validates
it again in `_validate_new_order`. Switching this one call site to
`make_order_new_unchecked` recovers **6.4 µs/order, 20% of the gateway leg**.

**b. A `typing` union is constructed at runtime, once per order.** The
generated `from_dict` contains:

```python
smp_action=cast(
    OrderNewSmpAction | None,
    None if p.get("smp_action") is None else str(p["smp_action"]),
),
```

`from __future__ import annotations` defers *annotations*, not *expressions* —
and `cast()`'s first argument is an ordinary expression. So `Literal[...] |
None` is rebuilt and hashed against `typing._tp_cache` on **every call**, at
**1 107 ns**, for a function that is a no-op returning its second argument.
The profile shows exactly one `typing.__hash__` per `from_dict` call,
confirming it. Hoisting the union to a module-level alias takes it to 58 ns.

This is pure waste with no behavioural effect, it is a generator-template
change so it is fixed everywhere at once, and it costs ~1 µs on **both** legs
(the engine's `Order.from_dict` is hand-written and unaffected, but every
generated `from_dict` on any path pays it).

> **Fixed 2026-09-03.** `_narrow_nullable` in
> `msgen/generators/python.py` now casts inside the conditional, so the target
> is a bare module-level alias:
>
> ```python
> None if p.get("smp_action") is None else cast(OrderNewSmpAction, str(...))
> ```
>
> `OrderNew.from_dict` measured over 200 000 iterations: **5 888 -> 4 306 ns,
> a 1 581 ns (27%) saving** - larger than the 1 107 ns predicted here, because
> the union expression also dragged in `_tp_cache`'s lookup machinery. The
> `typing` lines are gone from the profile entirely.
>
> Type precision is unchanged, and that was checked rather than assumed: mypy
> and pyright both still reject a bad value for a nullable enum, accept
> `None`, and reveal `Literal[...] | None` for the field. Regenerating touched
> `order.py`, `auction.py` and `circuit_breaker.py` - the three families with
> nullable enums - and `pm-msgen check` confirms the output still matches the
> spec.
>
> **On the full leg**, §6's ALF ingress measurement improves from a **32.0 us**
> median to **28.9 us** - four runs of 50 000 iterations each, spread under 3%.
> That is more than the isolated 1.58 us and the difference is not fully
> accounted for; the isolated benchmark used a smaller payload than the
> gateway's, which is the likeliest reason. Treat 1.58 us as the number that is
> firmly attributed and ~3 us as what the leg actually gained.

**c. `uuid4()` is 58% of `Order.create`.** 2 942 ns for an order id. `uuid4()`
draws from the OS CSPRNG; an exchange order id needs uniqueness, not
unpredictability.

---

## 8. Where the engine leg goes

Profile of 20 000 orders with the publisher draining, so GC noise does not
mask the real distribution. Shares of total profiled time:

| Component | Share | Calls per order |
|---|---:|---:|
| `_handle_new_order` — the function's own bytecode | **28%** | 1 |
| `dict.get` | 7.5% | **28.8** |
| `Order.from_dict` | 7.2% | 1 |
| `_apply_fill` | 3.4% | 0.5 |
| `_update_position` | 3.2% | 1 |
| `_publish_trade` | 2.9% | 0.5 |
| `from_ticks` | 2.8% | 2.5 |
| `_order_fill_prices` | 2.8% | 1 |
| `_sweep` | 2.3% | 1 |
| `_dbg_count` | 2.3% | **4** |
| `orjson.dumps` | 2.2% | 2.5 |
| `enum.__get__` (`.value` descriptor) | 1.9% | 3.5 |
| `logging.isEnabledFor` | 1.4% | **5.5** |

**No single hotspot dominates.** The largest line is `_handle_new_order`'s own
bytecode at 28% — a 473-line function executing a long sequence of gates
(gateway status, symbol allowlist, validation, session, halt, collar, matching
phase, SMP resolution) on every order, most of which do not apply to most
orders. That is what "more logic in the hot path" looks like in a profile: not
one expensive call, but a hundred cheap ones.

The per-order call counts are the actionable part:

- **28.8 `dict.get` calls per order.** The payload dict is re-interrogated
  field by field in several places rather than unpacked once.
- **4 `_dbg_count` calls per order** — a counter increment guarded by a flag,
  on a path that runs 45 000 times a second.
- **5.5 `isEnabledFor` calls per order** at 116 ns each — the logging guards
  themselves, before any message is formatted.
- **3.5 enum `.value` accesses** at 227 ns each; `.value` on a `str, Enum` is a
  descriptor call, not an attribute load.

None of these is individually significant. Together they are roughly
**3–4 µs/order, 15% of the engine leg**, and they are the recurring cost of
adding "just one more check" to a hot function.

---

## 9. What the recent changes actually cost

The features added over the measurement window were priced individually, to
check whether any of them is the culprit. None is:

| Change | Before | After | Delta | Where |
|---|---:|---:|---:|---|
| Durable trade id (`run_seq-counter`) | 120 ns | 431 ns | **+311 ns** | per *trade*, not per order |
| Tick validation (`to_ticks_exact`) | 239 ns | 338 ns | **+99 ns** | gateway only, per price |
| `cancel_reason` on `order.cancelled` | — | ~0 | **0** | cancel path only |
| Reject funnel + `reject_code` | — | ~0 | **0** | reject path only |
| `client_tag` resolver on lifecycle builders | — | ~100 ns | **+100 ns** | per ack |

Total on the common path: **well under 1 µs/order**, against a 54 µs budget.
The recent work is not the regression, and the commit-by-commit walk in §5
agrees. The cost is spread across two months of accumulated gates in
`_handle_new_order`, not concentrated anywhere.

---

## 10. Recommendations

Ranked by measured benefit against risk. Items 1 and 2 are prerequisites for
trusting anything that follows.

| # | Change | Measured win | Risk | Notes |
|---|---|---:|---|---|
| 1 | **Fix the benchmark** (§11) | Removes a 2.9× measurement artefact | None | Do first; nothing else is verifiable until the number is stable |
| 2 | **Extend the benchmark to the gateway leg** | — | None | 59% of the path is currently untimed |
| 3 | ~~Hoist the `X \| None` union out of generated `cast()`~~ | **DONE** — measured **1.58 µs** per generated `from_dict` | — | Fixed 2026-09-03; see below and `perf-notes.md` |
| 4 | ~~Gateway uses `make_order_new_unchecked`~~ | **DONE** — 4.99 µs/order, of which only 355 ns was validation | — | Done 2026-09-03 with the correspondence test §10 asked for |
| 5 | ~~Replace `uuid4()` for order ids~~ | **DONE** — 2.11 µs/order | — | `os.urandom(16).hex()`; no durable state needed after all |
| 6 | **Unpack the payload dict once in `_handle_new_order`** | ~1–2 µs/order | Low | 28.8 `dict.get` calls today |
| 7 | **Compile out `_dbg_count` and the log guards when disabled** | ~1 µs/order | Low | 9.5 guard calls per order |
| 8 | **Cache `.value` on hot enums** | ~0.8 µs/order | Low | 3.5 descriptor calls per order |
| 9 | **Split `_handle_new_order`'s gates** | not yet measured | Medium | 28% of engine time is this function's own bytecode |
| 10 | **Tune GC thresholds in the engine process** | ~5% in production, more under load | Low | `gc.set_threshold(50_000, 50, 50)` measured 13 669 vs 7 257 TPS in the *retaining* configuration |

### On item 4 — is skipping validation safe here?

`make_order_new_unchecked` exists for exactly this purpose, and
`docs-design/perf-notes.md` already documents that reasoning for
`make_trade_executed_unchecked`. The gateway has validated side, order type,
TIF, quantity, symbol, tag length and tick alignment before it builds the
message, and the engine re-validates on receipt. What the generated
`validate()` adds on top is `max_len` checks on strings the gateway has already
bounded.

**But it is a real reduction in defence-in-depth on the one path where a
malformed message would reach the bus.** The honest version of this
recommendation is: switch it, and add a test asserting that every field
`validate()` would have checked is checked by the gateway first — otherwise
this trades 6.4 µs for a class of bug that only appears in production.

> **Done 2026-09-03, and the framing above was wrong in a way worth
> recording.** Decomposing the builders shows the cost is not mostly
> validation:
>
> | | ns |
> |---|---:|
> | `make_order_new` (validating) | 7 349 |
> | `make_order_new_unchecked` | 2 364 |
> | *of the 4 985 difference:* `validate()` | **355** |
> | *of the 4 985 difference:* dataclass round trip | **4 630** |
>
> `make_order_new` goes dict → `OrderNew` → `validate()` → dict. The payload
> arrives as a dict and leaves as one; the object in the middle exists only to
> be validated. So 93% of the saving costs nothing in safety, and the headline
> for this item should have been "serialises three times", not "validates
> twice".
>
> The 355 ns still had to be earned. Two of `validate()`'s sixteen rules —
> `symbol` max_len 16 and `gateway_id` max_len 32 — had no gateway equivalent,
> and neither is checked by `pm-cverifier` either, so `validate()` was the only
> thing catching a misconfiguration. Both are config-derived, so they moved to
> where that belongs: symbols are bounded when the engine's snapshot lands,
> gateway ids at `HELLO`. Both are O(1) per connection rather than per order.
>
> `tests/test_alf_gwy_wire_bounds.py` covers all sixteen rules, asserts the two
> builders emit byte-identical frames, and — the part that keeps this honest —
> reads the rules out of the generated source so a rule added to the spec fails
> the build until someone classifies it.

### On item 5 — what replaces `uuid4()`?

The order id needs to be unique across gateways and restarts, and it is used as
a dict key and a wire string. It does **not** need to be unpredictable. The
pattern already adopted for `Trade.id` in the durable-trade-id work applies
directly: a per-gateway prefix plus a monotonic counter, formatted once.
Measured at 431 ns against uuid4's 2 942 ns, that is ~2.5 µs/order.

Two constraints, both already solved for trades: the prefix must be durable
across restarts (`persistence.load_and_bump_run_seq` is the existing
primitive), and the format must stay fixed-width so lexicographic order matches
chronological order. Note the id is currently a UUID *string* in several
stores; changing its shape is a wire-visible change and belongs in the same
category as the trade-id change, with the same `grep` for parsers.

> **Done 2026-09-03 — and not the way this section proposed.** The counter
> scheme above is the wrong trade. Measured:
>
> | | ns |
> |---|---:|
> | `str(uuid.uuid4())` — before | 2 584 |
> | `uuid.uuid4().hex` | 2 155 |
> | **`os.urandom(16).hex()` — chosen** | **473** |
> | `f"{prefix}-{next(counter):012d}"` | 265 |
>
> uuid4's cost is almost all packaging: it draws 16 random bytes, then builds a
> `UUID` object and formats the dashed 8-4-4-4-12 shape. Taking the bytes
> directly keeps **the entropy identical** — 128 bits of OS CSPRNG — so every
> uniqueness argument for uuid4 still holds, unchanged, with no durable state
> and no coordination.
>
> That matters more than the extra 208 ns the counter would have saved. Order
> ids are minted independently by five processes and must not collide across a
> restart, so a counter needs a durable run sequence in each of them. Paying
> `Trade.id`'s machinery five times over for 208 ns is a bad trade, and the
> recommendation above should not have been written without measuring
> `os.urandom` first.
>
> The id is 32 hex characters against uuid4's 36 — both inside the spec's
> 64-char `max_len`, and the two forms coexist safely in stored data because
> nothing parses one (verified by grep before changing it).

### What is not worth doing

- **`orjson`** is 2.2% of engine time at 277 ns/call on these payloads.
  It is not the problem, and the profiler's first-pass attribution of 45% to
  it was an artefact of GC pauses landing inside the call.
- **The matching path** (`_sweep`, `_apply_fill`, `_rest`) is ~9% combined and
  showed no depth-related scaling across 20 000 resting orders.
- **The micro-optimisations already recorded in `perf-notes.md`** are still
  correct and should not be revisited; they are not where the time went.

---

## 11. Fixing the benchmark itself

Three changes, in order of importance. None of them changes the engine.

**1. Drain the mock publisher.** A real socket does not retain frames:

```python
@dataclass
class _DummySocket:
    #: Retain frames only for the tests that assert on published output.
    #: The throughput test needs the count, not the frames, and retaining
    #: 25 000 of them is what makes its result bimodal.
    keep: bool = True
    sent: list[list[bytes]] = field(default_factory=list)
    count: int = 0

    def send_multipart(self, frames: list[bytes]) -> None:
        self.count += 1
        if self.keep:
            self.sent.append(frames)
```

`_build_engine` then takes `keep=False` for the throughput test and leaves the
default for everything else.

The latency and assertion tests need the frames; the throughput test needs only
a count. Retaining 25 000 frames to count them is what makes the number
bimodal.

**2. Report a distribution, not a single number.** The throughput test should
run the workload three times and report min/median/max, and **fail if the
spread exceeds a threshold** — a benchmark whose own variance is 2.9× cannot
detect a 20% regression. This is the same flakiness-gate reasoning applied in
`docs-design/EduMatcher-System-Trading-Verification.md` §16.

**3. Isolate the throughput test from the latency tests.** They currently share
a process, so the throughput test starts on a heap the latency tests loaded.
Either run it in its own process (`pytest-forked`, or a `subprocess`), or call
`gc.collect()` and rebuild the engine between test classes.

Optionally, **record the GC statistics** for the timed section
(`gc.get_stats()` before and after) and print collections per generation
alongside the TPS. When the number moves, that line will usually say why.

---

## 12. Reproducing these measurements

On the machine that shows the problem — the numbers here cannot settle it.

**Confirm or refute the bimodal hypothesis first.** If this shows a wide
spread, the 10 000 TPS is the artefact of §4 and not an engine property:

```bash
for i in 1 2 3 4 5; do
  poetry run pytest tests/test_perf.py::TestThroughput -q -s -m perf -p no:cov \
    | grep "TPS (orders"
done
```

**Then isolate the two amplifiers.** Both are one-line experiments:

```bash
# (a) GC out of the picture — add to the top of tests/test_perf.py, temporarily
#     import gc; gc.disable()
poetry run pytest tests/test_perf.py::TestThroughput -q -s -m perf -p no:cov

# (b) publisher draining — temporarily make _DummySocket.send_multipart a no-op
#     def send_multipart(self, frames): pass
poetry run pytest tests/test_perf.py::TestThroughput -q -s -m perf -p no:cov
```

Run each five times, not once. If either restores 40 000+ *and* removes the
spread, the benchmark is the problem.

If (a) or (b) alone restores 40 000+, the engine is fine and §11 is the whole
fix. If neither does, the regression is machine-specific and the next step is
a bisect using the same commits as §5:

```bash
git bisect start HEAD 9ac2486d
git bisect run sh -c 'poetry run pytest tests/test_perf.py::TestThroughput \
  -q -s -m perf -p no:cov | grep -q "TPS (orders/sec)   :     [3-9][0-9],"'
```

**The gateway leg** — the part no current test covers — is measured by driving
`AlfGateway._handle_client_line` directly with a socketpair-backed
`ClientSession`; §6's 31.8 µs came from 50 000 iterations of a single `NEW`
line with the rate limiter opened up. That harness is worth adding to
`test_perf.py` as a second latency class regardless of what the bisect finds.

---

## Appendix — measurement provenance

Every number in this document came from one of five scripts run against the
tree at `a1c14cb6`, on Python 3.13 in a Linux container:

| § | What was measured | How |
|---|---|---|
| 4 | Retention × GC matrix | 20 000-order workload, 4 configurations, 3 repeats, single process |
| 4 | Cost against book depth | 40 000 orders in 8 windows of 5 000, retained vs drained |
| 5 | Historical trees | `git archive` of 7 commits, same venv, best-of-3 and 5-run spreads |
| 6, 7 | Gateway leg | 50 000 `_handle_client_line` iterations, median and p90; cProfile for shares |
| 7, 9 | Per-call costs | 200 000–300 000 iterations each, warm, isolated |
| 8 | Engine shares | cProfile over 20 000 orders with the publisher drained |

Profiled absolutes are inflated 2–3× by cProfile and are quoted only as
shares. Wall-clock figures come from unprofiled runs.
