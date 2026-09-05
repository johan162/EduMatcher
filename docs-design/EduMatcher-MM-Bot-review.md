Version: 1.0.0

Date: 2026-09-05

Status: Review — for discussion

# EduMatcher — Market-Maker Bot Functional Review (pm-mm-bot)

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

**One instance quotes exactly one symbol.** `MMBot.__init__` takes a single
`symbol: str` (`bot.py:77`), and the class docstring says so directly:
"Autonomous market-maker bot for **a single symbol**" (`bot.py:71`). The CLI
(`main.py:29-31`) requires exactly one `--symbol`. To make markets in three
symbols today you run three OS processes, each with its own gateway ID
(`MM_AAPL_01`, `MM_MSFT_01`, `MM_TSLA_01` — see §9.1 of the design doc).

The design doc already flags this as a known limitation, not an oversight:
§14.3 "Multi-Symbol Mode" proposes a future `--symbols AAPL,MSFT,TSLA` mode
"similar to how `pm-ai-swarm` manages multiple single-trader bots" — and that
sibling process already exists and does exactly this pattern for the AI
trader (`src/edumatcher/ai_trader/swarm.py` fans out one `AITraderBot` per
symbol inside one process). That is the template to reuse rather than
inventing a new supervision model (see §5, Phase C).

### 2.2 Config file vs. CLI options for strategy selection

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

**The exchange cancels the sibling leg, not the bot — and the bot always
re-quotes both sides together; it never leaves one leg resting alone.**
Tracing the actual message flow:

1. A fill on either leg is reported by the **engine**, not decided by the
   bot. `quote_refresh_policy: INACTIVATE_ON_ANY_FILL` (configured per
   gateway, §9.2 of the design doc) means the engine's fill handler pulls
   the *entire* quote — both legs — out of its internal `QuoteIndex` and
   explicitly cancels the sibling order itself. The bot is a passive
   recipient of `order.fill.{GW}` and `quote.status.{GW}
   status=INACTIVE_BID_FILLED`/`INACTIVE_ASK_FILLED`.
2. On seeing `INACTIVE_*_FILLED` (`bot.py:550-556`), the bot clears its
   local quote/leg state (`_clear_quote_state()`) and arms a reissue timer
   `reissue_delay_ms` (default **200 ms**) in the future. It does **not**
   send a `quote.cancel` on this path — one isn't needed, because the
   engine has already torn down both legs.
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
   explicit cancel there is defensive, not load-bearing.

**Typical timing:** fill → `quote.status` → **~200 ms** (`--reissue-delay-ms`,
configurable) → fresh two-sided `quote.new` → `quote.ack`. That is the
whole one-sided gap in the normal case. The cancel-first paths (drift
reprice, heartbeat recovery) that *do* wait for a `quote.cancel`
confirmation are bounded by `--cancel-timeout-sec` (default **1.0 s**); if no
confirmation arrives in that window, `_tick()` forces the local state clear
and reissues anyway (`bot.py:702-708`), so the bot can never wait
indefinitely on a lost cancel ack. Net: the bot is out of the market for at
most ~200 ms after an ordinary fill, and for at most ~1 s in the (rarer)
drift/heartbeat-recovery paths.

One nuance worth flagging: **while quoting normally, a fill is one-sided by
definition** (only the leg that got hit fills), but the *engine* inactivates
the untouched sibling leg too, so "the bot cancels the other leg" is not
quite accurate framing — the bot never has to, because the exchange enforces
"filled or nothing" for MM quotes under `INACTIVATE_ON_ANY_FILL`. If the
project ever wants a policy where the surviving leg stays resting after a
partial fill on the other side, that would be a new `quote_refresh_policy`
value on the engine, not a bot change.

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

No other functional defects were found; the fill/cancel/reissue races that
were previously bugs (dropped ack, orphaned `CANCELLED`, overwritten cancel
timeout, malformed book `KeyError`, uncaught `QuotePricer` `ValueError`) are
all fixed per the CHANGELOG and covered by dedicated regression tests.

## 5. Plan to v1.0.0

### Phase A — Correctness fixes (blocking)

- Add the missing `register_tick_decimals()` call in `_request_symbols()`
  (§4.1). Add a regression test asserting `to_ticks()` uses the bot's own
  registered scale even when no other process has registered the symbol
  first (construct the test so the global registry starts empty for that
  symbol).
- Correct the stale `pm-config-gen` note in §9.2 of
  `EduMatcher-MM-bots.md` (§4.2).

### Phase B — Config-file strategy support

- Introduce a `StrategyConfig` YAML schema (`strategy: symmetric | ...` plus
  per-strategy parameters) and a `--config PATH` flag, with CLI flags
  continuing to override config-file values for the fields they both cover.
  Keep `symmetric` (the current, only strategy) as the default so existing
  CLI-only invocations keep working unchanged.
- Refactor `pricer.py`'s `QuotePricer` interface (`update_mid`/`set_mid`,
  `compute_prices`, `has_drifted`) into a small `Strategy` protocol so a
  second strategy class can be added later without touching `bot.py`'s
  state machine.
- This directly resolves §14.4 of the existing design doc and unblocks
  §2.6's answer above (skewed/volatility-adaptive strategies become new
  pricer classes, not state-machine changes).

### Phase C — Multi-symbol mode

- Port the `pm-ai-swarm` supervision pattern
  (`ai_trader/swarm.py`) to run N `MMBot` instances (one per symbol) inside
  one OS process, sharing one `argparse` invocation
  (`--symbols AAPL,MSFT,TSLA`). Each `MMBot` instance keeps its own
  sockets, state machine, and gateway ID exactly as today — this is a
  supervisory wrapper, not a change to `MMBot` itself.
- Resolves §14.3 of the existing design doc and the "how many terminals do
  I need for a classroom" pain point that motivated it.

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

## 6. Explicitly Out of Scope for v1.0.0

To keep the above phased and shippable, the following are named as
deliberately deferred rather than silently dropped:

- Coordination between multiple same-symbol MM instances (§14.5) — the
  existing design doc already judges this added complexity not worth it for
  educational use, and this review agrees; revisit only if a classroom
  scenario actually needs two bots quoting the same symbol simultaneously.
- Any change to the engine's `quote_refresh_policy` semantics (e.g., a
  policy that keeps a surviving leg resting after a partial fill) — that is
  an engine-side design question independent of the bot, and no evidence
  from this review suggests the current `INACTIVATE_ON_ANY_FILL` behavior is
  wrong for the bot's intended use.
