# Engine performance notes

This file records the micro-optimizations applied to the hot paths in
`engine/order_book.py` and `engine/main.py`. The rationale lives here (rather
than inline) so the code comments can focus on *invariants*, not bytecode
trivia. Each item was measured; do not extend the set without a profile showing
the target is ≥1% of wall time (review finding P6).

## OrderBook / matching

- **`__slots__` on `_HeapEntry` and `OrderBook`.** `_HeapEntry` is the most
  frequently allocated object in the engine (one per resting order, one per
  stop). `__slots__` removes the per-instance `__dict__`, shrinking memory and
  turning attribute access into a fixed-offset C-struct dereference
  (~0.5–1 µs saved per aggressive order across the sweep).

- **Single timestamp per `process()` call (`now`).** The engine's dispatch loop
  passes one pre-computed timestamp into `process()`, which threads it through
  `Trade.create()`, iceberg re-queue, and stop/trailing-stop conversion. This
  avoids repeated `time.time_ns` syscalls (~0.3–0.5 µs each); an aggressive
  order that triggers stops can otherwise make 2–4 redundant calls. Since
  finding H1, time priority is driven by the arrival sequence, so this
  timestamp is informational.

- **Cached aggressor attributes in `_sweep`.** `side`/`smp_action`/`gateway_id`
  are bound to locals before the sweep loop. Local access is a `LOAD_FAST`
  bytecode (~30 ns) versus `LOAD_ATTR` (~50–70 ns with `__slots__`); over N
  price levels this saves ~0.2–0.8 µs per aggressive order.

## Engine / publication

- **Pre-encoded topic bytes and cached per-gateway topics.** Static topics
  (e.g. `trade.executed`) are encoded once at module load; per-gateway
  ack/fill/cancel topics are cached in `_topic_cache` on first contact to avoid
  re-building f-strings and re-encoding on every message. `trade.executed`'s
  pre-encoded constant moved into the generated binding
  (`models/generated/trade.py`), which pre-encodes it the same way; the
  optimisation is unchanged, only its home.

- **`_publish_trade` costs ~0.6 µs more than it did, deliberately.** The
  function used to build its payload as a dict literal here (0.96 µs/call
  measured over 200 000 iterations with orjson). It now calls the generated
  `make_trade_executed_unchecked` (1.47–1.56 µs), so the field list lives in
  `spec/messages/trade.yaml` instead of being retyped in three places. This is
  the one item on this page that *adds* cost, so the reasoning is recorded in
  full:

    - The alternative was leaving the field list hand-written, which is what
      let `book.{SYMBOL}` gain `tick_decimals` in three surfaces and the C
      clients in none.
    - The **coercion** in the generated builder accounts for ~0.39 µs of the
      0.55. It is kept because dropping it makes
      `make_trade_executed_unchecked(price=100)` put an int on the wire where
      `make_trade_executed` puts a float, and mypy does not catch that — `int`
      is promotable to `float`. A silent wire divergence between two functions
      documented as identical is worth more than 0.39 µs.
    - The `_unchecked` variant exists precisely so this path skips validation;
      the validating `make_trade_executed` measures ~4.8 µs and is used
      everywhere else.
    - **Half the original call was already `orjson`** — 0.51 µs of the 0.96.
      The generated form's irreducible floor is ~1.13 µs, because a shared
      definition is a function call and a copied definition is not.
    - Do not "optimise" this back into a literal without reading
      `docs-design/EduMatcher-Message-Generator.md` **§14**, which decomposes
      the cost and evaluates every remaining optimisation. Two results worth
      knowing before trying: a `__class__` type test instead of a coercion call
      is **slower**, and coercing only the numeric fields would halve the
      overhead to +0.27 µs but weakens `_unchecked`'s byte-identity guarantee to
      typed call sites only. `tests/test_msgen_trade_perf.py` (marker `perf`)
      guards against a reversion to the 4× shape.

- **Pre-built `frozenset` for the fill-status check** avoids allocating a
  temporary tuple on every iteration of the events loop.

- **Monotonic clock on the hot path.** `_handle_new_order` uses `now_ns()`
  (monotonic, finding M9); the raw `time.time_ns` alias `_time_ns` is retained
  only for backward compatibility.

## Guidance

Macro costs dominate over these micro-opts: JSON per message, publication
fan-out, and O(resting) scans. Optimize those first. Keep code comments for
invariants; put measured nanosecond rationale here.
