# EduMatcher Market Data Terminal Review

**Scope:** `terminal-gui/` — `apps/web/src/` (views, components, lib, store), `apps/bridge/src/`, and `packages/calf-protocol`, `packages/terminal-types`. Read against `docs-design/EduMatcher-Terminal-GUI.md` and the shipped `src/edumatcher/md_gateway/`, `api_gateway/routers/`.

**Date:** 2026-08-01

**Subject:** `pm-terminal` — read-only, credential-free market data viewer for the EduMatcher exchange.

---

## Overall assessment

This is a well-built frontend. The separation of pure logic from rendering is real
and consistently applied — `overview-rows.ts`, `bars.ts`, `depth.ts`, `prev-close.ts`
carry the semantics and are tested directly, and the views are thin over them. The
comments explain *why* far more often than *what*, which is rare and valuable. The
theme system, density presets and auto-paging all show the display case was thought
about rather than assumed away. Nine deviations from the design document were found
by checking the design against shipped code, and three of them were pushed back into
CALF as protocol fixes rather than worked around locally. That is the right instinct
and it is worth saying plainly.

The findings below are therefore not about code quality. They are about whether a
person can trust what this screen tells them.

The pattern that unifies the high-severity items is this: **the terminal has several
ways of being wrong, or of silently changing what it means, and no way of saying so.**
Sequence numbers arrive on every frame and are read by nobody. Prices are rendered at
a precision the terminal cannot know. A reference-data outage reframes every
percentage on the board behind a footnote. Individually these are small; together they
describe a viewer that degrades quietly, and quiet degradation is the specific failure
mode a market data screen cannot have.

A second, narrower theme: the terminal is **blind through the auctions**, which for a
teaching exchange is a strange place to have a hole.

---

## High

Trust failures. The screen can be wrong, or can change what it means, without saying so.

### T-H1. A previous-close outage silently reframes every percentage on the board

`usePrevCloses` swallows its error and returns `{}`. Every row then falls back to
measuring change from the session open, which *is* marked per row — a `*` on the cell
and a footnote when a marked row is visible. But the Overview's error banner watches
only the `dailyBars` query, so the one prominent "something is wrong" signal never
fires for this.

The result is a board that quietly stops meaning what its own header says, with a
row-level asterisk as the only tell.

The general rule this violates, and which the whole terminal should be held to: *the
screen may degrade, but it must never change what it means without saying so at least
as loudly as the change is significant.* A market-wide baseline switch is not a
footnote-sized event.

Related: the `buildRows` docstring still claims "Every figure in a row now describes
the same moment." That was true when written and is now false — a row mixes
sub-second CALF data, a ten-second history poll and a five-minute previous close.
Three clocks, one row, nothing said. A reassuring comment that is no longer true is
worse than no comment.

**Action:** surface the outage as a banner; correct the docstring; consider exposing
the three data ages rather than implying one.

### T-H2. Today's VWAP is drawn as a reference line on multi-month charts

`SymbolDetail` passes `todayRow?.vwap` to `PriceChart` unconditionally, but the `1M`,
`3M`, `YTD` and `All` presets all render *daily* bars. A horizontal line at the
current session's VWAP drawn across three months of history is not a benchmark, it is
a coincidence positioned to look like one.

Previous close survives on a daily chart — it is the last bar's close. VWAP does not.

**Action:** suppress the VWAP line outside the intraday presets.

### T-H3. Every price is rendered at two decimals, regardless of the instrument

`format.ts`'s `price()` defaults to `decimals = 2` and no call site overrides it.
`tick_decimals` is real, per-symbol, defined in `SymbolConfig`, registered engine-side
through `models/price.py`, and carried on `trade.executed` payloads. Its default is 2,
which is exactly why this is invisible until somebody lists an instrument that is not.
At that point the last price, the bid, the ask, the spread, the basis-point spread,
the OHLC, the VWAP and the range bar are all quietly wrong on every screen.

The reason it is not wired up is the interesting part. The only client-reachable
source of `tick_decimals` is `GET /api/symbols`, which sits behind `require_trading`,
and the terminal deliberately holds no trading credential. The `terminal-gui` README
records this as design §22 open question 1.

It is not an open question. A read-only market data terminal that cannot obtain the
display precision of the instruments it displays is not finished, and this affects
**every CALF consumer**, not only this GUI — any client rendering a price has to
guess. That places it in the same category as the three defects this project already
pushed back into CALF rather than working around.

**Action:** carry `tick_decimals` on CALF as static reference data. See
*Recommendation: `REF` on `SYMBOLS`* below.

### T-H4. `seq` arrives on every frame and is checked by nobody

`uplink.ts` decodes `seq` from the CALF envelope and attaches it to every emitted
frame. `useLiveStore.applyFrame` destructures it into `_seq` and discards it. There is
no gap detection at the bridge, at the store, or anywhere between.

A market data terminal that cannot tell it has missed a message will show a stale book
with complete confidence. That is the worst available failure mode for this class of
software, and the mechanism to avoid it is already on the wire.

**Action:** track last-seen `seq` per `(channel, symbol)` at the bridge, detect gaps,
and surface affected streams in the UI.

### T-H5. The bridge does not use `RESUME`, so every reconnect takes a silent hole

A standing TODO in the `terminal-gui` README, which accepts the gap on the grounds
that this is a display-only viewer.

That reasoning holds for the Overview, whose rows are re-baselined by the `SNAP` on
resubscribe. It does not hold for the Trade Tape, which is a *time and sales record*.
A record with unmarked holes in it is worse than no record, because people quote from
it. The `RESUME` command exists — it was made standalone and repeatable by this very
project — and `buildResume` is already available in `packages/calf-protocol`, unused.

T-H4 and T-H5 should be one piece of work with one owner: detecting a gap you have no
mechanism to repair is only half useful, and repairing gaps you cannot detect is not
possible.

---

## Medium

Fitness for purpose. Nothing here is wrong; things here are missing or misleading.

### T-M1. The terminal is blind through the scheduled auctions

`normalise_cb_halt` publishes `INDICPX`, `INDICQTY` and `IMB`, and its own docstring
explains why: *"Publishing them at all mirrors the imbalance indicator real venues
disseminate during a reopening, which is what lets participants supply the offsetting
interest that resolves the halt."*

That reasoning is correct and it applies with at least as much force to the scheduled
opening and closing auctions — which is where the largest volume of the day prints.
But those fields are event-only, computed once at the instant a call phase ends, and
only on the circuit-breaker path. There is no continuous indicative price or imbalance
dissemination during `OPENING_AUCTION` or `CLOSING_AUCTION`.

So at the two moments of the day that matter most, this terminal can show a phase
badge and nothing else.

This is the highest-*value* item in this review. It sits in Medium rather than High
only because silence is a lesser failure than error, and because it is a gateway and
protocol project rather than a fix. For a teaching exchange it is arguably the most
pedagogically valuable screen that could be built: price formation under an imbalance
is the thing students most need to see and least often can.

### T-M2. Halted and post-close rows still render an executable-looking quote

A halted symbol shows its `HALT` badge and then a full, ordinary bid/ask/size/spread
beside it. None of that is executable. The same is true of the whole board after the
close: session phase sits in the status strip while every row goes on looking like a
live market.

### T-M3. Direction is carried by colour alone on the grid

The Trade Tape gets this right — `▲`/`▼` beside the side, colour as reinforcement.
Overview and Movers use colour only. Roughly one man in twelve has a red-green
deficiency, on a screen whose entire purpose is signalling direction.

### T-M4. Three data ages are presented as one row

Live CALF fields, a ten-second history poll and a five-minute previous close render
identically and adjacently. The status strip reports connection state but not data
age: "CALF connected" beside a ticking clock looks the same whether frames are pouring
in or the feed went silent five minutes ago.

The per-row staleness added for the print time is the right idea applied to one field;
the principle generalises.

### T-M5. No sorting on the Overview

Auto-paging is correct for the unattended display and wrong for a person at a desk.
Traders sort by percentage change, by turnover, by spread. There is no way to.

### T-M6. No countdown to the next session transition

The most-glanced item on a real trading screen. `STATE` carries the current phase and
the previous one, but not the next transition time, so this needs a feed answer before
it needs a frontend one.

---

## Low

### T-L1. The depth ladder ignores price gaps

Levels render evenly spaced regardless of the distance between them. Bids at
`100.00 / 99.99 / 99.98` are drawn identically to bids at `100.00 / 99.00 / 50.00`.
The cumulative column now says how much is behind the touch; the ladder still will not
say how far away it is, which is the other half of the question.

### T-L2. `bg-surface` is undeclared in the Tailwind config

Used in `TradeTape.tsx` and twice in `IndexView.tsx`, resolving to nothing. Four
siblings — `muted`, `ok`, `error`, `warning` — were declared in a previous change and
this one was missed.

### T-L3. The staleness threshold is an arbitrary hardcoded five minutes

Not grounded in how this exchange actually trades. On a thin classroom book it may
fade the entire board permanently, at which point it signals nothing.

### T-L4. Turnover's derivation is undocumented

Computed as `volume × VWAP`, which recovers notional exactly only when VWAP is
unrounded. It may not tie to a sum of the tape, and nothing says so.

---

## Recommendation: `REF` on `SYMBOLS`, for T-H3

`tick_decimals` is **static reference data** and belongs on the handshake and the
reference command, not on a market data channel.

Putting it on `TOP` or `TRADE` would repeat an unchanging value on every tick, on the
hottest path in the protocol, in a channel whose `MD` messages are explicitly deltas.
A field that never changes is precisely the opposite of what that channel is for.

`SYMBOLS` is already the right shape. It exists, it is askable at any time, it is
documented as the reliable route to the universe *because* `WELCOME|SYMBOLS=` is
optional and sent once, and it requires no credential.

**Proposed encoding:**

```
SYMBOLS|COUNT=3|SYMBOLS=AAPL,MSFT,TSLA|REF=AAPL:2,MSFT:2,TSLA:4
WELCOME|PROTO=CALF1|GW=md-gwy01|...|SYMBOLS=AAPL,MSFT|REF=AAPL:2,MSFT:4
```

Four properties, each deliberate:

1. **Backward compatible.** `SYMBOLS=` stays a bare comma-separated list, so every
   existing client is untouched. A new optional field cannot break a parser that does
   not look for it.
2. **Self-advertising.** The *presence* of `REF` is the capability signal — the same
   mechanism `CH_SUPPORTED` uses, and for the same reason. A client talking to an
   older gateway falls back to the documented default of 2 knowingly rather than
   accidentally. No `PROTO` bump is needed or wanted.
3. **Grammatically consistent.** The `SYM:DEC` tuple reuses the colon-delimited
   encoding `DEPTH` already established for `price:qty:count` within a
   comma-separated list. No new grammar.
4. **Extensible.** Contract multiplier is already a written proposal
   (`EduMatcher-contract-multiplyer.md`); currency and lot size will follow. A tuple
   grows to `AAPL:2:1:USD` without a further protocol change. The alternative —
   parallel positional lists `TICKDEC=2,2,4`, `MULT=1,1,50` that must stay
   index-aligned forever — is a bug waiting to be written.

`REF` covers exactly the same symbol set as `SYMBOLS`, so "present in `SYMBOLS`,
absent from `REF`" is not a state a client must reason about.

**The alternative considered and rejected:** adding a read-only tier to
`/api/symbols`. That solves it for this one terminal, couples market-data reference
to the trading API gateway, and leaves every other CALF consumer guessing. Worth
doing eventually for other reasons; it is not the answer to this.

---

## Prioritised actions

| Priority | ID | Action | Area |
|---|---|---|---|
| High | T-H1 | Banner a previous-close outage; fix the false "same moment" docstring | web |
| High | T-H2 | Suppress the VWAP reference line on the daily-bar presets | web |
| High | T-H3 | `REF` on CALF `SYMBOLS`/`WELCOME`; thread through bridge → `price()` | protocol, gateway, bridge, web |
| High | T-H4 | Sequence-gap detection, surfaced in the UI | bridge, store, web |
| High | T-H5 | Wire `RESUME` in the bridge | bridge |
| Medium | T-M1 | Indicative price and imbalance during scheduled auctions | gateway, CALF, web |
| Medium | T-M2 | Stop halted and post-close rows looking tradable | web |
| Medium | T-M3 | Non-colour direction affordance on Overview and Movers | web |
| Medium | T-M4 | Per-source data age; "last tick Xs ago" in the status strip | web |
| Medium | T-M5 | Click-to-sort columns, plus symbol type-ahead | web |
| Medium | T-M6 | Countdown to the next session transition | feed, web |
| Low | T-L1 | Show price gaps in the depth ladder | web |
| Low | T-L2 | Declare `bg-surface` in the Tailwind config | web |
| Low | T-L3 | Ground or expose the staleness threshold | web |
| Low | T-L4 | Document turnover's derivation | web |

**Sequencing notes.** T-H1 and T-H2 are hours, not days, and should land first.
T-H3 blocks nothing but touches every price on every screen, so it should land before
the display work in Medium rather than after it. T-H4 and T-H5 are one piece of work.
T-M1 is a scoping exercise with the gateway owner before it is an implementation.

---

# Addendum: pre-ship review

**Date:** 2026-08-02
**Scope:** final read of `terminal-gui/` before the first trading floor, after
T-H1–T-H5, T-M1–T-M6 and T-L1–T-L4 were implemented.

**Standard applied:** wrong data is catastrophic; absent data is a future
improvement. Everything below is sorted by that test alone, not by effort or
by how interesting it is.

## Ship-blockers found in this pass, and fixed

Three defects of the *wrong data* class. All three predate the remediation
work; none was named by the original review; all are now fixed with tests.

### A. Standing subscriptions were silently lost on every reconnect

`WsFanout.unregister` releases a tab's `DEPTH`/`CB` holds the moment its
socket closes — correct, and reference-counted across tabs. But nothing on
the browser side ever re-declared them: the subscribing effects in
`SymbolDetail` and `Session` are keyed on the symbol, not on the connection,
so they never fire again.

After any reconnect — a laptop waking, a wifi blip, a bridge restart — the
depth ladder **froze on its last pre-outage frame and stayed there**, and
halt detail stopped arriving. Nothing said so; the status strip returned to
"connected". A frozen order book presented as live is the worst single
failure this screen can have, and it never self-healed without a page
reload.

Fixed in `lib/ws.ts`: the client now holds standing interest and replays it
on every open, before the status change so nothing races it.

### B. A reconnected tab kept rendering pre-outage prices

A new WebSocket client received `hello` and nothing else. The store was never
cleared, so the previous book stayed on screen — indefinitely for any symbol
that did not tick again soon — under a green connection indicator.

The header comment in `lib/ws.ts` asserted the opposite: *"The bridge re-sends
`hello` and fresh snapshots on every new connection, so a reconnected tab
needs no catch-up logic of its own."* That was never true. It is the same
defect class as T-H1's `buildRows` docstring, and it is what let both A and B
go unnoticed — the comment answered the question, so nobody asked it.

Fixed: the bridge now replays its cached session phase, per-symbol state,
halt context and merged top-of-book to each new tab. Its own CALF session is
unaffected by a browser socket closing, so it holds the correct answer
already.

### C. A malformed `TRADE` printed on the tape at 0.00

`decodeTrade` defaults a missing `PX`/`QTY` to `0` so its return type stays
total. A `TRADE` line lacking either therefore rendered as a real print of
`0.00` for 0 shares, on the one screen people quote from. The known path —
the payload-less `SNAP` a gateway sent after a `TRADE` `REPLAY_MISS` — was
closed during T-H5, but nothing stopped a malformed line arriving another
way.

Fixed at the bridge: a `TRADE` without both fields is rejected as
`MALFORMED_TRADE` rather than defaulted onward. The tape may be missing a
print; it may not invent one.

### A bug introduced by fix B, caught before it shipped

The replayed frames initially advanced `lastTickAt`, so a feed silent for an
hour would have read "last tick 0s ago" the instant anyone refreshed — the
precise false signal T-M4 exists to give honestly. Frames restated from cache
now carry `replay: true` and do not advance the freshness clock. The marker is
explicit rather than inferred from a zero `SEQ`, so no reader has to know
which sentinel means what.

## Verified correct, for the record

Checked specifically for falsehood and found sound: `price()`/`qty()` render
`—` for anything non-finite rather than a number; the `TopCache` merge treats
an explicit `null` as a withdrawal rather than an overwrite, and hands out
detached copies; `previousCloses` derives "today" from the newest date in the
window rather than per symbol; the auction indicative is cleared on every
session transition; `notExecutableReason` matches the engine's own
`is_matching_enabled` exactly; and the store's `reduceFrame` is exhaustive
over `ServerFrame`, so a new frame type cannot be silently ignored.

## Residual risk accepted for this release

**A brief window of pre-outage prices on reconnect.** Between the socket
opening and the replay arriving, the previous book is still on screen. It is
milliseconds, the data age indicator remains honest throughout, and blanking
the board on every wifi blip would be worse. Noted rather than fixed.


## Future improvements — deliberately not done

Everything here is *absent information*, never wrong information, and none of
it should hold the release.

| ID | Improvement | Why it was left |
|---|---|---|
| T-F1 | A time series of the indicative through a call phase | T-M1 shows the current indicative, updating and flashing direction. Watching price *formation* as a curve is the fuller pedagogical answer and is its own screen. |
| T-F2 | Auction indicative on `AUCTION`'s `SNAP` | The channel has no snapshot by design. A tab joining mid-auction waits at most one interval (default 1s). Adding one would mean giving `AUCTION` snapshot semantics it deliberately lacks. |
| T-F3 | Per-source age for the previous close | The live feed's age and the ten-second poll's age are both shown. The previous close only goes stale across a session boundary, which its query key now invalidates. A third figure was judged clutter. |
| T-F4 | `AUCTION` gap repair via `RESUME` | `TRADE` gaps are repaired; `AUCTION` gaps are reported but not resumed. Lower volume, and the review named only the tape. |
| T-F5 | Persisted sort and search on the Overview | Deliberately session-only: a wallboard left sorted would sit paused indefinitely with nobody to notice. Revisit if desk users outnumber displays. |
| T-F6 | Non-colour affordance on the Movers bar itself | The bar is `aria-hidden` and now sits beside a signed figure with a caret. The bar's own fill is still colour-only. |
| T-F7 | `AUCTION`/`CB` channels in the example clients | `docs/examples/calf/` covers `TOP`/`TRADE`/`STATE`/`DEPTH`/`INDEX`. Neither newer channel has a worked example. |
| T-F8 | Palette declared as `rgb(var(--x) / <alpha-value>)` | Would make opacity modifiers work throughout instead of compiling to nothing. Deferred as a theme-wide change needing visual sign-off; a test now fails the build on any new occurrence. |
| T-F9 | Depth ladder spaced by price | T-L1 states the distance as a figure instead. True proportional spacing collapses to unreadable slivers when one level sits far out, and needs a design answer rather than a code one. |
| T-F10 | Read-only tier on `/api/symbols` | The alternative to `REF` considered and rejected in the original review. Still worth doing for other consumers; no longer needed by this terminal. |
