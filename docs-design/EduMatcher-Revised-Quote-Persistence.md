Version: 0.1.0

Date: 2026-09-02

Status: Design Proposal — not implemented

# EduMatcher — Revised Quote Persistence Across Engine Restarts


## Table of Contents

1. [Overview](#1-overview)
2. [Problem Statement](#2-problem-statement)
3. [Current Behaviour — Root-Cause Analysis](#3-current-behaviour--root-cause-analysis)
4. [Desired Behaviour](#4-desired-behaviour)
5. [Proposed Design](#5-proposed-design)
6. [Risky Changes and Mitigations](#6-risky-changes-and-mitigations)
7. [Implementation Plan](#7-implementation-plan)
8. [Differences From Real Market Makers](#8-differences-from-real-market-makers)
9. [Alternative: Rely on pm-mm-bot Instead of Persistence](#9-alternative-rely-on-pm-mm-bot-instead-of-persistence)
10. [Recommendation](#10-recommendation)
11. [Open Questions](#11-open-questions)


## 1. Overview

Config-seeded market-maker (MM) quotes appear in the book on the first,
fresh start of the exchange (`market_maker_quotes:` in `engine_config.yaml`),
exactly as documented. After a restart, they are gone: the book opens with
no MM liquidity at all, even though nothing about the quotes looked
"cancelled" before shutdown.

This is not a bug in the sense of a broken code path — every piece of it
behaves exactly as commented and exactly as documented in
`docs/user-guide/180-persistence.md`. It is two independently-reasonable
design decisions that combine into a result nobody would design on purpose:
quote legs are (a) seeded with `TIF=DAY` by default and excluded from GTC
persistence regardless of TIF, while (b) the re-seed-on-startup mechanism
that would otherwise replace them is suppressed once the symbol has any
trading history. This document analyses why, proposes a revised design that
makes quotes behave as implicitly-GTC resting liability (survive restart,
minus whichever leg was hit), and evaluates whether turning on `pm-mm-bot`
would make the code change unnecessary.


## 2. Problem Statement

Observed behaviour:

1. Fresh start of the exchange with the default three-symbol
   `engine_config.yaml`: MM quotes from `market_maker_quotes:` appear in the
   book, as expected.
2. Restart the exchange (clean shutdown, `Ctrl-C`, then restart): the MM
   quotes are gone. The book opens empty on the MM side.

Question raised: shouldn't book-state persistence save quotes as `TIF=GTC`,
or is something explicitly deciding to drop them at restart?

Answer, established in this document's analysis: quotes are *not* persisted
regardless of their `TIF`, and the mechanism designed to replace that gap
(re-seeding from config on every startup) silently no-ops once the symbol
has book statistics on file — which happens after the very first run. The
result is a book that is only ever seeded once per data directory, unless an
operator manually deletes `book_stats.json`.


## 3. Current Behaviour — Root-Cause Analysis

Three pieces of code, each defensible in isolation, combine to produce the
observed result.

### 3.1 MM seed quotes default to `TIF=DAY`

`MMQuoteSeed` (`src/edumatcher/engine/config_loader.py`) defines:

```python
@dataclass
class MMQuoteSeed:
    gateway_id: str
    bid_price: float
    ask_price: float
    bid_qty: int
    ask_qty: int
    tif: TIF = TIF.DAY
    quote_id: str | None = None
    seed_once: bool = True  # skip injection when book_stats already has an
                             # entry for this symbol
```

Unless an operator explicitly writes `tif: GTC` on every
`market_maker_quotes` entry, seeded quotes are `TIF=DAY`. On a clean
shutdown, `Engine._shutdown()` expires every resting `TIF=DAY` order —
including the MM quote legs — publishing `order.expired` for each. This
alone would explain why quotes vanish on restart, independent of the second
issue below.

### 3.2 Quote-origin orders are unconditionally excluded from GTC persistence

Even if an operator sets `tif: GTC` on the seed quotes, both persistence
paths explicitly filter out `origin == OrderOrigin.QUOTE`:

```python
# _resting_gtc_orders() — periodic checkpoint
def _resting_gtc_orders(self) -> list[Order]:
    """GTC orders that should survive a restart.

    Quote legs are excluded: they are re-seeded from config on every
    startup, so persisting them accumulates duplicates across restarts.
    """
    resting: list[Order] = []
    for book in self.books.values():
        for order in book.resting_orders():
            if order.tif == TIF.GTC and order.origin != OrderOrigin.QUOTE:
                resting.append(order)
    return resting
```

```python
# _shutdown() — same exclusion, inline
for order in book.resting_orders():
    if order.tif == TIF.GTC:
        if order.origin == OrderOrigin.QUOTE:
            # Quote legs are re-seeded from config on every startup;
            # do not persist them or they accumulate across restarts.
            continue
        all_resting.append(order)
```

This is documented as intentional in `docs/user-guide/180-persistence.md`:
config-seeded quotes are meant to be re-injected fresh on every startup, not
carried forward as saved state. The stated rationale — avoiding duplicate
quotes on restart — is real: it is exactly the problem the user solved once
already (see §3.3) and would reappear if this exclusion were simply deleted
without also changing §3.3's gate.

### 3.3 `seed_once` gates on `book_stats`, not on live quote state

The startup re-seed loop (`Engine._load_config()`, inside the
`market_maker_quotes` injection block in `src/edumatcher/engine/main.py`):

```python
for sym, sym_cfg in self._engine_config.symbols.items():
    for idx, quote_seed in enumerate(sym_cfg.market_maker_quotes, start=1):
        # seed_once: skip injection if this symbol already has a book_stats
        # entry, meaning it has been started at least once before.
        if quote_seed.seed_once and sym in stats:
            log.info(
                f"Skipping seed quote for {sym} "
                f"(seed_once=true, symbol has prior history)"
            )
            continue
        ...
```

`stats` here is `book_stats.json` — last buy/sell price and previous close,
persisted on every clean shutdown. This file gets an entry for a symbol the
moment any trade has been recorded against it, which typically happens
during the very first run (the seeded quotes themselves can cross a trader
order, or the auction uncross can print a trade). From the second run
onward, `sym in stats` is true, `seed_once` (default `True`) is true, and
the seed loop skips the symbol — permanently, until `book_stats.json` is
deleted by hand.

### 3.4 The combination

- Run 1: no `book_stats` entry yet → quotes seed from config. Correct,
  matches what the user observed.
- Shutdown: quotes are `TIF=DAY` (§3.1) → expired. Even if `TIF=GTC`, they
  are excluded from the GTC file regardless (§3.2).
- Run 2: `book_stats` now has an entry for the symbol (§3.3) → `seed_once`
  skips re-seeding. Nothing restores the quotes, because nothing saved them
  and nothing re-seeds them either. Net result: permanently empty MM side
  after the first restart.

Each of the three pieces has a documented, sensible reason to exist in
isolation:

- Defaulting to `TIF=DAY` is a reasonable default for "one-time bootstrap
  liquidity," matching a primary-market opening auction seed.
- Excluding quote-origin orders from GTC persistence prevents duplicate
  quotes if the *old* re-seed-every-startup model were still in force
  unconditionally.
- Gating re-seed on `book_stats` presence was the actual fix for that
  duplicate-quote problem, added after quotes were briefly persisted as
  ordinary GTC orders and then re-seeded on top of themselves.

But stacked together, they leave no path by which an MM quote — bootstrap or
otherwise — is present in the book after the first restart, which was never
the intent of any of the three individual decisions.


## 4. Desired Behaviour

Stated goals, as agreed in discussion, restated precisely:

1. **`seed_once` bootstrap semantics are correct and should be kept.** The
   config-seeded quote is an optional, one-time "IPO" bootstrap — its job is
   to give a symbol its very first price when the book has no other
   history. It should not re-fire on every restart once the symbol is live.
2. **A quote that is still active (untouched) at shutdown should survive a
   restart**, i.e. quote legs should be treated as implicitly `TIF=GTC`
   resting exposure, the same category as any other resting GTC order.
3. **If one leg of a quote has been hit, only the hit-and-not-yet-replaced
   state should carry forward** — normal MM principle: a filled side is
   gone, the un-hit side either follows it (per `quote_refresh_policy`) or
   remains resting, but a *stale* untouched two-sided quote should not
   reappear as if nothing happened.

This is explicitly a simplification relative to a real exchange, where MMs
requote within milliseconds and "what does a quote look like mid-restart"
is not really an observable question. For a teaching exchange with
human-scale restart cadence, treating quotes as durable resting state and
letting the existing in-session inactivation logic (§3's sibling-cancel on
fill) do the rest is the easiest model to explain and reason about.


## 5. Proposed Design

### 5.1 Summary of the change

Stop treating quote-origin orders as categorically unpersistable. Instead,
persist them by the same rule as any other order: **`TIF=GTC` resting
orders survive shutdown; `TIF=DAY` orders expire.** Quote legs simply join
that existing rule instead of being a special case. Two supporting changes
are required to make that safe: restoring the in-memory `QuoteIndex` on
startup, and changing what `seed_once` checks.

### 5.2 Persistence: remove the `origin == QUOTE` exclusion, condition on TIF only

In both `_resting_gtc_orders()` and `_shutdown()`
(`src/edumatcher/engine/main.py`), remove the `origin != OrderOrigin.QUOTE`
/ `origin == OrderOrigin.QUOTE: continue` branches. The remaining condition
— `order.tif == TIF.GTC` — is then sufficient and uniform for all order
origins.

Practical consequence: an MM quote leg persists across restart *only if*
its `MMQuoteSeed.tif` (or the `tif` a live `quote.new` was sent with) is
`GTC`. A `TIF=DAY` seeded quote keeps today's behaviour exactly — it
expires at shutdown and is gone until re-seeded. This is deliberate: it
keeps the meaning of `TIF=DAY` uniform across the whole system (quotes
included) rather than adding a second, quote-specific durability rule.
Operators who want quotes to survive restarts set `tif: GTC` on the
`market_maker_quotes` entry; operators who want the old one-shot-bootstrap
behaviour leave the default `TIF=DAY` in place, and now get exactly what
that TIF has always meant.

### 5.3 Startup: rebuild `QuoteIndex` from restored quote-origin orders

`_restore_gtc()` currently calls `book.process(order, match=False)` and
updates `self._order_symbol`, but never touches `self._quote_index`. Once
quote legs can appear in the restored GTC set, this must change: a restored
order with `origin == OrderOrigin.QUOTE` and a `quote_id` needs a
`QuoteEntry` reconstructed and inserted into `self._quote_index`, or the
order rests in the book as a phantom that `QuoteIndex`-mediated logic (a new
`quote.new` replacing it, `QLEGS`, `_on_quote_leg_filled`'s
inactivate-sibling-on-fill behaviour) cannot see or manage.

Restoration procedure per symbol:

1. After the existing per-order restore loop in `_restore_gtc()`, group the
   just-restored orders that carry `origin == OrderOrigin.QUOTE` by
   `(gateway_id, quote_id)`.
2. For each group with exactly one bid leg and one ask leg, construct a
   `QuoteEntry(quote_id=..., gateway_id=..., symbol=..., bid_order_id=...,
   ask_order_id=...)` and `self._quote_index.put(entry)`.
3. For each group with only one leg present (the sibling was filled, or
   filtered out by the removed-symbol skip, or lost to a corrupt record —
   see §6.3), do **not** insert a `QuoteEntry`. Log at `INFO` that a
   single-leg quote remnant was restored as a plain resting order for
   `gateway_id`/`symbol`/`quote_id`, and leave it resting exactly as any
   other lone GTC order would. This is consistent with "only the hit leg
   survives" (goal 3): the surviving leg keeps trading as ordinary resting
   liability, it is simply no longer *quote-managed* (no automatic
   sibling-cancel, no `QLEGS` visibility as an active quote) because there
   is no sibling left to manage it against.

### 5.4 `seed_once`: gate on live quote presence, not `book_stats`

Change the condition in the seed-injection loop from `sym in stats` to a
check against the *reconstructed* `_quote_index` (post §5.3, before the
seed loop runs — ordering matters, see §6.1): specifically, "does this
`(gateway_id, symbol)` pair already have an active `QuoteEntry`."

```python
already_has_quote = self._quote_index.get(quote_seed.gateway_id, sym) is not None
if quote_seed.seed_once and already_has_quote:
    log.info(
        f"Skipping seed quote for {sym}/{quote_seed.gateway_id} "
        f"(seed_once=true, an active quote was restored)"
    )
    continue
```

This is the semantic fix that actually closes the gap the user identified.
Previously "has prior history" was approximated by "has book stats," which
becomes permanently true after the first trade and never becomes false
again — so a symbol whose quote later got fully hit and removed (a
perfectly normal, expected event) could never receive a fresh bootstrap
quote again without manual intervention. Gating on the *quote itself* fixes
this: if the quote is gone (hit through, cancelled, or never restored
because it was `TIF=DAY`), `seed_once` correctly allows a fresh seed;
if the quote survived the restart, `seed_once` correctly declines to
duplicate it. `book_stats` remains exactly as useful as before for its
original purpose (`last_buy_price`/`last_sell_price`/`prev_close` for
collars and circuit breakers) — this change only touches what `seed_once`
reads.

### 5.5 No change to in-session fill/inactivation behaviour

`_on_quote_leg_filled()` already implements goal 3 for the live-trading
case: under the default `INACTIVATE_ON_ANY_FILL` policy, the moment one leg
of a quote is hit, the sibling leg is cancelled and the quote is marked
`INACTIVE_BID_FILLED`/`INACTIVE_ASK_FILLED` in the same event — there is no
window in normal operation where a stale two-sided quote with one dead leg
sits resting. This logic needs no change; §5.3's "single leg only" case
exists for restore-time bookkeeping (a leg persisted as `GTC`, its sibling
already gone from disk before shutdown because it was never GTC or was
already cancelled), not for anything that happens mid-session.

The policies where a leg genuinely can be resting alongside a filled
sibling — `INACTIVATE_ON_FULL_FILL` (only a *fully* filled leg triggers
inactivation; a partial fill leaves both legs live) and
`NEVER_INACTIVATE` — are unaffected by this proposal beyond the ordinary
consequence of §5.2: whatever is resting at shutdown persists if `GTC`,
exactly like it would for a manually-placed order under the same policy.

### 5.6 Documentation update

`docs/user-guide/180-persistence.md` currently states, as a documented
guarantee, that quote legs are never persisted and are always re-seeded
fresh. That guarantee is being replaced by a narrower, TIF-conditioned one.
The "At Shutdown" / "At Startup" sequence description and the callout box
under "What is deliberately not persisted" both need rewriting to describe
the new rule (§5.2–§5.4) rather than blanket exclusion. This is a
documentation-only workpackage (§7) — no code risk, but it is a correctness
requirement: the current text would be actively wrong after this change
ships.


## 6. Risky Changes and Mitigations

### 6.1 Startup ordering: `QuoteIndex` rebuild must happen before the `seed_once` check

`_restore_gtc()` runs before `_load_config()` (existing M4 ordering
constraint, preserved for tick-decimal registration). The seed-injection
loop lives inside `_load_config()`. This is actually the ordering the
revised design needs — restore first, seed-decision second — but it is
easy to get backwards during implementation (e.g. by moving seed logic
earlier for some unrelated reason) and silently reintroduce the duplicate-
quote bug `seed_once` was invented to prevent.

*Mitigation:* add an explicit assertion/comment at the top of the seed
loop noting the ordering dependency, and a regression test
(§7, workpackage 3) that starts the engine twice in sequence against the
same data directory with a `TIF=GTC` seeded quote and asserts exactly one
`QuoteEntry` exists for the symbol after the second startup — not two, not
zero.

### 6.2 A restored quote leg can cross a freshly-seeded quote on startup

Per `180-persistence.md`'s existing startup sequence, MM seeds are injected
*before* any gateway connects, and if a restored GTC order already crosses
a seed price, a trade executes immediately during startup, before any
participant has dialled in. Today this can only happen between a *trader's*
restored GTC order and a freshly-seeded MM quote. After this change, it can
also happen MM-vs-MM: a restored quote leg from gateway A crossing a
newly-seeded (because `seed_once` allowed it — e.g. gateway A's quote was
only partially restored, see §6.3) quote from gateway B.

*Mitigation:* this is not a new failure mode, just a new pair of
counterparties hitting an existing one. The existing trade-at-startup
behaviour already publishes the trade normally and is exercised by current
tests (`test_engine_durability.py`,
`test_persistence_roundtrips.py`). Extend those with one case covering
MM-quote-vs-MM-quote crossing at startup, and add one sentence to
`180-persistence.md` noting the seed-vs-restored-quote crossing case
explicitly (it is currently phrased only in terms of "a restored GTC
order").

### 6.3 Orphaned single-leg quote records

A `quote_id`'s bid and ask legs are always created and (previously) would
have been discarded together — but going forward they are *persisted*
together as two independent `Order.to_dict()` entries in one JSON list.
Nothing currently guarantees both survive to the next startup as a pair:

- The `_allowed_symbols` skip in `_restore_gtc()` operates per-order, so a
  symbol removed from config between restarts could drop one leg and not
  the other in a pathological edit — not the two-legs-from-one-quote case,
  but worth noting since both legs share a symbol so this specific scenario
  cannot actually split a pair. Not a real risk; recorded here to rule it
  out explicitly rather than leave the reader wondering.
- The "guard each order so one bad record cannot abort engine startup"
  behaviour in `_restore_gtc()` (per-order `try/except` around
  `book.process`) genuinely can drop one leg and keep the other, if one
  leg's record is individually corrupt.
- A crash between the periodic `_flush_persistence()` checkpoint writing
  `gtc_orders.json` and a hypothetical *separate* write is not a real risk
  here — both legs are entries in the *same* list, written by one call to
  `save_gtc_orders()`, which uses the existing atomic
  write-to-temp-then-`os.replace` path. Either both legs are in the file or
  neither is; there is no window where only one leg of an unmodified pair
  is written.

*Mitigation:* §5.3 already specifies the behaviour for this case — restore
the surviving leg as an ordinary (non-quote-managed) resting order, log it,
and do not attempt to insert a one-legged `QuoteEntry`. This needs a
dedicated test (§7, workpackage 4) constructing a `gtc_orders.json` with a
deliberately single-legged quote-origin order and asserting: the order
still rests in the book, `self._quote_index.get(...)` returns `None` for
that `(gateway_id, symbol)`, and startup does not raise.

### 6.4 `NEVER_INACTIVATE` combined with GTC persistence is a new durable steady-state

Under `quote_refresh_policy: NEVER_INACTIVATE`, a partially-filled leg can
now persist and accumulate across many restarts (it never gets cancelled by
`_on_quote_leg_filled`, and it is `GTC` so it survives shutdown). This was
possible for one continuous run before; it is now possible indefinitely
across restarts. This is very likely the *intended* consequence of treating
quotes as implicitly GTC, not a bug — but it is a new operational
characteristic worth calling out explicitly in the gateway-configuration
documentation (`090-market-maker.md`, where `quote_refresh_policy` is
documented) so an instructor configuring `NEVER_INACTIVATE` for a class
exercise understands the quote's remaining quantity is now durable state,
not reset by restarting the exchange between sessions.

*Mitigation:* documentation only (§7 workpackage 6). No code change beyond
what §5 already specifies — flagging it here because it is a behavioural
change an operator could be surprised by, even though the code doing it is
correct per the design.

### 6.5 Backward compatibility of `gtc_orders.json` across the change

Before this change, `gtc_orders.json` written by a given engine version
never contains `origin == QUOTE` entries. After this change, it can. An
older engine binary reading a newer file is unaffected (it already
filters/ignores fields it doesn't specifically restore beyond what
`Order.to_dict()`/`from_dict()` round-trip; quote-origin orders it restores
would simply rest as ordinary orders, since the old `_restore_gtc()` never
special-cased `origin` on read — only `_shutdown()`/`_resting_gtc_orders()`
special-cased it on write). A newer engine reading an older file (no
quote-origin entries) is trivially fine — nothing to restore, falls through
to normal `seed_once` seeding as it does today. No migration is needed.

*Mitigation:* none required beyond noting it; flagged for completeness
since the project's persistence file format has no explicit version field
and this is exactly the kind of change a version field would normally
gate — worth a one-line confirmation in the PR description rather than a
schema change, per the "minimum code that solves the problem" project
convention.


## 7. Implementation Plan

Each workpackage is independently mergeable and independently testable —
sized so a single work session can complete one, run the full check suite
(`black`, `flake8`, `mypy`, `pyright`, plus the relevant `pytest` files),
and stop in a working state.

**WP1 — Persist quote-origin GTC orders (§5.2)**
Remove the `origin != OrderOrigin.QUOTE` filter from `_resting_gtc_orders()`
and the `origin == OrderOrigin.QUOTE: continue` branch from `_shutdown()`.
*Verify:* a new/extended test in `test_engine_durability.py` — place a live
`quote.new` with `tif=GTC`, trigger `_shutdown()`, assert the quote's two
legs appear in the saved `gtc_orders.json` with `origin=QUOTE`. A
companion case confirms a `TIF=DAY` quote is still excluded (expired, not
saved) — unchanged from today.
*Note:* at this point restored quote legs rest in the book but are **not**
yet reachable through `_quote_index` — WP2 closes that gap. Land WP1 and
WP2 together if a genuinely atomic PR is preferred; they are listed
separately here only because they are independently reviewable and touch
different methods.

**WP2 — Rebuild `QuoteIndex` on restore (§5.3)**
Extend `_restore_gtc()` to group restored quote-origin orders by
`(gateway_id, quote_id)` and populate `self._quote_index`, per the
two-leg/one-leg handling in §5.3.
*Verify:* extend `test_persistence_roundtrips.py` — restore a two-legged
persisted quote, assert `self._quote_index.get(gateway_id, symbol)` returns
a `QuoteEntry` with matching `bid_order_id`/`ask_order_id`; a second case
restores a single surviving leg and asserts no `QuoteEntry` is created
(§6.3's test) while the order itself still rests in the book.

**WP3 — Change `seed_once` gate to live-quote presence (§5.4)**
Replace `sym in stats` with the `self._quote_index.get(...)` check in the
seed-injection loop.
*Verify:* the ordering regression test from §6.1 — two sequential engine
starts against one data directory with a `TIF=GTC`, `seed_once: true`
quote: after start 1, one `QuoteEntry` exists; after start 2 (restore, no
re-seed), still exactly one, with the *same* `bid_order_id`/`ask_order_id`
as before restart (proves it was restored, not re-seeded on top). A third
start after manually cancelling the quote (simulating "fully hit and
removed") asserts the seed *does* fire again, closing the original gap.

**WP4 — Startup crossing and corrupt-record edge cases (§6.2, §6.3)**
Add the MM-vs-MM startup-crossing test and the single-leg-corrupt-record
test described in those sections.
*Verify:* tests pass; no change to production code expected in this WP
unless WP1–WP3 review surfaces a gap.

**WP5 — Update `180-persistence.md`** (§5.6)
Rewrite the "At Shutdown"/"At Startup" numbered sequences and the "What is
deliberately not persisted" callout to describe the TIF-conditioned rule.
Add the one-sentence startup-crossing note from §6.2.
*Verify:* doc build (`mkdocs build` or the project's existing doc-build
check) passes; a human read-through against WP1–WP4's actual behaviour.

**WP6 — Update `090-market-maker.md`** (§6.4)
Add the `NEVER_INACTIVATE`-plus-restart-durability note.
*Verify:* doc build passes.

**WP7 — Full-suite verification**
Run `black`, `flake8`, `mypy`, `pyright` across the touched files, and the
full `pytest` suite (not just the new/extended files) to catch any
incidental interaction with existing GTC-restore, `QLEGS`, or `QBOOT`
tests that assumed quote-origin orders never appear in the persisted file.

Suggested sequencing: WP1 → WP2 → WP3 → WP4, each as its own commit/PR;
WP5–WP6 can land alongside WP4 or immediately after; WP7 gates the final
merge.


## 8. Differences From Real Market Makers

This design is an explicit simplification, and it is worth being clear
about where it departs from a real exchange rather than let it pass as
"realistic":

- **Requoting cadence.** A real MM's quoting engine reprices continuously —
  typically sub-millisecond to low-millisecond — in response to market data,
  inventory, and risk limits. "What was the quote at the instant of an
  exchange restart" is not a meaningful question on a real venue, because
  restarts of MM infrastructure and matching infrastructure are
  independently redundant and failover is designed to be invisible at that
  timescale. In EduMatcher, restarts happen at human/classroom cadence
  (seconds to minutes), so "what does the book look like right after
  restart, before anyone reconnects" is an observable, teachable state —
  which is exactly why this design bothers to define it carefully.
- **Persistence of quotes at all.** A real matching engine does not persist
  "market maker quotes" as a distinct category of durable state the way
  this design does — a real MM's quotes are just that MM's live orders, and
  if the MM's own systems and the exchange's matching engine are both up,
  the quote simply continues to exist; if the MM's systems are down, no
  amount of exchange-side persistence brings its quoting *intent* back,
  only its last-known resting orders (and many real venues actively purge
  a disconnected MM's resting quotes rather than leave them exposed — see
  `disconnect_behaviour: CANCEL_QUOTES_ONLY` already in this codebase,
  which mirrors that). This design's choice to persist quote legs as
  ordinary GTC state on the *engine* side is a stand-in for "the MM's own
  system would have kept them alive," acceptable here because the
  `pm-mm-bot` process is optional and the exchange needs to model a
  sensible restart in its absence (§9 examines the alternative directly).
- **Single-leg quote remnants.** A real MM would never leave a naked
  filled-through leg sitting as an ordinary resting order for the class of
  time this design allows between a fill and the next `pm-mm-bot`
  heartbeat/QLEGS reconciliation (up to 15s by default, see §9.3) — that
  exposure is the entire reason automated MM systems exist. This design
  accepts that window as pedagogically fine (it is, in fact, a good
  demonstration of why `quote_refresh_policy` and reissue delay matter) but
  it is a real behavioural gap from production MM systems, not merely a
  timing detail.
- **"IPO bootstrap"** (`seed_once`) has no real analogue as a config file at
  all — a real listing's opening reference price comes from a formal price
  discovery/book-building process (e.g. an underwriter-led auction), not a
  hardcoded YAML price. Modelling it as a one-shot seed is a deliberate and
  reasonable simplification for teaching purposes and this document does
  not propose changing that.


## 9. Alternative: Rely on pm-mm-bot Instead of Persistence

### 9.1 The question

If `pm-mm-bot` were running continuously alongside the engine, would it
notice an empty book after an engine restart and re-insert a quote on its
own — making the persistence changes in §5 unnecessary?

### 9.2 Two distinct restart scenarios

**Scenario A — bot restarts together with the engine** (e.g. both run under
the same `docker compose`/supervisor and both bounce). This is the
straightforward case and the one the bot's design already handles well:
`_run_loop()`'s startup sequence (`src/edumatcher/mm_bot/bot.py`) is:

1. `_authenticate()` — `gateway_connect` / `gateway_auth` handshake.
2. Request symbol list.
3. **QBOOT** (`_request_bootstrap()`) — ask the engine whether an active
   quote already exists for this `(gateway_id, symbol)`; if so, adopt it
   (`_try_adopt_from_bootstrap`) instead of creating a duplicate.
4. **QLEGS** reconciliation against the adopted quote_id.
5. Wait for `session.state`.
6. If nothing was adopted, resolve a reference price via `_resolve_bootstrap_reference()`'s
   priority chain and send a fresh `quote.new`.

**Scenario B — engine restarts, bot process does not** (bot survives
`pm-engine` bouncing underneath it — plausible if they are separately
supervised, or the operator only restarts the engine). This is the scenario
that actually matches "the exchange restarts and the quotes are gone" as
observed. It is materially worse for the bot: `_authenticate()` only runs
once, at bot process startup (`_run_loop()` step 1) — there is **no
reconnect/re-auth loop in the bot's steady-state event loop**
(`_run_loop`'s `while self._running` loop only polls the SUB socket and
calls `_tick()`; it never re-sends `gateway_connect`). The bot has no
built-in signal that the engine underneath it restarted at all. Its own
`_quote_id` stays populated (nothing cleared it — from the bot's point of
view, it never lost its quote), so the heartbeat guard
(`now - ... and self._quote_id is None`) does not fire, because the
precondition (`self._quote_id is None`) is false.

### 9.3 How long would Scenario B take to notice and recover?

The only mechanism that eventually detects the mismatch is **periodic QLEGS
reconciliation** (`_reconcile_qlegs`, driven from `_tick()`):

```python
if now - self._last_qlegs_reconcile >= self._qlegs_reconcile_interval_sec:
    ...
    self._send(make_quote_legs_request_msg(self.gateway_id, self.symbol, "ALL"))
```

`--qlegs-reconcile-interval-sec` defaults to **15.0 seconds**. When the
reply comes back showing no legs (or a different `quote_id`) than the bot
is tracking, `_reconcile_qlegs` clears local state and schedules an
immediate reissue. So, worst case, **up to ~15 seconds** after an engine
restart before the surviving bot notices and re-quotes — not instantaneous,
and during that entire window the book has zero MM liquidity from that
gateway even though the bot process looks perfectly healthy. Best case is
just under one reconciliation interval if the restart happens right before
a scheduled check; there is no faster path in the current design (the
heartbeat guard, which runs every `--heartbeat-interval-sec`, default 5s,
does *not* help here — it only fires when `_quote_id is None`, which is not
true in this scenario).

Two secondary consequences worth noting for Scenario B specifically:

- Until the bot notices, it is also blind to session-state changes the
  engine emits post-restart (`_session_state` is whatever it last received
  before the engine went down — stale, though usually harmless since most
  session-state values persist across a same-day restart).
- The bot's own reconnect is not gated on re-authenticating — `QLEGS`
  request/reply happens over the existing SUB/PUSH sockets, which for a ZMQ
  PUB/SUB and PUSH/PULL setup typically survive a *brief* engine outage and
  resume delivering once the engine's sockets rebind on the same
  addresses. If the engine's ZMQ endpoints changed (different port, engine
  moved), the bot would need its own restart regardless — outside the scope
  of what QLEGS polling can fix.

### 9.4 How would the bot price its quote into a potentially-empty book?

This is `_resolve_bootstrap_reference()`'s fallback chain (§ "Bootstrap:
starting with an empty book" in `100-mm-bot.md`, and confirmed directly in
code), evaluated in order, first match wins:

1. **Book- or trade-derived mid** — if the bot already has a mid-price
   cached from book/trade events received during its startup waits (only
   relevant to Scenario A's fresh startup, or if some other participant has
   already posted resting orders/traded by the time the bot asks).
2. **QBOOT inactive-quote price** — if QBOOT returns a record of this
   gateway's *previous* quote (even if inactive), the bot reconstructs a
   mid from its last-known bid/ask and requotes at the same level. This is
   the path most relevant to Scenario A after this document's §5 changes
   ship: if the engine now restores the quote as a live `QuoteEntry`, QBOOT
   would report it as **active**, and step 4 of the bot's startup sequence
   (`_try_adopt_from_bootstrap`) would adopt it directly rather than
   falling through to this inactive-price fallback at all.
3. **Random bootstrap range** — `--initial_min`/`--initial_max`, if
   configured; a uniformly random price within that range, rounded to the
   nearest tick.
4. **Fail fast** — if none of the above resolve, the bot logs "no
   reference price available" and exits with a non-zero code rather than
   guessing.

For **Scenario B** specifically (the scenario that matches the reported
symptom), the bot never re-runs this resolution chain at all in response to
the engine restart — QLEGS reconciliation only clears local state and
triggers `_cancel_and_reissue()`, which calls `_send_quote()` using
whatever mid-price the pricer already has cached from before the restart
(`self._pricer.mid_price`, untouched by the QLEGS mismatch). So a
surviving bot reissues at its **last known mid**, not a freshly-resolved
one — reasonable behaviour (nothing has necessarily changed about fair
value just because the engine process bounced), but worth noting since it
means the bot is not "re-bootstrapping" in Scenario B, only "re-announcing"
what it already believed.

### 9.5 Does running the bot make §5's changes unnecessary?

**No, not on its own, and the two are complementary rather than
substitutes:**

- The bot is optional infrastructure (`pm-mm-bot` is a separate process an
  operator must choose to run per symbol); config-seeded
  `market_maker_quotes` exist specifically to give a book liquidity
  **without** requiring any bot process — that is the whole point of the
  config-seed feature, and it is the mechanism the user's original question
  was about. Telling operators "just run the bot" abandons that no-bot use
  case entirely rather than fixing it.
- Even with the bot running, Scenario B leaves the book with **zero MM
  liquidity from that gateway for up to ~15 seconds** after every restart,
  by design of the bot's current reconnection model — not an improvement
  over §5's restore-time fix, which closes that gap to zero (the quote is
  back the instant the engine finishes its restore step, before any
  gateway reconnects at all, exactly as config-seeded quotes already work
  today on a *first* start).
- **The two combine well.** With §5 shipped, Scenario A's QBOOT adoption
  path (§9.4 step 2) becomes strictly better: the bot finds its quote
  already **active** (not merely an inactive price to reference) and adopts
  it directly via step 4 of its startup sequence, skipping requoting
  entirely — one less quote.new/quote.ack round-trip on every bot restart,
  and continuity of the exact same resting order IDs rather than a
  cancel-and-replace. Scenario B's ~15s gap is also better *bounded* once
  §5 ships, because the thing QLEGS reconciliation discovers changes from
  "everything is gone, start over" to "does my adopted state still match" —
  though the ~15s worst-case latency itself is unchanged unless
  `--qlegs-reconcile-interval-sec` is also tuned down, which is an
  orthogonal, low-risk config change (not a code change) worth a one-line
  mention in `100-mm-bot.md` rather than this document.
- If reducing Scenario B's detection latency below 15s is desired
  independent of §5, the actual fix is in the bot, not the engine: add a
  lightweight re-authentication or engine-liveness probe to the bot's
  steady-state loop. That is out of scope for this document (which is about
  engine-side persistence) but is flagged here as the natural follow-up if
  "bot notices an engine restart quickly" becomes its own requirement.


## 10. Recommendation

Proceed with §5's engine-side change (WP1–WP7). It is the only fix that
covers the no-bot case, which is the case the original question was raised
against, and it strictly improves the bot-running case too (§9.5). Running
`pm-mm-bot` remains a good idea for symbols that need continuous
inter-session repricing, but it is not a substitute for this fix and should
not be presented as one to operators who only want config-seeded liquidity
that survives a restart.


## 11. Open Questions

- Should `--qlegs-reconcile-interval-sec`'s default (15s) be revisited given
  §9.3's finding that it is the sole recovery path for a surviving bot
  after an engine-only restart? This document takes no position — it is an
  existing, independently-tunable default, not something this proposal's
  code changes touch.
- Should there be a config-level or CLI-level way to force a fresh
  `seed_once` re-seed without deleting `book_stats.json`/manually cancelling
  the quote (e.g. an admin command)? Not required by the stated goals in
  §4, but worth asking the user whether it is wanted as a follow-up
  convenience, since §5.4 still requires manual quote cancellation to
  intentionally re-trigger a bootstrap seed.
- §6.4 flags `NEVER_INACTIVATE` plus GTC persistence as a new durable
  steady-state. Is that combination something the training material should
  actively demonstrate (a worked example of MM inventory risk building up
  across sessions), or purely a documented caveat? Content decision, not a
  code decision.
