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
