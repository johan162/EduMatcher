Version: 1.0.0

Date: 2026-11-21

Status: WP-HP01–03 implemented 2026-11-21 (uncommitted); the live sim-day
check of WP-HP03 is pending — see §6

# EduMatcher — AI traders take part in circuit-breaker reopening auctions

## 1. Problem

In the 2026-11-21 sim run (`~/.edumatcher-sim/data/audit`), every
circuit-breaker reopening auction was a no-cross:

| `auction.result` reason | Crossed | No cross |
|---|---|---|
| `SCHEDULED` (opening auction) | 294 | 6 |
| `REOPEN` (after a CB halt) | **0** | **300** |

All 303 halts were L1 (≥ 4 % from the 5-minute average, 3-minute halt); 185
fell in the first hour after the open. `circuit_breaker.extend` was published
zero times all day.

The engine is correct. A halt is the reopening auction's call phase: LIMIT and
ICEBERG orders are accepted and rest unmatched (`engine/main.py` step [7]),
MARKET/IOC/FOK are rejected, and `_flush_circuit_breakers` uncrosses at the
end. The book that existed when the symbol halted was an uncrossed continuous
book, so the reopen finds a cross only if new interest arrives during the halt,
and none does. In MAR's halt from 11:41:25 to 11:44:37 the engine received one
cancel and no new orders.

Both order sources in the sim stay out of a halted symbol on purpose:

- **AI traders.** `session_policy.order_allowed(..., halted=True)` returns
  `False` for everything, `strategies._priced` skips halted symbols, and the
  combo, basket and protection paths each check `st.halted`.
- **MM bot.** `_handle_circuit_breaker_halt` pulls the quote and goes
  `PAUSED`. The engine also rejects quotes on a halted symbol
  (`engine/main.py` ~4306), so the MM bot cannot take part without a new
  order path.

Consequences:

1. The terminal-gui and dash-gui show hundreds of meaningless `(no cross)`
   reopenings.
2. Reopening price discovery, the ACE corridor and its extension ladder, and
   the forensics breaker check's corridor assertions are never exercised by
   the sim. In the sim, a halt is just a 3-minute gap in trading.

## 2. Goal

During a circuit-breaker halt, the AI traders behave as they already do in a
scheduled call phase: with probability `auction_participation` a decision on
the halted symbol sends a resting LIMIT that straddles the reference price, so
that buyers and sellers overlap at the reopen.

**Success criteria** (measured on a full sim day, WP-HP03):

- A majority of `REOPEN` auctions cross (`eq_price` not null). Expected: most
  of them; 30 orders per symbol per 3 minutes is the measured midday rate.
- No CB-halt rejects of AI-trader orders (`CIRCUIT_BREAKER_ACTIVE`) beyond
  races at the halt's first instant.
- Breaker checks in `pm-sim-forensics` (`checks/breakers.py`) report no new
  findings now that reopens print. They verify each reopen against the
  corridor.
- `circuit_breaker.extend` may now occur. It is observed and reported, not
  required.

## 3. Open questions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Do agents also take part in an **operator** halt (`halt_source: ADMIN`)? | **No.** An operator halt is discretionary and only ends when the operator says so; an instructor halting a symbol for a lesson expects it quiet. The engine's reject codes already draw this line (CB vs ADMIN). |
| Q2 | Reuse `auction_participation` or add a separate `halt_participation` preset knob? | **Reuse.** A halt *is* a reopening auction; a second knob is configurability nobody asked for. Revisit only if WP-HP03 shows the rate needs separate tuning. |

Both recommendations accepted by Johan 2026-11-21.

## 4. Design

A symbol in a CB halt gets an **effective phase** `HALTED` for order entry,
whatever the session phase is. `HALTED` is a call phase.

- **`session_policy`**: `_ALLOWED["HALTED"] = (_RESTING, {DAY, GTC})`. That
  mirrors the engine, which accepts LIMIT/ICEBERG and rejects
  MARKET/IOC/FOK, with no ATO/ATC. `is_call_phase("HALTED")` is true and
  `auction_tif("HALTED")` is `None`, so the order uses the preset's `tif`
  (DAY by default). `symbol_phase(phase, halted, halt_source)` returns
  `HALTED` for a CB halt in any session phase except `CLOSED`.
  `order_allowed(phase, …, halted=True)` refuses everything unless `phase`
  is `HALTED`. Any path that does not ask for the symbol's phase keeps
  sending nothing for a halted symbol: TWAP slices, protection, and any
  ADMIN halt.
- **`MarketState`**: keeps `halt_source` next to `halted`, from the
  `circuit_breaker.halt.*` payload and from `halt_status` entries, which already
  carry `halt_source`. `worker.handle_market` passes the payload through
  instead of `True`/`False`.
- **Decisions**: `strategies._priced` stops excluding CB-halted symbols. In
  `Agent._decide`, a CB-halted symbol is handed to the executor with phase
  `HALTED`. That takes the existing `orders_for` → `auction_participation` →
  `_auction_order` path, which straddles `st.reference(auction=True)`. No
  indicative is published during a CB halt in continuous trading
  (`_flush_auction_indicative` skips halted symbols), so the reference falls
  to the halted book's mid, then the last trade, i.e. the trigger price. The
  existing collar clamp in `_finish`, the dynamic band around the last trade,
  keeps prices acceptable. Prices are deliberately **not** clamped to the ACE
  corridor, so a book that wants to reopen outside it can drive an extension.
- **Housekeeping**: the stale-order sweep skips orders on CB-halted symbols,
  as it already does in call phases. They wait for the uncross, and a
  crossed halt book's touch is no market price. Orders left after the reopen
  are swept normally.
- **Unchanged**: combos and baskets (continuous only), protection stops
  (continuous only, halted skipped), and the MM bot. A TWAP slice that falls
  due during a halt is consumed and not sent, as before. Baskets now draw
  only non-halted symbols (`_combinable`); before, `_priced` excluded every
  halted symbol for them.

## 5. Work packages

Run them in order. Each one should pass black, flake8, mypy, pyright and
pytest (`-n logical`) before Johan commits it.

### WP-HP01 — Halt source in market state; `HALTED` order policy

Test first:

- `tests/test_ai_trader_execution.py`: replace
  `test_halted_blocks_everything` with tests showing that a CB halt allows
  LIMIT and ICEBERG with DAY/GTC, refuses MARKET/IOC/FOK, STOP/STOP_LIMIT,
  ATO and ATC, and refuses everything for an ADMIN halt and in `CLOSED`.
- `tests/test_ai_trader_market_state.py`: `on_halt` records `halt_source`
  from the payload; `on_halt_status` records it per entry; resume clears both.
- `tests/test_ai_trader_worker.py`: a `circuit_breaker.halt.X` frame with
  `halt_source: ADMIN` leaves `X` halted with source ADMIN.

Then change `session_policy.py`, `market_state.py` (`halt_source` field,
`on_halt(symbol, payload | None)`), and `worker.py`. Update the
`session_policy` module docstring.

### WP-HP02 — Decisions on a halted symbol

Test first:

- `tests/test_ai_trader_strategies.py`: rework
  `test_unpriced_and_halted_symbols_are_skipped` so that a CB-halted priced
  symbol can be chosen and an ADMIN-halted one cannot.
- `tests/test_ai_trader_execution.py`: `test_halted_no_order` becomes two
  tests. With phase `HALTED`, the order is a LIMIT straddling the reference,
  with the preset `tif`, clamped to the collar and sent with probability
  `auction_participation` (0.0 → never, 1.0 → always). For a `sweep` style it
  is still a LIMIT, never MARKET/IOC/FOK.
- `tests/test_ai_trader_agent.py`: an agent with `auction_participation: 1.0`
  in CONTINUOUS, whose only symbol is CB-halted, emits a resting LIMIT/DAY
  on it. The same agent sends no combo, basket leg or protection stop on it.
  A resting order on a CB-halted symbol survives a housekeeping pass that
  would otherwise sweep it as stale.

Then change `strategies._priced`, `Agent._decide` (pass the effective phase
`HALTED` to `orders_for` and `_combo`, which already refuse non-continuous
phases), and `Agent._housekeeping` (exclude CB-halted symbols from
`orders.stale`).

### WP-HP03 — Docs and live verification

Docs:

- `docs/books/participant-guide/part-4-automated-trading/020-how-the-bots-decide.md`,
  the call-phase paragraph: a circuit-breaker halt counts as a call phase. The
  trader sends a straddling LIMIT (preset TIF) with probability
  `auction_participation`. Operator halts are left alone.
- `docs/books/ai-traders/part-2-how-it-works/060-tuning-the-traders.md`:
  `auction_participation` row now also covers CB reopenings.
- Check `docs/books/ai-traders` and the operator guide's risk-controls chapter
  for wording that says the sim's reopenings never cross, or that agents
  avoid halts.

Live verification on a full sim day (rebuild the `edumatcher-ai-sim`
image). Report each item in §6:

1. Count `auction.result` by reason and crossed/no-cross, using the same
   `grep "[auction.result"` over `audit.log` + `audit/*.log` as in §1.
2. Count `circuit_breaker.halt`, `resume` and `extend`, and halts per
   symbol. Watch for halt → reopen → re-halt chains. A reopen print does not
   trigger (`may_trigger=False`), but the next continuous trade is compared
   with a window that now contains it.
3. Count AI-trader rejects by code during halts
   (`CIRCUIT_BREAKER_ACTIVE`, `COLLAR_BREACH`).
4. Run `pm-sim-forensics` and confirm the breaker checks are clean.
5. Look at the terminal-gui Session tab with the reason filter set to Reopen:
   the rows should now show prices.

## 6. Implementation notes and measurements

**WP-HP01** (2026-11-21). `SymbolState.halt_source`; `MarketState.on_halt(symbol,
halted, source)`; the worker passes `halt_source` from the halt payload;
`session_policy.symbol_phase` and the `HALTED` row. Full suite: 15217 passed.

**WP-HP02** (2026-11-21). `strategies._priced` admits CB-halted symbols, and the
new `_combinable` keeps baskets continuous-only. `Agent._decide` uses the
symbol's phase. Housekeeping skips the stale sweep for orders on a symbol in a
halt call (`_in_halt_call`). Tests: `TestCircuitBreakerHalt` in
`test_ai_trader_agent.py`, the halt-call cases in `test_ai_trader_execution.py`,
and the strategy and basket cases. A mutation check that makes `symbol_phase`
never return `HALTED` fails six of them. Full suite: 15231 passed.

**WP-HP03** (2026-11-21). Participant guide ch. 020 (the phase paragraph and the
call-phase paragraph) and the AI-traders tuning table updated; mkdocs builds.
**Live verification not yet run.** It needs the `edumatcher-ai-sim` image
rebuilt and a full sim day. Items 1–5 of WP-HP03 are still open.

**Review fix** (holistic review, 2026-11-21). `MarketState.on_halt_status` only
ever set halts. The engine's `halt_status` reply lists every halted symbol,
but a symbol that resumed while the worker was away (engine restart, lost
session) stayed halted. Before this plan, that only kept agents off the
symbol. With it, a stale CB flag would keep the symbol in a call phase, with
its orders never swept as stale. The reply is now taken as the whole picture
(`test_halt_status_is_the_whole_picture`). The reply and the halt/resume
events share the engine's PUB socket, so their order is kept.

**Noted, not changed.** Book snapshots of a halted book feed `observe()`, and
so the momentum and volatility signals, as they already do in the scheduled
call phases. With agents now quoting into halts, the halted book's mid moves,
where before it stayed still. Watch for it in the live run; this is the same
behaviour as pre-open, not a new class of problem.
