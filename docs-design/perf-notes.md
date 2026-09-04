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

- **Fill loop passes the raw enum member instead of `.value` to the JSON
  encoder (2026-09-04).** The two non-aggressor fields in the fill payload
  (`evt.side`, `evt.order_type`) called `.value` on a `str, Enum` member
  before handing it to `dumps`. Both `orjson.dumps` and the stdlib `json`
  fallback already serialize a `str` subclass — which is exactly what a
  `str, Enum` member is — as its string value, so `.value` bought nothing but
  an extra descriptor call. Profiling 30 000 orders through
  `_handle_new_order` showed 75 057 calls to `enum.py:value` at this pair of
  call sites; removing it drops that count to zero with no change to the
  emitted bytes (checked against both encoders).

  This is deliberately narrow. The wider hot path has ~29 similar `dict.get`
  calls per order (`docs-design/EduMatcher-Perf-Analysis.md` §10 item 6), but
  profiling showed those are legitimate per-trade VWAP / trade-id / liquidity
  aggregation, not redundant re-reads — nothing to unpack there. §10 item 7
  (compiling out the `_dbg_count` log guards) was left alone too: it is a
  shared helper with 52 call sites across the file, the measured cost is
  ~1.3% of profiled wall time, and the only way to avoid re-checking
  `log.isEnabledFor` on every call is a cached flag that would go stale the
  moment the log level changes at runtime — not a trade worth making for a
  sub-300 ns/order win.

  **Do not extend this to `Order.to_dict()`'s eight `.value` calls** without
  separately profiling those call sites — `to_dict()` is used far outside the
  order-entry hot path (persistence, snapshots, other message builders), and
  this change was verified only for the two fill-loop sites actually
  profiled here.

## Message generator

- **Nullable enum `from_dict` no longer builds a `typing` union per call
  (2026-09-03).** `msgen/generators/python.py::_narrow` emitted
  `cast(Alias | None, None if ... else str(...))` for a nullable enum field.
  `cast`'s first argument is an ordinary expression, not an annotation, so
  `from __future__ import annotations` does not defer it: `Alias | None` was
  rebuilt and hashed against `typing._tp_cache` **on every call**, for a
  function that returns its second argument unchanged.

  `_narrow_nullable` now casts inside the conditional, so the target is a bare
  module-level alias:

  ```python
  None if p.get("smp_action") is None else cast(OrderNewSmpAction, str(...))
  ```

  Measured on `OrderNew.from_dict`, 200 000 iterations: **5 888 -> 4 306 ns,
  -1 581 ns (27%)**, and the `typing.__hash__` / `_tp_cache` lines leave the
  profile entirely. In isolation the cast expression alone goes from 1 107 ns
  to 58 ns.

  The type is unchanged - the conditional is `None | Alias`, which is what the
  field declares - and both mypy and pyright still reject a bad value for a
  nullable enum, accept `None`, and reveal the precise `Literal[...] | None`
  for the field. That was verified explicitly rather than assumed: the whole
  point of the `cast` is the checking it enables, and a faster form that
  stopped catching a typo would be a bad trade.

  Three families carry nullable enums today - `order` (6 fields), `auction`
  (2) and `circuit_breaker` (3) - and `order.new` is on the order-entry hot
  path, so this lands where it matters. End to end, the ALF ingress leg
  (`_handle_client_line` for a `NEW`) went from a **32.0 us** median to
  **28.9 us**, four runs of 50 000 iterations each, spread under 3%. The leg
  saving is larger than the isolated 1.58 us; the isolated benchmark used a
  12-key payload against the gateway's 22-key one, which is the likeliest
  reason, but the gap is not fully accounted for.

  **Do not "simplify" this back to a single cast around the whole
  conditional.** It reads better and costs a microsecond per call.

## ALF gateway ingress

- **`make_order_new_unchecked` on the single-order path (2026-09-03).**
  `_handle_new_single` built its bus frame with the validating builder, which
  goes dict -> `OrderNew` -> `validate()` -> dict. Measured on one order:
  **7 349 ns against 2 364 ns**. Only **355 ns** of that difference is
  `validate()`; the other **4 630 ns** is the dataclass round trip, which buys
  nothing - the payload arrives as a dict and leaves as a dict.

  The 355 ns is a real safety trade and is only acceptable because every rule
  `validate()` declares is enforced earlier: client-supplied fields per order
  by the gateway's own parsers, and the two config-derived limits once each -
  `symbol` max_len 16 when the engine's snapshot lands, `gateway_id` max_len
  32 at HELLO. `tests/test_alf_gwy_wire_bounds.py` pins the correspondence
  field by field, and its `test_every_validate_rule_is_accounted_for` reads the
  rules out of the generated source so a *new* spec rule fails the build until
  someone classifies it. Without that test this optimisation would rot into a
  defect quietly.

  Other callers of `make_order_new_msg` (console, AI trader, REST, BALF) keep
  the validating builder, as `_unchecked`'s own docstring asks.

- **`os.urandom(16).hex()` for order ids (2026-09-03).** `str(uuid.uuid4())`
  was **2 584 ns**; this is **473 ns**. The entropy is identical - 128 bits
  from the OS CSPRNG - so the collision argument is unchanged, which matters
  because five processes mint order ids with no coordination and several
  stores outlive the process that wrote them. uuid4's extra 2 111 ns is
  entirely `UUID` object construction and the dashed 8-4-4-4-12 formatting,
  and nothing in the system parses an order id back (checked). Shared by
  `Order.create`, `ComboOrder.create` and BALF's `new_engine_order_id` via
  `models/ids.py`.

  A per-gateway counter would be 265 ns but needs a durable run sequence in
  each of those five producers to survive a restart - the machinery `Trade.id`
  needs, and 208 ns does not justify.

  **Combined with the generator fix above, the ALF ingress leg
  (`_handle_client_line` for a `NEW`) went from a 32.3 us median to 17.3 us -
  three runs of 50 000 iterations each, spread under 1%.** That is more than
  the parts sum to, because the unchecked builder skips `OrderNew.from_dict`
  altogether and so subsumes the generator saving on this path.

## Guidance

Macro costs dominate over these micro-opts: JSON per message, publication
fan-out, and O(resting) scans. Optimize those first. Keep code comments for
invariants; put measured nanosecond rationale here.
