# Review of the T-H1 – T-H5 fixes

**Date:** 2026-08-01
**Scope:** working-tree diff on `develop` (19 files modified, 1 new test file), read against
`docs-design/reviews/EduMatcher-Terminal-GUI-Review.md`, the shipped
`src/edumatcher/md_gateway/`, and `docs-design/EduMatcher-Market_Data_Protocol.md`.

**Verdict: do not commit.** Three blockers, all in T-H4/T-H5, all of the same
shape: the fix was validated against a fake gateway that behaves differently
from the real one on exactly the path the fix introduces.

Everything green — `typecheck` clean across all five workspaces, 534/534 tests
pass. That is not evidence here; see §1.4.

---

## Verified first

Your specific worry — that T-H3 needed a CALF change nobody made — is mostly
unfounded, but not entirely.

`packages/calf-protocol` has **zero** changes in this diff, and that is correct:
`buildResume`, `isChannel` and `SNAPSHOT_ELIGIBLE` all already existed, and
T-H4/T-H5 introduce no new wire field. T-H3's `REF` work landed in the *previous*
commit (`a840395`) and is genuinely complete: implemented in
`md_gateway/gateway.py:444,466,470`, wired through `main.py`, parsed in the
bridge, and specified in `docs-design/EduMatcher-CALF-Extensions.md` §3.4 with
the exact encoding the review proposed. Nothing missing there.

Two documentation defects do remain, and one of them matters — see §2.

---

## 1. Blockers

### 1.1 The `RESUME` replay delivers duplicate prints to the tape

`uplink.ts:445-468`. On detecting a jump `previous → seq`, `checkForGap` records
`seq` as the new baseline (line 450) and then sends `RESUME|LASTSEQ=previous`
(line 455).

`replay_buffer.py:65` returns **every** buffered event with `seq > last_seq`.
That is `previous+1 … current`, which **includes `seq` itself** — the very
message that revealed the gap and has already been emitted downstream. Any
further live prints that arrive before the gateway processes the `RESUME` are
replayed too.

`gateway.py:939 _queue_raw` appends to one ordered `session.out_queue` over one
TCP socket, so the replay reliably arrives *after* the live message. The
duplicates therefore hit `checkForGap`'s `seq <= previous` early return at line
449 — which protects the baseline and nothing else. `checkForGap` returns
`void`; `onStreamMessage` carries straight on to line 389 and emits the frame
anyway. The store prepends it (`useLiveStore.ts:246`), and the tape renders a
second row with a duplicate React key `${sym}-${seq}`.

A time-and-sales record that prints the same trade twice is the failure the
review was trying to prevent, in the other direction.

The docstring at `uplink.ts:435-443` states the right rule — *"Such a message
must be ignored outright, not merely excluded from the gap check"* — so the
intent is correct; only the wiring is missing. Have `checkForGap` return
`boolean` and drop the message in `onStreamMessage` when it is stale.

While there: the same docstring's premise is false. *"a `RESUME` reply and live
traffic are two separate writes on the wire with no guaranteed relative order"* —
they are one queue on one socket, strictly ordered. The defensive code is still
worth having, but believing the order was arbitrary is what made these
duplicates look unorderable instead of reliably-later and droppable.

### 1.2 A `TRADE` `REPLAY_MISS` puts a phantom `0.00` print on the tape

`gateway.py:_handle_resume`, on `ReplayMissError`, sends
`ERR|CODE=REPLAY_MISS` **and then calls `_send_snapshot_for_stream`
unconditionally**. That function (`gateway.py:690-712`) has branches for `TOP`,
`STATE`, `INDEX`, `DEPTH`, `CB` — and none for `TRADE`. For `TRADE` it emits a
bare `SNAP|CH=TRADE|SYM=X|SEQ=n|TS=…` with no payload.

The bridge routes it by `CH`, not `MSGTYPE`, so it lands in
`onStreamMessage`'s `case "TRADE"` → `decodeTrade` → `decode.ts:230`
`numOr(fields["PX"], 0)` → `{ px: 0, qty: 0, side: "" }` → emitted as a trade
frame. The tape renders a print at **0.00 for 0 shares with no side**.

This path did not exist before this change: the bridge never sent `RESUME`, so
`TRADE` never reached `_send_snapshot_for_stream`. The change creates it.

And it is not the rare path. Gap detection here is *reactive* — a gap is only
noticed when the next print for that symbol arrives. `config.py:35` sets
`replay_window_sec = 30`. Any symbol whose next print comes more than 30s after
the reconnect will `RESUME` against an aged-out window and get `REPLAY_MISS`.
For everything but the busiest names, **`REPLAY_MISS` is the normal outcome of a
reconnect**, so the phantom print is the normal outcome too.

Fix at the source (`_handle_resume` should not snapshot a channel that has no
snapshot) and defensively in the bridge (ignore `SNAP` on `TRADE`/`AUCTION`).
The bridge-side guard is in scope for this diff; the gateway one may not be.

### 1.3 `AUCTION` gaps are displayed as missing trade prints

`useLiveStore.ts:265-267` files **every** `GapFrame` into `tradeGaps` regardless
of `frame.ch`. `mergeTapeRows` does not filter by channel either, and the row
renders *"gap in the tape — some prints for {sym} were missed"*.

Note which gaps actually reach the browser today: `checkForGap` only ever
`emit`s for `AUCTION` (line 467 — `TRADE` takes the `RESUME` branch,
snapshot-backed channels return at 465), plus `TRADE` `REPLAY_MISS` from line
301. So the *majority* of gap rows on the Trade Tape will be `AUCTION` gaps
claiming that trade prints were lost. That is a false statement about the tape's
completeness, on the one screen whose whole value is being a complete record.

Filter on `frame.ch === "TRADE"` in the store, or carry `ch` into the row text.

### 1.4 The fake gateway is scripted to behaviour the real gateway does not have

`test/fake-calf-gateway.ts handleResume` echoes canned lines and, on `"MISS"`,
writes the `ERR` and stops. The real gateway replays *everything* past
`LASTSEQ` (§1.1) and always follows `REPLAY_MISS` with a `SNAP` (§1.2). Neither
divergence is exercised.

`uplink.test.ts` "resumes a TRADE gap instead of reporting it unrepaired"
scripts the reply as `SEQ=2,3` — omitting the `SEQ=4` the real buffer would
return — and then asserts `frames.map(t => t.seq).sort()` equals `[1,2,3,4]`
(a lexicographic sort on numbers, which happens not to matter at these values).
The fixture and the assertion between them hide §1.1 exactly.

The two new fake-gateway behaviours need to match `replay_since` and
`_handle_resume`, and then §1.1 and §1.2 will fail loudly, as they should.

---

## 2. The protocol documentation is stale in a way this change now depends on

### 2.1 `EduMatcher-Market_Data_Protocol.md` does not describe standalone `RESUME`

§7.3 and the §12 field table document `RESUME` **only** as a `HELLO` flag
(`HELLO|…|RESUME=1|CH=…|SYM=…|LASTSEQ=…`), one stream per connection, and state
explicitly: *"RESUME applies to one (CH, SYM) stream per HELLO. To resume
multiple streams, send a plain HELLO then issue SUB for each stream."*

The gateway implements a standalone, repeatable `RESUME` command
(`gateway.py:393`, `_handle_resume`) — and this change now depends on it for its
core mechanism. The normative protocol document describes none of it. A
third-party CALF client reading the spec would not know the command exists.

This is not blocking the commit, but it should not be left: the whole point of
pushing the three earlier defects back into CALF was that the protocol is the
contract.

§7.3's `REPLAY_MISS` description — *"immediately followed by a fresh SNAP"* — was
written when only snapshot-backed channels were resumable. Nobody ever wrote
down what a `TRADE` `REPLAY_MISS` means. That undefined case is the root of §1.2.

### 2.2 `buildResume`'s docstring is now false

`packages/calf-protocol/src/commands.ts:20-22`:
*"The bridge does not use this yet: it reconnects with a plain `HELLO` and
re-subscribes…"*

It does use it, as of this diff. This is exactly the defect class the original
review named under T-H1: *"A reassuring comment that is no longer true is worse
than no comment."* One-line fix, but it is in the protocol package, which is
where a comment is least likely to be re-read and most likely to be trusted.

---

## 3. T-H2 is only partly fixed, and the justification is wrong

`SymbolDetail.tsx:307` gates the VWAP line on `preset === "1D" || preset ===
"Live"`, with an inline comment arguing that *"only `1D` and `Live` never scroll
past today."*

`timeframe.ts:43-46`: both are `from: isoAt(now, 1)` — a **rolling 24 hours**,
not today's session. At 10:00 the `1D` chart shows yesterday from 10:00 onward,
which on a normal calendar is most of yesterday's session. Today's VWAP is drawn
flat across it.

That is the same defect the comment correctly rules out for `5D`, one preset
smaller. The four daily-bar presets — the loud version, and what the review
actually named — are fixed, so this is not a blocker. But the residual case is
real and the reasoning in the comment is not.

Either bound the line to bars at or after the session open, or clip its x-extent
to today's portion of the window.

---

## 4. T-H1: the banner says the opposite of what the screen shows

The plumbing is clean — `PrevCloses`, three call sites, `isError` OR-ed with
`dailyBarsError`, and the `buildRows` docstring correction is accurate and
well-judged.

The wording is not. The banner reads *"Ranking unavailable"* / *"Change
unavailable — the history service is not reachable"* while the board goes on
displaying a full column of %Chg figures. They are not unavailable; they have
been silently re-baselined to the session open — which is the precise event the
review said must be announced. As written, the banner is a false statement
sitting above numbers that are real but mean something else.

Say what they now mean:

> %Chg measured from today's open — previous closes unavailable.

Two smaller notes on `isError` semantics (`main.tsx:13` sets no `retry`, so the
default of 3 applies):

- **Late.** `isError` only flips after three backed-off retries, so there is a
  multi-second window where the whole board is re-baselined with no banner at
  all.
- **Over-eager.** Once the query has succeeded, a later refetch failure sets
  `isError` while `data` — and therefore the closes — is still valid. Previous
  closes do not move intraday, so the banner then fires over figures that are
  perfectly correct. `isError && Object.keys(closes).length === 0` would be
  truer to what the user is looking at.

Erring toward noise is the safer direction, so this is a judgment call — but not
while the text asserts something untrue.

---

## 5. Efficiency

### 5.1 The Trade Tape's memo no longer hits (regression)

`TradeTape.tsx`:

```ts
const source = paused ? frozen : { trades, gaps: tradeGaps };
const rows = useMemo(() => mergeTapeRows(source.trades, source.gaps, symbol), [source, symbol]);
```

`source` is a fresh object literal on every render, so `[source, symbol]` changes
every render and the memo never hits. Before this change `source` was `trades` —
a stable reference from the store. Net effect: a full spread and sort of up to
`TRADE_BUFFER_MAX = 500` frames on **every render** of a component that
re-renders on every print.

Depend on `[trades, tradeGaps, frozen, paused, symbol]` instead.

### 5.2 `mergeTapeRows` sorts 500 to take 200

Both inputs are already newest-first. A two-pointer merge bounded by `limit` is
O(200) with no full copy, against the current O(n log n) plus two array copies.

More to the point, `gaps` is empty essentially all the time. A
`gaps.length === 0` fast path makes the normal case free — and it can call
`filterTape`, which your change otherwise orphaned (it now has no caller in
`src/`, only in tests).

### 5.3 `RESUME` permanently grows the gateway's fanout scan

`gateway.py:_handle_resume` does `session.subscriptions.add((ch, sym))`. The
bridge already holds `TRADE|*`, so every `RESUME` adds a redundant concrete pair
that is never removed — `TRADE` is a wildcard channel and never unsubscribed.

`fanout.py:25 session_wants` linear-scans that set for every client on every
stream event. After a reconnect across N symbols the set grows by N and the
gateway's hottest loop gets proportionally slower, permanently, for the life of
the connection. Fine at classroom scale; worth knowing it is a cost this change
introduces on the far side of the socket, invisible from the bridge.

---

## 6. Smaller items

- **`bg-warning/10` on the gap row compiles to nothing.** Verified against a real
  Tailwind build: `.text-warning` and `.text-halt` are emitted;
  `.bg-warning\/10` is absent. Tailwind 3.4 cannot apply an alpha modifier to a
  colour declared as a bare `var(--halt)`. The row keeps its amber text but has
  no background tint. Same silent-nothing class as T-L2. Use `bg-halt-bg`, which
  is already an `rgba()` token.

- **Mixed clocks on `GapFrame.ts`.** `ws.ts` documents it as *"The gateway's own
  clock"*. True for `checkForGap` (envelope `TS`); false for `uplink.ts:301`,
  which uses `new Date().toISOString()` — the bridge's clock. `mergeTapeRows`
  sorts prints and gaps together on that field, so any skew places the hole at
  the wrong point in the tape. Fix the comment at minimum; better, carry the
  gateway `TS` through the `ERR` path if it is available.

- **Duplicate React key.** `key={`gap-${sym}-${ts}`}` collides when two gaps for
  one symbol share a millisecond — a `TRADE` `REPLAY_MISS` and an `AUCTION` gap
  can.

- **`seq = 0` opens a silent hole.** `decode.ts:60` defaults a missing `SEQ` to
  `0`. That baselines `lastSeq` at 0; the next real message triggers
  `buildResume(ch, sym, 0)`; the gateway rejects it with `BAD_MESSAGE`, not
  `REPLAY_MISS`, so no gap is emitted and nobody is told. A `seq <= 0` guard in
  `checkForGap` closes it.

- **Unreachable `return {}`** at `useLiveStore.ts:269-270`. Pre-existing — it
  already followed `case "index"`'s return on `HEAD` — so per house rules, noting
  it rather than asking for its removal. Flagging only because the new
  `case "gap"` was inserted directly above it and it now reads as new dead code.

---

## What is right

Worth saying, because most of this is good work:

- `lastSeq` deliberately surviving reconnects is the correct call, the reasoning
  is written down, and there is a test pinning it.
- The never-move-the-baseline-backward rule is right, and the comment explaining
  why a corrupted baseline is worse than a missed gap is the best comment in the
  diff.
- Excluding `SYM=*` is correct, and the stated reason matches the gateway —
  `_handle_resume` does reject `SYM=*` explicitly.
- Suppressing gaps on `SNAPSHOT_ELIGIBLE` channels is defensible and checks out
  against `_handle_sub`'s automatic `SNAP`.
- Keeping gaps out of `trades` rather than splicing them in, so no existing
  reader has to learn to skip a non-print, is the right structure.
- The `buildRows` "three clocks, not one" docstring correction is accurate and
  says the useful thing.

The gap between this and shippable is narrow. It is concentrated almost entirely
in one place: the fake gateway does not do what the real one does, and every
blocker above hides behind that.
