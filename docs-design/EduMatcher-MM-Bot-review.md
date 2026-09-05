Version: 1.4.0

Date: 2026-09-05

Status: Phases A and B implemented (see §5); the engine-side correctness bug
found in v1.2.0 follow-up review (§4 item 3) is now fixed; §2.1's "why not
multi-symbol" premise corrected and Phase C given a concrete implementation
plan (§5a)

# EduMatcher — Market-Maker Bot Functional Review (pm-mm-bot)

> **Update (v1.1.0):** Phase A (the `register_tick_decimals` fix and the
> stale `pm-config-gen` doc note) and Phase B (config-file support and the
> `PricingStrategy` interface) from §5 below have been implemented — see
> `docs-design/EduMatcher-MM-bots.md` §14.4 (now marked Implemented, v1.2.0)
> and `docs/user-guide/100-mm-bot.md` § Config file for the shipped design
> and usage. The rest of this document is left as originally written: an
> accurate record of the review that motivated the change, not a live status
> page. Phases C–E (multi-symbol mode, risk/operability items, and the final
> documentation/sign-off pass) remain open.

> **Update (v1.2.0):** A follow-up Q&A pass on §2.3's fill/reissue timing
> answer surfaced a real engine-side bug that §2.3 (as originally written)
> did not know about and stated incorrectly: **a *partial* fill on a quote
> leg does not get that leg's own resting remainder cancelled anywhere**,
> only its sibling. See the corrected §2.3, the new §4 item 3, and the
> reproduction script referenced there. This is an `engine/main.py` bug, not
> a `pm-mm-bot` bug — the bot has no visibility into it and cannot work
> around it — but it directly affects the bot's real-world exposure under
> `INACTIVATE_ON_ANY_FILL` (the bot's assumed policy), so it is recorded
> here rather than in a separate engine-only document.

> **Update (v1.3.0):** §4 item 3's *first* proposed fix (cancel the hit
> leg's own remainder inside `_on_quote_leg_filled`, at fill time) was
> caught as wrong before it shipped — it would have contradicted the
> documented intent of `INACTIVATE_ON_ANY_FILL` by killing live, tradeable
> quote liquidity the instant it was touched, rather than only once a
> replacement quote actually arrives. The **correct** fix — implemented and
> tested in this version — is in `_handle_quote_new`'s replace-in-slot
> logic instead: a new fallback, `_cancel_orphaned_quote_legs`, cancels any
> stray resting quote-origin order for the gateway/symbol when no active
> `QuoteIndex` entry is found to replace. See §4 item 3's "Fix (implemented
> in v1.3.0)" subsection for the full detail, the five new regression tests
> in `tests/test_mm_quotes_engine.py`, and the corrected §2.3.

> **Update (v1.4.0):** §2.1's original answer explained the single-symbol
> constraint correctly as a fact, but its framing invited the wrong
> conclusion — that N processes (Phase C's swarm-of-processes proposal) is
> the only way to get multi-symbol coverage. A direct question from the
> project owner surfaced this: **nothing on the engine side ties a
> `MARKET_MAKER` gateway, or its quotes, to a single symbol.** The engine's
> `QuoteIndex` keys every active quote by `(gateway_id, symbol)` and
> explicitly tracks a *set* of such keys per gateway
> (`models/quote.py:92-116`) — one gateway can hold as many concurrent
> quotes across as many symbols as it likes, exactly like a real MM's single
> exchange session quoting a whole book of names. §2.1 is corrected in place
> below (marked, not rewritten) and a concrete implementation plan for a
> genuinely single-process, single-gateway multi-symbol `pm-mm-bot` is added
> as new §5a, ahead of the existing Phase C swarm-of-processes plan, which
> is now the fallback option rather than the default.

## Table of Contents

- [EduMatcher — Market-Maker Bot Functional Review (pm-mm-bot)](#edumatcher--market-maker-bot-functional-review-pm-mm-bot)
  - [Table of Contents](#table-of-contents)
  - [1. Scope and Method](#1-scope-and-method)
  - [2. Answers to the Review Questions](#2-answers-to-the-review-questions)
    - [2.1 Single symbol or multiple symbols per instance?](#21-single-symbol-or-multiple-symbols-per-instance)
    - [2.2 Config file vs. CLI options for strategy selection](#22-config-file-vs-cli-options-for-strategy-selection)
    - [2.3 One leg fills — does the bot cancel the other leg and re-quote both sides?](#23-one-leg-fills--does-the-bot-cancel-the-other-leg-and-re-quote-both-sides)
    - [2.4 Will the bot work, as far as code review can tell?](#24-will-the-bot-work-as-far-as-code-review-can-tell)
    - [2.5 What functionality is missing?](#25-what-functionality-is-missing)
    - [2.6 Can we add more advanced strategies via a simple config file?](#26-can-we-add-more-advanced-strategies-via-a-simple-config-file)
    - [2.7 What else is needed before v1.0.0?](#27-what-else-is-needed-before-v100)
  - [3. ZMQ Usage vs. the Rest of the Codebase](#3-zmq-usage-vs-the-rest-of-the-codebase)
  - [4. Confirmed Bugs and Discrepancies](#4-confirmed-bugs-and-discrepancies)
  - [5. Plan to v1.0.0](#5-plan-to-v100)
    - [Phase A — Correctness fixes (blocking)](#phase-a--correctness-fixes-blocking)
    - [Phase B — Config-file strategy support](#phase-b--config-file-strategy-support)
    - [Phase C — Multi-symbol mode](#phase-c--multi-symbol-mode)
    - [Phase D — Operability](#phase-d--operability)
    - [Phase E — Documentation and sign-off](#phase-e--documentation-and-sign-off)
  - [5a. Implementation Plan — True Multi-Symbol `pm-mm-bot`](#5a-implementation-plan--true-multi-symbol-pm-mm-bot)
    - [5a.1 Why this is possible](#5a1-why-this-is-possible)
    - [5a.2 What has to change in `bot.py`](#5a2-what-has-to-change-in-botpy)
    - [5a.3 CLI, config file, and gateway identity](#5a3-cli-config-file-and-gateway-identity)
    - [5a.4 Per-symbol failure isolation](#5a4-per-symbol-failure-isolation)
    - [5a.5 Staged implementation steps](#5a5-staged-implementation-steps)
    - [5a.6 Testing](#5a6-testing)
    - [5a.7 What this does *not* change](#5a7-what-this-does-not-change)
    - [5a.8 Relationship to Phase C](#5a8-relationship-to-phase-c)
  - [6. Explicitly Out of Scope for v1.0.0](#6-explicitly-out-of-scope-for-v100)

## 1. Scope and Method

This is a functional code review of `src/edumatcher/mm_bot/` (`bot.py`, `main.py`,
`pricer.py`, 3 files, ~880 lines of runtime code) against the existing design
doc `docs-design/EduMatcher-MM-bots.md` (v1.1.0, status "Implemented") and the
90+ tests in `tests/test_mm_bot.py`. It also compares the bot's ZMQ usage
against `messaging/bus.py` and the other gateway/bot processes
(`ai_trader`, `alf_gwy`, `balf_gwy`, `api_gateway`) that share the same
transport layer. It does not re-run the test suite or static-analysis gates
(black/flake8/mypy/pyright) — the git history (`ba32e3a3`, `76387ff0`, and the
CHANGELOG's four-bug patch round) shows those gates are already exercised
routinely for this package, and the finding here is about *behavioural* gaps
rather than style or typing.

## 2. Answers to the Review Questions

### 2.1 Single symbol or multiple symbols per instance?

> **Correction (v1.4.0):** everything below about *today's* code is
> accurate and unchanged. What was missing is the "why" — the original
> answer read as though one-symbol-per-instance were a constraint the
> exchange imposes, and it is not. **Nothing on the engine side limits a
> `MARKET_MAKER` gateway to one symbol.** `QuoteIndex` (`models/quote.py`)
> keys every active quote by `(gateway_id, symbol)` and tracks a *set* of
> such keys per gateway (`_keys_by_gateway: dict[str, set[tuple[str,
> str]]]`, `quote.py:95`) — one gateway ID can hold as many simultaneous
> active quotes, across as many symbols, as it likes. There is no schema
> check, no config constraint, and no protocol restriction anywhere that
> ties a gateway to a single symbol; a real exchange market maker quoting
> a whole book of names from one session is exactly this shape. The
> one-symbol-per-instance rule below is entirely a `pm-mm-bot`
> implementation choice — every per-symbol assumption lives in `MMBot`'s
> own instance attributes (`self.symbol`, `self._pricer`, `self._quote_id`,
> etc.), not in anything the engine requires. **A concrete plan to remove
> that constraint — refactoring `MMBot` itself to hold N symbols' worth of
> state in one process behind one gateway ID, rather than running N
> processes — is now §5a**, ahead of the swarm-of-processes Phase C
> proposal below, which remains a valid *fallback* (see §5a.8 for when it's
> still the better choice) but is no longer the only path to multi-symbol
> coverage.

**One instance quotes exactly one symbol, today.** `MMBot.__init__` takes a
single `symbol: str` (`bot.py:77`), and the class docstring says so
directly: "Autonomous market-maker bot for **a single symbol**"
(`bot.py:71`). The CLI (`main.py:29-31`) requires exactly one `--symbol`. To
make markets in three symbols today you run three OS processes, each with
its own gateway ID (`MM_AAPL_01`, `MM_MSFT_01`, `MM_TSLA_01` — see §9.1 of
the design doc).

The design doc already flags this as a known limitation, not an oversight:
§14.3 "Multi-Symbol Mode" proposes a future `--symbols AAPL,MSFT,TSLA` mode
"similar to how `pm-ai-swarm` manages multiple single-trader bots" — and that
sibling process already exists and does a related pattern for the AI trader
(`src/edumatcher/ai_trader/swarm.py`, which launches one `pm-ai-trader`
**subprocess** per bot via Python's `subprocess` module — see
`build_bot_command`/`build_gateway_ids`, not an in-process fan-out — each
with its own gateway ID and, in swarm mode, its own single assigned symbol).
§14.3 and the original Phase C below took that as the template to reuse
rather than inventing a new supervision model; §5a below proposes the
alternative of removing the constraint from `MMBot` directly instead.

### 2.2 Config file vs. CLI options for strategy selection

**As of v1.1.0 of this document, this has been implemented — see the update
note at the top of this file and §5 Phase B.** The analysis below describes
the state at the time of the original review and remains accurate as a
record of why the change was made.

**CLI flags only — there is no config-file mode.** `main.py` builds an
`argparse` parser with about 20 flags (`--gap`, `--qty`, `--drift-ticks`,
`--reissue-delay-ms`, `--tif`, the five timeout/interval flags, the
`--initial_min`/`--initial_max` bootstrap range, the two engine socket
addresses, logging flags). There is exactly one strategy: symmetric
fixed-gap quoting around the tracked mid (`pricer.py`). There is no
`--profile` selector and no `--config path.yaml`.

This mirrors §14.4 "Config-File Mode" in the design doc, which proposes
`pm-mm-bot --config mm_aapl.yaml` as future work, explicitly "to allow
complex configurations to be version-controlled... and make the launch
script simpler." It is worth noting that `pm-ai-trader` — the bot's closest
sibling — already went one step further than `pm-mm-bot` here: it selects
between four named strategies (`aggressive`, `cautious`, `many-small`,
`few-large` in `ai_trader/personality.py`) via `--profile`, though those are
still hard-coded presets, not an external file. `pm-mm-bot` has neither
presets nor a file. See §5 Phase B for a concrete, minimal proposal.

### 2.3 One leg fills — does the bot cancel the other leg and re-quote both sides?

> **Correction (v1.2.0, fixed in v1.3.0):** the original answer below said
> the engine "has already torn down both legs" by the time the bot
> reissues. That was true only when the hit leg is *fully* filled. **On a
> partial fill, the hit leg's own remainder was never cancelled by the
> engine at fill time — it was left resting** — which is actually the
> documented, intended behavior (see §4 item 3's "Correction (v1.3.0)"),
> **but the bot's reissue was not cleaning it up either**, because the
> replace-in-slot logic that was supposed to do exactly that
> ("cancel any surviving old child orders") only ran when it found a live
> `QuoteIndex` entry, and the engine had already removed that entry at fill
> time, before the reissue ever arrived. **As of v1.3.0 this is fixed**: the
> replace-in-slot logic now falls back to scanning the book directly for
> the stray leg when no `QuoteIndex` entry is found. See §4 item 3 for the
> full trace, the fix, and the reproduction/tests. The bullets below are
> left as originally written except where marked, so the correction is
> visible in context rather than silently rewritten.

**The exchange cancels the sibling leg, not the bot — and the bot always
re-quotes both sides together; it never leaves one leg resting alone.**
Tracing the actual message flow:

1. A fill on either leg is reported by the **engine**, not decided by the
   bot. `quote_refresh_policy: INACTIVATE_ON_ANY_FILL` (configured per
   gateway, §9.2 of the design doc) means the engine's fill handler removes
   the quote from its internal `QuoteIndex` and explicitly cancels the
   *sibling* order — **not** the filled order itself (see §4 item 3: for a
   full fill this is moot, since a fully filled order has nothing left to
   cancel, but for a partial fill it means the filled leg's remainder is
   never cancelled by this path). The bot is a passive recipient of
   `order.fill.{GW}` and `quote.status.{GW}
   status=INACTIVE_BID_FILLED`/`INACTIVE_ASK_FILLED`.
2. On seeing `INACTIVE_*_FILLED` (`bot.py:550-556`), the bot clears its
   local quote/leg state (`_clear_quote_state()`) and arms a reissue timer
   `reissue_delay_ms` (default **200 ms**) in the future. It does **not**
   send a `quote.cancel` on this path — the bot believes one isn't needed,
   because it (like the original text here) assumes the engine has already
   torn down both legs. **That assumption is false for a partial fill** —
   see §4 item 3.
3. When the timer fires, `_cancel_and_reissue()` sees `_quote_id is None`
   and calls `_send_quote()` directly (`bot.py:484-494`), which always sends
   one `quote.new` carrying **both** `bid_price`/`ask_price` and
   `bid_qty`/`ask_qty` (`bot.py:456-467`) — there is no code path that
   re-quotes only one side.
4. The engine's `quote.new` handler (`engine/main.py`, `_handle_quote_new`)
   is itself an atomic replace: it looks up any existing quote for the
   `(gateway_id, symbol)` slot, cancels it if present, and installs the new
   pair in one synchronous step. So even the drift-reprice and
   heartbeat-recovery paths in `bot.py`, which *do* send an explicit
   `quote.cancel` before the new `quote.new` (`_cancel_and_reissue`'s other
   branch, used when the bot still believes a quote is live), are being
   extra cautious rather than relying on a race-prone assumption — the
   explicit cancel there is defensive, not load-bearing. **Caveat added in
   v1.2.0: this atomic replace only cancels a quote it can still find in the
   index. When the previous fill already removed the index entry (the
   `INACTIVATE_ON_ANY_FILL` reissue path, steps 1–3 above), `_handle_quote_new`
   finds nothing to replace and skips the cancel entirely — it never falls
   back to scanning the book for stray orders from this gateway/symbol.**

**Typical timing:** fill → `quote.status` → **~200 ms** (`--reissue-delay-ms`,
configurable) → fresh two-sided `quote.new` → `quote.ack`. That is the
whole one-sided gap in the normal case, **for a full fill**. The
cancel-first paths (drift reprice, heartbeat recovery) that *do* wait for a
`quote.cancel` confirmation are bounded by `--cancel-timeout-sec` (default
**1.0 s**); if no confirmation arrives in that window, `_tick()` forces the
local state clear and reissues anyway (`bot.py:702-708`), so the bot can
never wait indefinitely on a lost cancel ack. Net: the bot is out of the
market for at most ~200 ms after an ordinary (full) fill, and for at most
~1 s in the (rarer) drift/heartbeat-recovery paths — but see §4 item 3 for
what actually happens on a *partial* fill, which is not "out of the
market," it is "quoting twice."

One nuance worth flagging: **while quoting normally, a fill is one-sided by
definition** (only the leg that got hit fills), but the *engine* inactivates
the untouched sibling leg too, so "the bot cancels the other leg" is not
quite accurate framing — the bot never has to, because the exchange
*intends* to enforce "filled or nothing" for MM quotes under
`INACTIVATE_ON_ANY_FILL`. **As of this v1.2.0 correction, that enforcement
is known to be incomplete for partial fills — see §4 item 3.** If the
project ever wants a policy where the surviving *sibling* leg stays resting
after a partial fill on the other side, that would be a new
`quote_refresh_policy` value on the engine (a legitimate, separate feature
request); it is not the same thing as the bug in item 3, which is about the
*hit* leg's own remainder, not the sibling.

### 2.4 Will the bot work, as far as code review can tell?

**Yes, for the single-symbol, fixed-gap, symmetric-quoting use case it was
built for.** The state machine is complete and defensively written:

- Startup sequence (connect → auth → symbols → gap validation → `QBOOT`
  adopt-or-bootstrap → `QLEGS` reconcile → wait for session → first quote)
  fails closed at every step — every `_run_loop` early return logs a
  specific reason and returns exit code 1, there is no silent partial start.
- The reissue/heartbeat/QLEGS-reconciliation triad gives the bot three
  independent ways to notice and recover from a stuck or diverged state
  (dropped `quote.ack`, orphaned `CANCELLED` after an already-processed
  `INACTIVE`, a fill arriving while a cancel is already in flight). The git
  history (`ba32e3a3`) shows these were each found and fixed as real bugs
  during hardening, and each now has a dedicated regression test
  (`TestFillDuringCancelInFlight`, `TestQuoteStatusOrphanedCancelled`,
  `TestMMBotQlegsReconciliation`).
- `tests/test_mm_bot.py` has ~95 tests covering pricer edge cases (tick
  rounding, minimum spread, drift boundaries), CLI validation, startup
  failure paths, fill/cancel/reissue timing races, session/halt handling,
  and QLEGS divergence — this is unusually thorough test coverage for a
  package this size and gives real confidence in the state machine as
  written.

That said, "will it work" surfaced one concrete correctness gap during this
review (§4 below): the bot never calls `register_tick_decimals()` for its
own symbol, so `to_ticks()` inside `_send_quote()` can silently use the
wrong price scale for any non-default-tick-size symbol if the bot happens to
be the first process to reference that symbol's price conversion. In the
normal classroom sequence (engine starts first and registers every
configured symbol's tick decimals at boot) this is masked, but it is a
latent bug, not a hypothetical one — it depends on process start order that
the bot does not itself guarantee.

### 2.5 What functionality is missing?

Grouped by whether the design doc already anticipated it (§14) or this
review found it independently:

**Already tracked as future work (§14 of the existing design doc), still
missing:**
- Multi-symbol mode (§14.3 / §2.1 above).
- Config-file mode (§14.4 / §2.2 above).
- Inventory skewing — the bot always quotes symmetrically around mid; it has
  no notion of net position and cannot lean its quote to work down an
  accumulated inventory (§14.1).
- Volatility-adaptive spread — `gap` is fixed for the life of the process
  (or derived once from `mm_max_spread_ticks` at startup); it never widens
  in a fast market (§14.2).
- Coordination between same-symbol instances — two bots on `MM_AAPL_01`/`02`
  can both reprice at once, each briefly widening the effective market
  spread during their own cancel windows (§14.5).
- Metrics/observability endpoint — no `--metrics-port`; the only visibility
  is the log stream (§14.6).

**Found during this review, not previously documented:**
- No `register_tick_decimals()` call for the bot's own symbol (§4) — a
  correctness gap, not a feature gap, but it belongs in the same fix pass.
- `docs-design/EduMatcher-MM-bots.md` §9.2's tip — "Use `pm-config-gen
  --gateways MM_AAPL_01:MARKET_MAKER ...` *(to be created as part of this
  feature)*" — is now stale. `pm-config-gen` already has full
  `MARKET_MAKER`/`disconnect_behaviour`/`mm_max_spread_ticks` support
  (`config_gen/builder.py`, `config_gen/gateway_spec.py`,
  `config_gen/warnings.py`). The doc should be updated to say so plainly
  rather than "to be created," since a reader following the doc today would
  wrongly conclude the tooling doesn't exist yet.
- No maximum-position / risk cap. Unlike `pm-ai-trader`, which enforces
  `--max-position` and a reject-rate circuit breaker
  (`ai_trader/main.py`'s `_max_position`, `_max_rejects` fields), `pm-mm-bot`
  has no analogous safety valve — it will keep quoting the same fixed size
  on both sides indefinitely regardless of how much inventory it has
  accumulated one-sidedly (which ties back to the missing inventory-skew
  feature: without either skew or a cap, an MM bot in a trending market
  will accumulate an unbounded position).
- No re-registration or refresh of symbol metadata mid-run. If
  `mm_max_spread_ticks` or `tick_decimals` changes on the exchange while the
  bot is already running (e.g., an instructor edits config between
  classroom sessions and restarts only the engine), the bot never re-requests
  `system.symbols_request` after startup and would keep using stale values
  until manually restarted.

### 2.6 Can we add more advanced strategies via a simple config file?

Yes, and the codebase already shows the shape to copy. `pricer.py` is
already cleanly separated from the ZMQ/state-machine code ("QuotePricer is
stateless with respect to ZMQ" — its own docstring), so a new strategy is a
new class with the same three-method surface (`update_mid`/`set_mid`,
`compute_prices`, `has_drifted`) that `bot.py` calls through
`self._pricer`. Concretely:

1. Define a small `StrategyConfig` schema (YAML) with a `strategy: symmetric
   | skewed | volatility_adaptive` discriminator plus that strategy's own
   parameters, loaded once at startup the same way `engine_config.yaml` is
   loaded elsewhere in the codebase (there is already a YAML-loading and
   validation convention to match — see `config_gen/`).
2. Keep `--gap`, `--qty`, etc. as overridable CLI flags for the common case
   (a config file is not the only way in), matching how the project already
   treats CLI flags as overrides of config-file defaults elsewhere.
3. `bot.py` picks the concrete pricer class based on `strategy` and passes
   it the rest of `MMBot` unchanged — none of the state machine, ZMQ
   handling, or reissue/heartbeat logic needs to know which strategy is
   active, because all of that already only talks to `self._pricer` through
   the three-method interface above.

This is a moderate, well-scoped piece of work — not a rewrite — precisely
because the pricer/bot separation was already done correctly in v1.

### 2.7 What else is needed before v1.0.0?

See §5 for the full phased plan; in priority order the blocking items are:
the `register_tick_decimals` gap (§4), refreshing the stale `pm-config-gen`
note in the design doc, and a documented, deliberate decision on
"single-symbol CLI-only" as the shipped v1.0.0 scope versus deferring
multi-symbol/config-file support to a v1.1 (both are real, scoped features,
not quick additions — see §5 Phases B and C for size).

## 3. ZMQ Usage vs. the Rest of the Codebase

**Yes — `mm_bot` follows the established ZMQ conventions in
`messaging/bus.py` and matches its closest sibling, `pm-ai-trader`, in every
respect that matters:**

- **Socket factories, not raw `zmq.Context()` calls.** Both
  `_setup_sockets()` (`bot.py:201-218`) and `AITraderBot.__init__`
  (`ai_trader/main.py:120-131`) go through `make_pusher()`/`make_subscriber()`
  from `messaging/bus.py`, so the PUSH socket automatically inherits the
  shared fail-fast defaults (`SNDTIMEO=0`, `SNDHWM=1000`, `IMMEDIATE=1`) —
  the bot never risks blocking its single-threaded loop if the engine's PULL
  side is backed up, exactly as `bus.py`'s own comment intends.
- **Topic-prefix subscription, not a wildcard SUB with in-process
  filtering.** `_setup_sockets()` subscribes to the exact set of
  gateway-scoped and symbol-scoped topics it needs
  (`topic_gateway_auth(self.gateway_id)`, `topic_book_snapshot(self.symbol)`,
  etc.) rather than subscribing to everything and filtering in Python — this
  matches every other gateway process reviewed (`alf_gwy`, `balf_gwy`,
  `ai_trader`) and keeps the bot's own receive volume proportional to what
  it actually consumes.
- **`zmq.Poller` with a timeout, never a blocking `recv()`.** Every wait
  (`_authenticate`, `_request_symbols`, `_request_bootstrap`,
  `_request_qlegs`, `_wait_for_session`, the main loop, and shutdown's
  cancel-confirmation wait) polls with an explicit deadline loop rather than
  blocking indefinitely — consistent with the rest of the codebase's
  reactor-style single-threaded event loops, and necessary here since the
  bot has its own timers (reissue, heartbeat, QLEGS) that must keep firing
  even while waiting for a specific reply.
- **`decode()`/typed `make_*_msg()` helpers, not hand-rolled JSON.** All
  messages go through `edumatcher.models.message` — the shared codec that
  the msgen-generated system uses everywhere — so the bot gets the same
  wire format, the same three-frame `SequencedPublisher` sequencing on the
  subscribe side, and the same schema guarantees as every other consumer.
  Nothing in `bot.py` constructs a frame list or a JSON payload by hand
  outside those helpers.
- **Clean socket teardown.** `_close_sockets()` is called from a `finally`
  block in `run()`, so sockets are released even if `_run_loop()` raises —
  matching the close-on-exit discipline used elsewhere (though note this
  project's convention is a shared module-level `zmq.Context.instance()`
  that is never explicitly terminated by any process reviewed; that appears
  to be an accepted, deliberate simplification for short-lived
  classroom/CLI processes rather than an oversight specific to this bot).

No divergence from house style was found. The one structural difference
from `pm-ai-trader` — `mm_bot` takes engine addresses as CLI flags
(`--engine-pull`/`--engine-pub`, defaulting to `tcp://127.0.0.1:5555/5556`)
where `ai_trader` imports fixed constants (`ENGINE_PULL_ADDR`,
`ENGINE_PUB_ADDR` from `edumatcher.config`) — is a design choice, not a ZMQ
convention violation; if anything it makes `mm_bot` slightly more flexible
for pointing at a non-default engine instance, at the cost of one more way
for a launch script to get it wrong. Not a defect, just worth naming as an
inconsistency between the two sibling bots if a future pass wants to
standardize one way or the other.

## 4. Confirmed Bugs and Discrepancies

**Items 1 and 2 are fixed as of v1.1.0 of this document. Item 3 was found in
v1.2.0 follow-up review and fixed in v1.3.0 — see the update notes at the
top of this file. It is an `engine/main.py` bug, not a `pm-mm-bot` bug.**

1. **Missing `register_tick_decimals()` call — silent wrong price scale on
   non-default-tick symbols.** `_request_symbols()` (`bot.py:269-303`)
   extracts `tick_decimals` from the symbol-metadata reply and sets
   `self._tick_size` for the bot's *own* pricer math, but never calls
   `edumatcher.models.price.register_tick_decimals(symbol, tick_decimals)`.
   Every other symbol-metadata consumer in the codebase does
   (`alf_gwy/gateway.py:1213`, `balf_gwy/gateway.py:993`,
   `api_gateway/engine_client.py:538`, `ai_trader/main.py:326`,
   `engine/main.py:825,1117`). Since `_send_quote()` calls the *module-level*
   `to_ticks(bid, self.symbol)` (`bot.py:461-462`), which reads from that
   same global registry (defaulting to 2 decimals for an unregistered
   symbol), the price the bot puts on the wire can be scaled differently
   from the price its own pricer computed, for any symbol where
   `tick_decimals != 2` and where the engine or another gateway process has
   not already registered that symbol before the bot's first quote. In the
   normal boot order (engine starts first, registers every configured
   symbol at `engine/main.py:825`) this is masked; it is still a real gap
   because the bot does not defend its own correctness and depends on
   process start order it does not control or check. **Fix:** call
   `register_tick_decimals(self.symbol, int(meta["tick_decimals"]))`
   alongside the existing `self._tick_size` assignment in
   `_request_symbols()`.
2. **Stale tooling note in the existing design doc.** §9.2 of
   `EduMatcher-MM-bots.md` says the `pm-config-gen --gateways ...` helper is
   "to be created as part of this feature" — it already exists and is fully
   featured (`config_gen/builder.py:701-712`,
   `config_gen/gateway_spec.py:28`, `config_gen/warnings.py:90-99`). Low
   severity (documentation only) but should be corrected so instructors
   don't think they have to hand-write gateway YAML stanzas.

3. **Engine never cancels a quote leg's own remainder on a *partial* fill —
   the MM ends up quoting the same side twice.** (Found in v1.2.0 follow-up
   review; **fixed in v1.3.0** — see the corrected "Fix" subsection below,
   which replaces this item's original, incorrect proposed fix.)

   **Symptom.** Under `quote_refresh_policy: INACTIVATE_ON_ANY_FILL` (the
   policy `pm-mm-bot` is designed around — see §2.3), when a resting quote
   leg is only *partially* filled (a taker takes less than the full
   quoted quantity), the engine inactivates the quote and cancels the
   sibling leg exactly as documented — but it never cancels the **hit
   leg's own remaining quantity**. That remainder stays resting on the
   book, at its old price, indefinitely. `pm-mm-bot` then immediately
   reissues a brand-new two-sided quote on top of it (per §2.3), because
   `quote.status INACTIVE_*_FILLED` is the bot's signal that both legs are
   already gone — which is only true for a full fill. **Net effect: the
   gateway ends up with two live resting orders on the same side** (the old
   partial remainder plus the new leg) until the stale one is separately
   hit, expires on its own `TIF`, or the whole gateway's quotes are torn
   down (disconnect, kill switch, explicit cancel) — silently doubling the
   MM's real one-sided exposure versus what it believes it has quoted.

   **Root cause, traced end to end in `engine/main.py`:**

   - `_on_quote_leg_filled()` (~line 3057) is the engine's fill handler for
     quote legs. On `INACTIVATE_ON_ANY_FILL` it does exactly two things:
     `self._quote_index.remove(gateway_id, symbol, ...)` (pops the
     bookkeeping entry — a pure in-memory dict operation, **not** a book
     operation) and `self._cancel_order_by_id(sibling_id)` (cancels the
     *other* leg). It never calls `_cancel_order_by_id(order.id)` for
     `order` — the leg that was actually hit — anywhere in the function.
     The function's own comment states the (incomplete) assumption
     outright: *"`order` is the filled leg — already terminal, its final
     state is available directly."* That is true when `order.status ==
     FILLED`; it is false when `order.status == PARTIAL`.
   - Whether a hit leg is actually terminal depends on
     `OrderBook._apply_fill()` (`order_book.py` ~line 1213):
     `passive.status = OrderStatus.FILLED if passive.remaining_qty == 0
     else OrderStatus.PARTIAL`, and `_purge_from_indexes(passive)` — the
     function that actually removes an order from the book's price-level
     structures — is called **only** `if passive.status == OrderStatus.FILLED`.
     A `PARTIAL` order is deliberately left resting with its reduced
     `remaining_qty`; `_handle_new_order`'s own fill-loop comment agrees
     ("a partially filled order that rests keeps it [routing entry]").
   - The bot's reissue does not accidentally clean this up either.
     `_handle_quote_new()`'s replace-in-slot logic (~line 3278) is:
     `previous = self._quote_index.remove(gateway_id, symbol, ...); if
     previous: self._cancel_quote_entry(previous, ...)`. `_cancel_quote_entry`
     is the **only** code path that ever calls `_cancel_order_by_id` on a
     quote's tracked bid/ask ids. But by the time the reissue's `quote.new`
     arrives, `_on_quote_leg_filled` has *already* popped the `QuoteIndex`
     entry (first bullet above) — so `previous` is `None`, `_cancel_quote_entry`
     never runs, and nothing else in `_handle_quote_new` looks at the book
     itself. The replace path relies entirely on the `QuoteIndex` entry
     still existing and still accurately describing what is resting; a
     partial fill silently breaks that invariant without removing the
     entry in a way that lets the replace path notice.
   - This is **not a new regression** — `git log -S"_on_quote_leg_filled"`
     shows only three commits ever touched this function
     (`91d8365c` introducing it, `1cf2bdb2` and `9a000897` adding QLEGS
     history capture), none changing the sibling-only cancellation logic.
     The gap has existed since MM quotes were first implemented. It is also
     not caught by any existing test: no test in `tests/test_mm_quotes_engine.py`,
     `tests/test_engine_quote_legs.py`, or elsewhere asserts book state
     after a *partial* fill on a quote leg followed by a reissue.
   - **The design docs describe the same incomplete picture.** Both
     `docs-design/EduMatcher-MM_Quotes_Implementation_Plan.md` (`QuoteIndex`
     docstring: "Enforces the rule: at most one active quote per
     (gateway_id, symbol) pair") and `docs-design/mm-quote-identification.md`
     ("there can be only one active quote slot per gateway and symbol") are
     accurate as written — they describe the `QuoteIndex` *slot*, which
     genuinely never holds more than one entry — but neither claims, and
     neither the code nor any test verifies, that the physical book can
     never hold a stray resting order outside that slot. The
     `mm-quote-identification.md` walkthrough for exactly this policy
     (`INACTIVATE_ON_ANY_FILL`, its "Example 1") shows a fill with no
     `remaining=` figure at all — i.e. it silently illustrates only the
     full-fill case — while its full-fill-only-policy example
     (`INACTIVATE_ON_FULL_FILL`, "Example 2") does show a partial fill, but
     for a policy where the engine deliberately leaves the quote active.
     The partial-fill-under-`ANY_FILL` combination this bug lives in was
     never walked through anywhere.
   - **Empirically confirmed, not just read from the source.** A standalone
     repro against the real `Engine` (using the project's own
     `tests/test_mm_quotes_engine.py::_make_engine` harness): post a
     500x500 quote, submit a same-gateway 100-lot order that partially fills
     the bid leg, then immediately reissue a fresh 500x500 quote (as the bot
     does). Result: `book.resting_orders()` for that gateway shows **two**
     live `BUY` orders — the stale one at `remaining_qty=400,
     status=PARTIAL` from the original quote, and the new 500-qty leg from
     the reissue — plus the fresh ask leg. The stale order is never touched
     by the reissue.

   > **Correction (v1.3.0): the fix below was wrong and was never shipped.**
   > The original text here proposed cancelling the hit leg's own remainder
   > *inside* `_on_quote_leg_filled`, i.e. immediately on the fill. That
   > would have been a real behavior regression, not a fix: it directly
   > contradicts the documented intent of `INACTIVATE_ON_ANY_FILL` itself.
   > The `QuoteRefreshPolicy` docstring in
   > `EduMatcher-MM_Quotes_Implementation_Plan.md` gives its own worked
   > example — "Someone buys 100 from the ask. Bid still has 500. **Ask has
   > 400 remaining.** `INACTIVATE_ON_ANY_FILL`: pull the **bid** immediately"
   > — pulling the *sibling* (bid), never the hit leg's (ask's) own 400
   > remaining. The hit leg's remainder is meant to stay live and tradeable
   > until the bot's *reissue* actually replaces it, not to be killed the
   > instant it's touched — cancelling it immediately would leave the book
   > with zero resting quantity from this MM on that side for the whole
   > `--reissue-delay-ms` gap (~200 ms) on every partial fill, which is
   > exactly the kind of stale-exposure/no-liquidity gap
   > `INACTIVATE_ON_ANY_FILL` exists to prevent, not cause. The actual,
   > implemented fix is below.

   **Fix (implemented in v1.3.0).** The real gap is narrower: it's in
   `_handle_quote_new`'s replace-in-slot logic, not in
   `_on_quote_leg_filled`. `docs-design/mm-quote-identification.md`'s
   own replace-by-new-quote walkthrough already states the intended
   behavior — "remove the current active quote slot... **cancel any
   surviving old child orders**... install the new quote" — but the actual
   code only did that when `self._quote_index.remove(...)` found a live
   `QuoteEntry` (`previous`). When a prior fill had already removed that
   entry (the `INACTIVATE_ON_ANY_FILL` case this bug lives in), `previous`
   is `None` and the "cancel any surviving old child orders" step silently
   never ran. The fix adds exactly that fallback, at replace time, without
   touching `_on_quote_leg_filled` or the fill-time behavior at all:

   ```python
   previous = self._quote_index.remove(
       gateway_id, symbol, reason="Replaced by new quote"
   )
   if previous:
       self._cancel_quote_entry(previous, reason="Replaced by new quote")
   else:
       # No active QuoteIndex entry — most commonly because a prior fill
       # already inactivated this gateway/symbol's quote. Under
       # INACTIVATE_ON_ANY_FILL, that path cancels only the untouched
       # sibling leg — by design, the *hit* leg's own remainder (if the
       # fill was partial) is meant to stay resting, live and tradeable,
       # until this replacement quote actually supersedes it.
       self._cancel_orphaned_quote_legs(gateway_id, symbol)
   ```

   `_cancel_orphaned_quote_legs(gateway_id, symbol)` is a new small helper
   next to `_cancel_quote_entry`: it scans `book.resting_orders()` for any
   order matching `gateway_id` and `origin == OrderOrigin.QUOTE` and cancels
   it via the existing `_cancel_order_by_id`. It deliberately does **not**
   touch ordinary (`origin=ORDER`) orders — this mirrors
   `_handle_gateway_disconnect`'s `CANCEL_ALL` sweep, which excludes
   quote-origin orders for the opposite reason (it expects `QuoteIndex`
   -driven cancellation, not a book scan, to handle those). No `quote.status
   CANCELLED` is re-published for the orphaned leg — the quote was already
   announced `INACTIVE_*_FILLED` at fill time; only an ordinary
   `order.cancelled` is emitted, via `_cancel_order_by_id`'s existing
   publish.

   **Verified.** The standalone repro from the original finding now shows
   the fix working end to end: immediately after the partial fill (before
   any reissue), the hit leg is still `PARTIAL` with its full remainder
   resting and genuinely tradeable — a second taker order was confirmed to
   still fill against it. Only once the bot's reissue actually arrives does
   `_cancel_orphaned_quote_legs` find and cancel it; `book.resting_orders()`
   for that gateway then shows exactly the new quote's two legs, never
   three. Five new tests were added to `tests/test_mm_quotes_engine.py`:
   `test_partial_fill_sibling_cancelled_but_hit_leg_survives` (the hit leg
   stays live and tradeable right after the fill — the policy's actual
   intent),
   `test_reissue_after_partial_fill_cancels_stale_remainder` (the
   regression test for the bug itself — the stale remainder is gone and
   `order.cancelled` was published for it after the reissue),
   `test_reissue_with_no_prior_quote_is_unaffected` and
   `test_reissue_after_full_fill_still_finds_nothing_stray` (the new
   fallback is a true no-op when there is nothing stray to find), and
   `test_inactivate_on_full_fill_partial_leg_stays_active_and_unaffected`
   (confirms `INACTIVATE_ON_FULL_FILL`'s deliberate "accumulate partials,
   stay active" behavior — design doc's own "Example 2" — is completely
   unaffected, since that policy never inactivates on a partial fill in the
   first place, so the ordinary `previous`-found branch handles its replace
   exactly as before). Full suite (`tests/test_mm_quotes_engine.py` plus the
   broader `-k "quote or engine"` sweep, 778 tests): all passing; black,
   flake8, mypy, and pyright all clean on both changed files
   (`engine/main.py`, `tests/test_mm_quotes_engine.py`).

   **This is an engine bug, not a `pm-mm-bot` bug** — the bot has no
   visibility into it (`quote.status INACTIVE_*_FILLED` carries no
   remaining-qty information about the hit leg) and had no way to detect or
   work around it from its own side. It is recorded in this document rather
   than a separate engine-only one because it directly affects the answer
   to §2.3 and the bot's real-world exposure under the policy the bot is
   built to assume; `pm-mm-bot` itself required no changes.

No other functional defects were found; the fill/cancel/reissue races that
were previously bugs (dropped ack, orphaned `CANCELLED`, overwritten cancel
timeout, malformed book `KeyError`, uncaught `QuotePricer` `ValueError`) are
all fixed per the CHANGELOG and covered by dedicated regression tests. Item
3 above is a new finding from v1.2.0 follow-up review, found by tracing
`quote_refresh_policy` handling end to end rather than by the original
review's method (comparing `mm_bot/*` against its own design doc and
tests) — it lives entirely in `engine/main.py`, outside `mm_bot/`'s three
files, which is why the original pass did not surface it.

## 5. Plan to v1.0.0

### Phase A — Correctness fixes (blocking) — Done

- Added the missing `register_tick_decimals()` call in `_request_symbols()`
  (§4.1), alongside the existing `self._tick_size` assignment. Added
  `TestMMBotStartup::test_symbols_reply_registers_tick_decimals_globally` in
  `tests/test_mm_bot.py`, which registers a non-default (4-decimal) tick size
  and asserts both `get_tick_decimals()` and `to_ticks()` pick it up; the
  test clears the shared tick registry before and after itself so a
  non-default registration for `AAPL` can't leak into other test files.
- Corrected the stale `pm-config-gen` note in §9.2 of `EduMatcher-MM-bots.md`
  (§4.2) — it now gives the full, working command (`--symbols` is required
  alongside `--gateways`) and notes the `MARKET_MAKER` default
  `disconnect_behaviour`.

### Phase B — Config-file strategy support — Done

- Added `mm_bot/config.py`: `load_config_file(path) -> dict`, validating the
  file is a YAML mapping whose keys are a fixed allow-list mirroring every
  CLI flag's argparse `dest` name (this includes `symbol` and `id_suffix`,
  not just tuning parameters — the file can fully replace the CLI for a
  given bot instance). Unknown keys, unreadable files, and invalid YAML all
  raise `ValueError` with the file path and reason.
- `main.py` now takes `--config PATH` and `--strategy NAME` (default
  `symmetric`). Loading is a two-pass `argparse` parse: a bare
  `parse_known_args` finds `--config`, its values are applied via
  `parser.set_defaults(**file_values)`, then the real `parse_args()` runs —
  so an explicit CLI flag always overrides the same key from the file, with
  no per-field bookkeeping. `--symbol` is no longer `required=True` at the
  argparse level; `main()` checks after parsing that it ended up set one way
  or the other. The existing `--gap`-was-explicit detection (which suppresses
  the MM-obligation auto-default) was extended to also treat a `gap:` key in
  the config file as explicit, not just a CLI flag.
- Added `PricingStrategy` (a `Protocol` in `pricer.py`) covering the six
  members `bot.py` actually calls on `self._pricer`
  (`mid_price`, `price_decimals`, `update_mid`, `set_mid`, `compute_prices`,
  `has_drifted`). `QuotePricer` is unchanged and satisfies it structurally —
  no inheritance, no renaming, so existing callers and tests were unaffected
  beyond one constructor-signature change (see below). Added
  `create_strategy(name, *, tick_size, gap, drift_ticks) -> PricingStrategy`,
  a small registry (`{"symmetric": ...}` today) keyed by `--strategy`,
  raising `ValueError` for an unknown name; `bot.py`'s `_run_loop` now calls
  this factory instead of constructing `QuotePricer` directly, and `_pricer`
  is typed as `PricingStrategy | None`.
- `MMBot.__init__` gained a required `strategy: str` parameter (threaded
  through from `main.py`'s `--strategy`/config value) — every direct
  `MMBot(...)` call site, including the test fixture, needed a `strategy=`
  kwarg added.
- This directly resolves §14.4 of the existing design doc (now marked
  Implemented, v1.2.0) and unblocks §2.6's answer above: a future
  skewed/volatility-adaptive strategy is a new class registered in
  `pricer.py`'s factory, with no change to `bot.py`'s state machine, ZMQ
  handling, or CLI plumbing.
- Added `tests/test_mm_bot_config.py` (6 tests for `config.py` in isolation)
  and 18 new tests in `tests/test_mm_bot.py` covering: the strategy factory
  (available/create/unknown/constructor-validation-propagation), `main.py`
  config-file integration (symbol-from-file, CLI-overrides-file,
  gap-from-file-counts-as-explicit, missing-symbol exit, file-not-found
  exit, unknown-key exit, default-strategy), and an end-to-end
  unknown-`--strategy` startup failure via the real `MMBot.run()`. Full
  suite: 126/126 passing; black, flake8, mypy, and pyright all clean on
  every changed file.

### Phase C — Multi-symbol mode (fallback option — see §5a)

> **Correction (v1.4.0):** this phase, as originally scoped, is not the
> only way to reach multi-symbol coverage — see §5a for a plan that gives
> `pm-mm-bot` real multi-symbol support (one process, one gateway ID)
> instead of this supervisory-wrapper approach. This phase is retained as
> the lower-effort fallback; §5a.8 says when to prefer it.

- A `pm-ai-swarm`-style **launcher**
  (`ai_trader/swarm.py` is the template — it launches one `pm-ai-trader`
  **subprocess** per bot via Python's `subprocess` module, each with its own
  gateway ID and, in swarm mode, its own single assigned symbol; it is not
  an in-process fan-out) that starts N separate `pm-mm-bot` **processes**
  (one per symbol, one gateway ID each: `MM_AAPL_01`, `MM_MSFT_01`, …) from
  one `argparse` invocation (`pm-mm-swarm --symbols AAPL,MSFT,TSLA`). Each
  `MMBot` instance keeps its own sockets, state machine, and gateway ID
  exactly as today — this is a process launcher, not a change to `MMBot`
  itself, and it does not give one gateway multiple symbols; it just saves
  typing N `pm-mm-bot` invocations by hand.
- Resolves §14.3 of the existing design doc and the "how many terminals do
  I need for a classroom" pain point that motivated it, without the larger
  `MMBot` refactor §5a describes. Worth doing regardless of whether §5a
  ships, since some classroom/ops scenarios genuinely want N independent
  gateway identities (see §5a.8).

### Phase D — Operability

- Decide, deliberately, whether v1.0.0 ships with or without: inventory
  skewing (§14.1), a position cap analogous to `pm-ai-trader`'s
  `--max-position` (§2.5), volatility-adaptive spread (§14.2), and a
  `--metrics-port` (§14.6). None of these block correctness; all of them
  affect how safe the bot is to leave running unattended in a classroom
  session for an extended period. Recommendation: ship v1.0.0 with a
  documented position cap (smallest of these to add, and the one whose
  absence has the worst unattended-failure mode — unbounded inventory
  accumulation) and defer skew/volatility/metrics to v1.1.
- Add a periodic re-request of `system.symbols_request` (or accept a
  `system.symbols_update` push, if one exists) so a mid-run change to
  `mm_max_spread_ticks`/`tick_decimals` is picked up without a bot restart,
  or explicitly document that a config change requires restarting all
  affected bots.

### Phase E — Documentation and sign-off

- Update `EduMatcher-MM-bots.md` to v2.0.0 reflecting whichever of Phases
  B–D actually ship, retire the now-answered items in its own §14, and fold
  this review's findings in as the "what changed since v1" record.
- Re-run black/flake8/mypy/pyright and the full `tests/test_mm_bot.py` suite
  (plus new tests from Phase A) as the release gate, per the project's
  standing verification requirement.

## 5a. Implementation Plan — True Multi-Symbol `pm-mm-bot`

*(Added v1.4.0.)* This section lays out what it would actually take to make
one `pm-mm-bot` process, behind one gateway ID, quote N symbols at once —
the option §2.1's correction says the engine already permits and Phase C's
swarm launcher does not attempt.

### 5a.1 Why this is possible

Every wire-level fact needed to support this was checked directly against
current source, not assumed:

- **Quotes are keyed `(gateway_id, symbol)`, not `gateway_id` alone.**
  `models/quote.py`'s `QuoteIndex._index: dict[tuple[str, str], QuoteEntry]`
  and its `_keys_by_gateway: dict[str, set[tuple[str, str]]]` both allow a
  set of symbols per gateway. Nothing rejects a second `quote.new` for the
  same gateway on a different symbol.
- **The topics `MMBot` subscribes to split into two groups**, and this
  split is exactly what makes the refactor tractable:
  - *Per-gateway* topics — `gateway_auth`, `symbols`, `quote_bootstrap`,
    `quote_legs`, `quote_ack`, `quote_status`, `order_fill`,
    `order_cancelled` (all `topic_*(gateway_id)` in
    `models/generated/{system,quote,order}.py`) — carry events for *every*
    symbol the gateway is active on, multiplexed onto one topic. The
    payload itself carries `symbol` (confirmed in
    `models/generated/order.py`, `"symbol": self.symbol` appears in every
    order/fill message builder), so demultiplexing is a matter of reading
    a field already present, not a protocol change.
  - *Per-symbol* topics — `book_snapshot(symbol)`,
    `circuit_breaker_halt/resume(symbol)` — already require one
    `SUBSCRIBE` per symbol. `make_subscriber(addr, *topics)`
    (`messaging/bus.py:107`) already accepts an arbitrary number of topics
    on one SUB socket — subscribing to N symbols' book/circuit-breaker
    topics instead of one is a longer argument list, not a new mechanism.
- **Tick-size/price-scale registration is already global and per-symbol.**
  `register_tick_decimals(symbol, tick_decimals)` /
  `to_ticks(price, symbol)` (`models/price.py`) key their cache by symbol
  already — this is the exact mechanism Phase A's bug fix (§4) plugged the
  bot into. A multi-symbol bot calling `register_tick_decimals` once per
  symbol at startup needs no change here at all.
- **`PricingStrategy` (`pricer.py`) is already a self-contained per-symbol
  unit.** One `QuotePricer` instance holds exactly one symbol's tick size,
  gap, drift threshold, and tracked mid — there is no cross-symbol state
  inside it. A dict of `{symbol: PricingStrategy}` is a direct, natural fit
  for the existing abstraction; the Protocol itself needs no changes.

In short: **one PUSH socket and one SUB socket, subscribed to a wider topic
list, are already sufficient to run N symbols behind one gateway ID.** The
entire constraint lives in `MMBot`'s own instance attributes, which are
scalars (`self.symbol`, `self._quote_id`, `self._pricer`, …) where they
would need to be per-symbol collections.

### 5a.2 What has to change in `bot.py`

Every scalar, symbol-shaped piece of `MMBot` state becomes a per-symbol
entry, most naturally as one small `_SymbolState` dataclass held in a
`dict[str, _SymbolState]` keyed by symbol, rather than scattering N parallel
dicts:

```python
@dataclass
class _SymbolState:
    tick_size: float = 0.01
    mm_max_spread_ticks: int | None = None
    gap: float = 0.0
    gap_was_explicit: bool = False
    pricer: PricingStrategy | None = None
    state: BotState = BotState.CONNECTING
    quote_id: str | None = None
    bid_order_id: str | None = None
    ask_order_id: str | None = None
    quoted_at_mid: float | None = None
    reissue_at: float | None = None
    last_quote_sent_at: float = 0.0
    last_qlegs_reconcile: float = 0.0
    awaiting_cancel_for_reissue: bool = False
    pending_fills: list[dict] = field(default_factory=list)
```

Fields that stay scalar (genuinely gateway-level, not symbol-level):
`gateway_id`, `strategy` name, `qty`/`drift_ticks`/`tif`/timeout config
(today these are shared across all symbols the bot quotes — see §5a.3 for
whether that should be overridable per symbol), `_session_state` (session
phase is exchange-wide, not per-symbol), the two sockets, and the
verbose/debug plumbing.

Mechanical consequences, by area:

- **`_setup_sockets`**: subscribe to `topic_book_snapshot(sym)` and
  `topic_circuit_breaker_halt/resume(sym)` for every symbol in
  `self.symbols`, in addition to the unchanged per-gateway subscriptions
  (those stay singular — one `gateway_id`, not N).
- **`_dispatch`**: the per-symbol topics (`book_snapshot`,
  `circuit_breaker_*`) already carry the symbol in the topic string itself,
  so routing to the right `_SymbolState` is a dict lookup by parsing it
  back out (or, cleaner, precomputing a `{topic: symbol}` reverse map at
  startup since the symbol set is fixed for the process's life). The
  per-gateway topics (`order_fill`, `order_cancelled`, `quote_ack`,
  `quote_status`) carry `symbol` in the *payload*, not the topic — for
  `order_fill`/`order_cancelled` this is a direct payload read; for
  `quote_ack`/`quote_status`, the payload does not carry `symbol` directly
  today (only `quote_id`), so the bot needs a `quote_id -> symbol` map,
  populated when a quote is sent and consulted on the matching ack/status.
  This is the one place a genuinely new piece of local bookkeeping is
  needed, not just a reshape of existing fields.
- **`_send_quote`/`_cancel_quote`/`_cancel_and_reissue`/`_clear_quote_state`**:
  become symbol-parametrized, operating on one `_SymbolState` entry;
  callers pass the symbol they mean instead of relying on `self.symbol`.
- **`_tick`**: today's single reissue-timer/heartbeat/QLEGS-reconcile check
  becomes a loop over `self._symbols.values()`, each checked against its
  own `reissue_at`/`last_qlegs_reconcile`, independently. This is
  mechanical but touches every branch in the current method.
- **`_request_symbols`**: today filters the `SYMBOLS` reply down to the one
  symbol the bot cares about; it needs to instead register
  `tick_size`/`mm_max_spread_ticks` for every symbol in `self.symbols` and
  fail startup only if *none* of them are present (see §5a.4 on whether one
  missing symbol should fail the whole bot or just that symbol).
- **`_request_bootstrap`/`_request_qlegs`/`_try_adopt_from_bootstrap`/
  `_resolve_bootstrap_reference`/`_reconcile_qlegs`**: `QBOOT`/`QLEGS`
  already accept a `SYM=` filter (per the training-chapter and protocol-doc
  review done earlier this project) — one request per symbol at startup
  (they are cheap, infrequent, and already have their own timeout), rather
  than trying to invent a bulk multi-symbol query the protocol does not
  offer. Reconciliation logic is otherwise identical, just addressed at one
  `_SymbolState` per response instead of `self`.
- **`run`/`_run_loop`**: the startup sequence (authenticate → symbols →
  gap/pricer setup per symbol → QBOOT/QLEGS per symbol → wait for session →
  initial quote per symbol) is the same shape repeated per symbol instead
  of once; session-state handling (`_handle_session_state`,
  `_handle_circuit_breaker_halt/resume`) stays mostly as-is for the parts
  that are genuinely gateway/session-wide, but the "cancel and pause" /
  "resume and reissue" actions become a loop over symbols instead of a
  single quote.

### 5a.3 CLI, config file, and gateway identity

- **`--symbol SYM` becomes `--symbols SYM[,SYM...]`**, mirroring the
  existing `pm-ai-trader --symbols AAPL,MSFT` convention
  (`ai_trader/main.py`) rather than inventing a new flag shape. Singular
  `--symbols AAPL` (one symbol) must keep working unchanged — this is an
  additive CLI change, not a breaking one, for anyone still running one
  symbol per bot.
- **`--gap`/`--qty`/`--drift-ticks` stay single values applied to every
  symbol** for the initial version — a genuinely per-symbol override syntax
  (`--gap AAPL:0.10,MSFT:0.20`, echoing `config_gen`'s `SYM:KEY=VALUE`
  convention) is a reasonable v2 addition but adds real parsing complexity
  that isn't needed to answer "can one bot quote multiple symbols" — call
  this out explicitly as deferred rather than silently missing.
- **`mm_bot/config.py`'s `_ALLOWED_KEYS`** gains `symbols` (plural) as an
  alias resolving the same way `--symbols` does; `symbol` (singular) stays
  supported for one-symbol config files already in use.
- **Gateway identity**: `MM_<SYMBOL>_<nn>` (today's `main.py:290`) has no
  sensible multi-symbol form — there is no single `<SYMBOL>` to interpolate.
  A multi-symbol bot needs an operator-chosen label instead:
  `MM_<LABEL>_<nn>` (e.g. `MM_TECH_01` for a bot quoting `AAPL,MSFT`), via a
  new `--label` flag (falls back to the first symbol if omitted, so a
  single-symbol invocation with no `--label` reproduces today's ID
  unchanged — this is the detail that keeps the change backward
  compatible). This needs a config-side decision too: the gateway still
  needs one `role: MARKET_MAKER` entry in `engine_config.yaml`, and every
  symbol it quotes needs a `market_maker_quotes` seed naming that one
  gateway ID — nothing new required there, since `market_maker_quotes` is
  already per-symbol config referencing a `gateway_id` (confirmed in the
  training-chapter review — `config_gen/builder.py`'s
  `_build_mm_quote_seed`), it just needs to name the *same* gateway ID
  under multiple symbols instead of a different gateway ID under each.

### 5a.4 Per-symbol failure isolation

This is the real design question, not a mechanical one: **should one
symbol's problem take down the whole bot, or just that symbol?** Today,
every startup failure (`auth rejected`, `no reference price`, `gap exceeds
mm_max_spread_ticks`, an unknown symbol) is fatal to the one thing the bot
does. With N symbols in one process, the options are:

1. **All-or-nothing startup** (simplest): if any symbol fails a startup
   check (missing from `SYMBOLS`, gap validation fails, no reference price
   resolvable), the whole process exits non-zero, same as today. Easiest to
   implement and reason about, worst operationally — one bad symbol name
   in a 10-symbol `--symbols` list takes down quoting for the other 9.
2. **Per-symbol degrade** (recommended): a symbol that fails its own
   startup checks is logged and excluded from `self._symbols` for the rest
   of the run — the bot proceeds quoting whichever symbols *did* pass, and
   exits non-zero only if *zero* symbols are left quotable. This mirrors
   the "fail closed at every step, but scoped to what actually failed"
   philosophy the existing single-symbol state machine already has
   (§2.4's review explicitly praised this property) — it should be
   preserved at the per-symbol level, not lost in the transition to
   multi-symbol.
3. **Runtime isolation once running**: an unhandled error path for one
   symbol (e.g. a QLEGS mismatch loop that never converges) should log and
   keep that symbol in a paused/retrying state rather than crashing the
   process and silently pulling every other symbol's live quotes down with
   it — this is arguably the single biggest operational argument *for*
   option 2's degrade-not-crash posture over option 1.

Recommendation: implement option 2. It costs a bit more code (the loop
bodies in §5a.2 need a try/except boundary per symbol instead of one
top-level fail-fast return) but it is the behavior an operator running a
multi-symbol MM bot unattended would actually want, and it is a direct,
foreseeable consequence of moving from "one thing to keep alive" to "N
independent things sharing a process."

### 5a.5 Staged implementation steps

1. Introduce `_SymbolState` and refactor `MMBot.__init__`/all the
   attributes listed in §5a.2 to hold `dict[str, _SymbolState]` — with the
   bot still constructed for exactly one symbol, so this step is a pure
   refactor with **no behavior change**, verifiable against the full
   existing `tests/test_mm_bot.py` suite (120 tests) unmodified.
2. Extend `_setup_sockets`/`_dispatch`/`_tick` to loop over
   `self._symbols` instead of assuming one entry — still driven by a
   single-symbol CLI invocation, so still no behavior change, but now
   exercising the loop machinery with N=1.
3. Add the `quote_id -> symbol` map for demultiplexing `quote_ack`/
   `quote_status` (the one genuinely new piece of state from §5a.2).
4. Land `--symbols` (plural) in `main.py` and `mm_bot/config.py`, plus
   `--label` for gateway identity, keeping `--symbol` (singular) as a
   backward-compatible alias.
5. Implement per-symbol startup degrade (§5a.4 option 2) and the
   process-level "exit non-zero only if zero symbols survived startup"
   check.
6. Update `docs/user-guide/100-mm-bot.md` (a new "Multi-symbol mode"
   section, CLI table row for `--symbols`/`--label`, an updated
   architecture diagram) and the training chapters that reference
   `pm-mm-bot` (`docs/training/020-setting-up-MM-bots.md`,
   `210-automation-commandclient-mm-bot.md`) to show a single multi-symbol
   invocation as an alternative to N single-symbol processes.

### 5a.6 Testing

- Every existing single-symbol test in `tests/test_mm_bot.py` must keep
  passing unmodified through steps 1-2 above — this is the regression
  safety net for the refactor itself.
- New coverage needed: N=2 startup (both succeed), N=2 startup with one
  symbol failing gap validation (confirm the other still quotes, per
  §5a.4), a fill on symbol A's leg while symbol B has an independent
  in-flight cancel (confirming no cross-symbol state leakage — this is
  exactly the class of bug `TestFillDuringCancelInFlight` already guards
  against for the single-symbol case, so the multi-symbol equivalent
  should follow the same pattern), independent drift-triggered reprice on
  one symbol while the other is idle, and independent QLEGS-reconciliation
  divergence on one symbol while the other's quote is untouched.
- `tests/test_mm_bot_config.py` needs the `--symbols`/`symbols:` plural
  form and the `--label` flag added to its config-file coverage.

### 5a.7 What this does *not* change

- No engine change of any kind — everything in §5a.1 already works today.
- No protocol/message-schema change — `quote.new`/`quote.cancel` already
  take `symbol` per call; the bot just calls them more than once per
  process now.
- `QBOOT`/`QLEGS` usage pattern is unchanged in shape (one request per
  symbol, same as today's one request for the bot's one symbol) — just
  issued N times at startup instead of once.

### 5a.8 Relationship to Phase C

Phase C's swarm-of-processes launcher is not obsoleted by this plan — the
two solve different problems:

- **§5a (this section)** gives *one gateway identity* multiple symbols.
  Use it when the goal is genuinely fewer processes/gateways to manage, or
  when the classroom/production scenario wants to model a single MM
  session quoting a whole sector, the way a real exchange participant
  would.
- **Phase C** gives *N gateway identities*, each still one symbol, just
  launched together. Use it when the scenario specifically wants N
  independently-attributable market makers (e.g. teaching self-match
  prevention or per-gateway risk controls, where having a *different*
  `gateway_id` per symbol is the point, not a limitation to work around).

Both are legitimate; §5a is the answer to "why can't one bot do what one
real MM session does," and Phase C remains the answer to "I want N
independent bot identities without typing N commands by hand."

## 6. Explicitly Out of Scope for v1.0.0

To keep the above phased and shippable, the following are named as
deliberately deferred rather than silently dropped:

- Coordination between multiple same-symbol MM instances (§14.5) — the
  existing design doc already judges this added complexity not worth it for
  educational use, and this review agrees; revisit only if a classroom
  scenario actually needs two bots quoting the same symbol simultaneously.
- Any *new* `quote_refresh_policy` value or semantics (e.g., a policy that
  deliberately keeps a surviving *sibling* leg resting after a partial
  fill) — that is a genuine engine-side design question independent of the
  bot. **This is distinct from §4 item 3** (fixed in v1.3.0), which was a
  bug in the existing `INACTIVATE_ON_ANY_FILL` policy's implementation (the
  *hit* leg's own partial remainder was never cancelled by the reissue,
  regardless of what any new policy might decide about the sibling) — that
  was a correctness gap to close, not a request for new policy semantics.
