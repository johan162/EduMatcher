# CALF Market-Data Gateway Protocol Training

## Objective

Train on end-to-end usage of the CALF protocol through pm-md-gwy using the
example parser/subscriber libraries for external market-data consumers.

You will practice connection, subscription, snapshots, live market-data
consumption, heartbeats, replay checkpoints, and recovery/error behavior.

 

## Prerequisites

- Chapters 01-22 completed.
- Engine running and producing market activity.
- `pm-md-gwy` running and reachable on TCP (default 5570).
- `pm-calf-spy` installed (ships with the `edumatcher` package — no separate
  build step).
- Support libraries and clients available in `docs/examples/calf`:
  - calf_parser.py, calf_subscriber.py
  - calf_parser.h, calf_parser.c, calf_subscriber.c

Recommended startup terminals:

1. Engine: `pm-engine --verbose`
2. CALF gateway: `pm-md-gwy`
3. One or more client terminals for subscriber exercises

 

## Background

CALF is a line-oriented protocol over TCP used for external market-data
 dissemination.
Clients connect to pm-md-gwy, perform HELLO and SUB, then consume stream data.

In this chapter, the most important operational ideas are:

- Session establishment with HELLO and WELCOME, including per-symbol
  reference data (`REF=SYM:DEC`) for display precision
- Channel and symbol subscription with SUB and UNSUB, across all seven
  channels: TOP, TRADE, STATE, INDEX, DEPTH, AUCTION, CB
- Baseline snapshots (`SNAP`) plus incremental live events (`MD`, `TRADE`, `STATE`, `AUCTION`, `INDIC`, `CB`)
- Liveness with HB and PING/PONG
- Replay with the standalone `RESUME` command / LASTSEQ, and REPLAY_MISS handling
- Auction uncross results (`AUCTION`, with a `REASON` for what kind of
  uncross it was) and indicative pricing during the call phase (`INDIC`)
- Circuit-breaker detail (`CB`), including its cause (`SRC`) and Automated
  Corridor Expansion (`CORRLO`/`CORRHI`/`EXP`, closing backstop prints)
- `pm-calf-spy` as the ready-made, read-only way to inspect any of the above
  without writing a client

 

## Exercise 1: Prepare a Config That Enables CALF

Generate `engine_config.yaml` with a market_data_gateway section:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --sessions-enabled \
  --market-data-gateway \
  --market-data-bind-address 127.0.0.1 \
  --market-data-port 5570 \
  --market-data-replay-window-sec 30 \
  --market-data-heartbeat-interval-sec 1 \
  --market-data-idle-timeout-sec 5 \
  --output engine_config.yaml
```

Start or restart processes with that config:

```bash
pm-engine --verbose
pm-md-gwy
```

:material-checkbox-blank-outline: Checkpoint: gateway starts and listens on the configured port.

 

## Exercise 2: Use the Python Example as a TOP/TRADE Consumer

From the example directory. `calf_subscriber.py` has no `--channels` flag —
it always subscribes to the Cartesian product of `{TOP, TRADE, STATE, DEPTH}`
(filtered down to whatever `WELCOME|CH_SUPPORTED=` actually advertises) for
the symbols you pass:

```bash
cd docs/examples/calf
python3 calf_subscriber.py \
  --host 127.0.0.1 \
  --port 5570 \
  --symbols AAPL
```

Observe:

- WELCOME line parsed by the Python library
- SNAP for TOP (and STATE, DEPTH) baseline
- incoming MD and TRADE messages for subscribed symbols

:material-checkbox-blank-outline: Checkpoint: subscriber prints parsed MD/TRADE events with expected symbol and sequence fields.

 

## Exercise 2B: Manual Handshake Probe with nc

Before continuing with richer clients, validate a minimal manual protocol flow:

```bash
nc 127.0.0.1 5570
```

Then send:

```text
HELLO|CLIENT=manual01|PROTO=CALF1
SUB|CH=TOP,TRADE|SYM=AAPL
```

Expected behavior:

- WELCOME after HELLO
- SNAP for CH=TOP after SUB
- live MD and TRADE once market activity occurs

:material-checkbox-blank-outline: Checkpoint: manual nc session can establish, subscribe, and receive at least one live market-data line.

 

## Exercise 3: Use the C Example Subscriber

Build and run the C subscriber:

```bash
cd docs/examples/calf
make
./calf_subscriber 127.0.0.1 5570
```

Observe in output:

- WELCOME fields
- SUB flow
- MSG lines for live traffic

:material-checkbox-blank-outline: Checkpoint: C subscriber connects, parses, and prints live CALF events.

 

## Exercise 3B: `pm-calf-spy` — the Read-Only Diagnostic CLI

`calf_subscriber.py`/`.c` are example *libraries* to build on; `pm-calf-spy`
is a ready-made, read-only diagnostic client for watching the wire directly,
with no code to write. It runs fully passively — no reconnect, no
auto-recovery, no local state rebuild — so what you see is exactly what the
gateway sent, nothing injected or inferred on your behalf.

```bash
pm-calf-spy --channels TOP,TRADE --symbols AAPL
```

Try a few variations:

```bash
# Every channel the gateway advertises, every symbol (default)
pm-calf-spy

# JSON output instead of human-readable
pm-calf-spy --channels TOP,TRADE --symbols AAPL --format json

# Show heartbeats too (suppressed by default)
pm-calf-spy --channels STATE --symbols AAPL --show-heartbeats

# Raw wire line alongside the formatted one
pm-calf-spy --channels TOP --symbols AAPL --raw

# One-shot replay of a single stream
pm-calf-spy --resume TOP:AAPL:1042 --channels TOP --symbols AAPL

# Stop after 20 data-carrying lines
pm-calf-spy --channels TRADE --symbols '*' --count 20
```

Now try the wildcard default against a mix of eligible and ineligible
channels:

```bash
pm-calf-spy --channels '*' --symbols '*'
```

Since `SYM=*` is only valid for `TOP`/`TRADE`/`STATE`/`AUCTION`, a naive
single `SUB|CH=*|SYM=*` would be rejected outright by the gateway.
`pm-calf-spy` instead splits the request into one `SUB` for the
wildcard-eligible channels and one per concrete symbol for `DEPTH`/`INDEX`/
`CB`, and reports which channels it skipped for the wildcard rather than
failing the whole subscription.

:material-checkbox-blank-outline: Checkpoint: you can explain why `pm-calf-spy` runs with reconnect and auto-recovery both off, and why `--channels '*' --symbols '*'` doesn't produce a single rejected `SUB`.

 

## Exercise 4: State Channel and Wildcard Behavior

`calf_subscriber.py` automatically adds a session-wide `SUB|CH=STATE|SYM=*`
on top of its per-symbol subscriptions (pass `--no-state-wildcard` to skip
it):

```bash
python3 docs/examples/calf/calf_subscriber.py \
  --host 127.0.0.1 \
  --port 5570 \
  --symbols AAPL
```

Expected behavior:

- immediate SNAP for CH=STATE,SYM=* (session-wide) plus one for
  CH=STATE,SYM=AAPL (that symbol's own halt/resume stream)
- STATE updates when session phase or halt/resume transitions occur

:material-checkbox-blank-outline: Checkpoint: you can explain why wildcard symbols are valid only for STATE.

Note: as of CALF `1.0.0`, `SYM=*` is also valid for `TOP` and `TRADE` (see
Exercise 7 below); as of the `AUCTION`/`CB` extension, `SYM=*` is valid for
`AUCTION` too. It remains invalid for `INDEX`, `DEPTH`, and `CB`.

Note also: a symbol-level `STATE` subscription (`CH=STATE|SYM=AAPL`) no
longer only reports that symbol's own halts and resumes. On every
session-wide transition (open, close, phase change) the gateway now fans
out a `STATE` event per known, non-halted symbol as well as the `SYM=*`
line — so a client watching one instrument learns the exchange opened or
closed without also subscribing to `SYM=*`. A halted symbol is skipped by
this fan-out; its halt outlives the session phase it began in, and only an
explicit resume moves it.

To see this, open two `nc` sessions: one `SUB|CH=STATE|SYM=*`, one
`SUB|CH=STATE|SYM=AAPL`. Trigger (or wait for) a session-phase transition
and compare — both should print a `STATE` line for the transition, not just
the wildcard session.

:material-checkbox-blank-outline: Checkpoint: you can explain why a
single-symbol `STATE` subscriber needs this fan-out to know the exchange
opened or closed, and why a halted symbol is excluded from it.

 

## Exercise 4B: Auction Results and Circuit-Breaker Detail

Two channels extend the original five: `AUCTION` (auction uncross results —
no baseline `SNAP`, `SYM=*` allowed, mirrors `TRADE`) and `CB`
(circuit-breaker halt/resume detail — cached baseline `SNAP`, `SYM=*` **not**
allowed, mirrors `DEPTH`/`INDEX`). `calf_subscriber.py` does not drive these
two channels, so exercise them manually with `nc`, alongside `STATE` for
comparison:

```bash
nc 127.0.0.1 5570
```

```text
HELLO|CLIENT=manual03|PROTO=CALF1
SUB|CH=CB,STATE|SYM=AAPL
SUB|CH=AUCTION|SYM=AAPL
```

Expected behavior:

- immediate `SNAP|CH=CB|SYM=AAPL|STATUS=ACTIVE|...` on subscribe (or
  `STATUS=HALTED` plus detail if already halted) — `AUCTION` gets no `SNAP`,
  same as `TRADE`
- an `AUCTION|...` line the next time AAPL's auction uncrosses (open, close,
  or a re-opening auction after a halt), carrying `EQPX`/`EQQTY`/`TRADES`
  and, if a residual exists, `IMBSIDE`/`IMBQTY`, plus a `REASON` of
  `SCHEDULED` (leaving an auction/other non-matching phase), `REOPEN` (a
  halted symbol reopening), or `RECOVERY` (GTC orders restored at engine
  startup) — without `REASON` the three would be indistinguishable on the
  wire
- a `CB|...` line on the next halt (`STATUS=HALTED` with `LEVEL`,
  `TRIGGERPX`, `REFPX`, `RESUMEAT`, `SRC`) and a matching one on resume
  (`STATUS=ACTIVE` with `SRC`) — `SRC` is `CB` for an automatic breaker
  trigger or `ADMIN` for an operator halt; it says what caused the halt,
  not how it will resume
- a `STATE|...` line for the same halt/resume, independently — compare the
  two: `STATE` gives you the simple `SESSION=HALTED`/`SESSION=CONTINUOUS`
  flag, `CB` gives you the operational detail behind it. They fire
  independently, not in a guaranteed order relative to each other

In a second `nc` session, try `SUB|CH=CB|SYM=*` and confirm it is rejected
with `ERR|CODE=INVALID_SYMBOL` — unlike `AUCTION`, `TOP`, `TRADE`, and
`STATE`, `CB` never accepts a wildcard symbol.

:material-checkbox-blank-outline: Checkpoint: you can explain why `AUCTION` has no `SNAP` but `CB` does, why `CB` rejects `SYM=*` while `AUCTION` accepts it, and what each `AUCTION|REASON=` value tells you that the rest of the fields don't.

 

## Exercise 4C: Indicative Auction Price (`INDIC`)

While an opening or closing auction's call phase is running, the gateway
publishes a repeated *indicative* uncross price on the same `AUCTION`
channel — a different message type, `INDIC`, not a preview of `AUCTION`
itself. It says what would happen if the phase ended right now, not what did
happen.

```bash
nc 127.0.0.1 5570
```

```text
HELLO|CLIENT=manual04|PROTO=CALF1
SUB|CH=AUCTION|SYM=AAPL
```

Time this around the opening or closing auction window (or trigger one via
your session-state controls) and observe:

- repeated `INDIC|CH=AUCTION|SYM=AAPL|...` lines during the call phase, on a
  fixed interval (`auction_indicative_interval_sec`, default 1s) — every
  reading republishes, even unchanged ones, so a client can tell a stable
  indicative from a stalled feed
- `INDICQTY` and `IMBQTY` always present; `INDICPX` omitted when the book
  would not cross at all — that omission is a reading ("nothing would
  trade"), not a gap
- exactly one final `AUCTION|...` line when the call phase ends and the
  symbol actually uncrosses

:material-checkbox-blank-outline: Checkpoint: you can explain why `INDIC` and `AUCTION` share a channel but are different message types, and why a missing `INDICPX` must not be rendered as a zero price.

 

## Exercise 4D: Automated Corridor Expansion (ACE)

A circuit-breaker halt does not always end at its first scheduled
`RESUMEAT`. If the indicative uncross price at that instant falls outside
the reopening corridor (`CORRLO`..`CORRHI`), the halt extends: the corridor
widens one rung, `RESUMEAT` moves out, and a fresh call phase begins. The
`CB` channel carries this as a further `STATUS=HALTED` event on the same
stream, not a new one.

```bash
nc 127.0.0.1 5570
```

```text
HELLO|CLIENT=manual05|PROTO=CALF1
SUB|CH=CB,STATE|SYM=AAPL
```

Trigger a halt whose reopening indicative lands outside the corridor (or
replay a recorded scenario that does) and observe:

- the initial halt's `SNAP`/`CB` line carrying `CORRLO`, `CORRHI`, `EXP=0`
  alongside the familiar `LEVEL`/`TRIGGERPX`/`REFPX`/`RESUMEAT`/`SRC`
- an extension event: `STATUS=HALTED` again, with `EXP` incremented, a later
  `RESUMEAT`, a wider `[CORRLO, CORRHI]`, and event-only `INDICPX`/
  `INDICQTY`/`IMB` describing the call phase that just failed to clear
  inside the old corridor
- **no accompanying `STATE` line for the extension** — the symbol was
  halted before and after, so the coarse session state hasn't changed; only
  `CB` reports it
- eventually a resume (`STATUS=ACTIVE`) once an indicative lands inside the
  corridor, or — if the trading day ends first — a resume carrying
  `REASON=CLOSING_BACKSTOP`, `CLAMPED=1`, and `PRINTPX`, meaning the
  exchange printed at the corridor boundary rather than a price the book
  discovered

:material-checkbox-blank-outline: Checkpoint: you can explain why a client that ignores `EXP`/`CORRLO`/`CORRHI` will wrongly report a halted symbol as overdue to reopen, and what `CLAMPED=1` tells you about a `CLOSING_BACKSTOP` print.

 

## Exercise 4E: Reference Data — Tick Decimals (`REF`)

Every instrument has a display precision (`tick_decimals`) that a market
data client otherwise has no way to discover. `WELCOME` and the `SYMBOLS`
reply both carry it as `REF=SYM:DEC,...`, matching the symbol set in
`SYMBOLS=`.

```bash
nc 127.0.0.1 5570
```

```text
HELLO|CLIENT=manual06|PROTO=CALF1
SYMBOLS
```

Observe:

- `WELCOME|...|SYMBOLS=...|REF=...` on connect — `REF` covers exactly the
  symbols listed in `SYMBOLS`, in the same `SYM:DEC` order
- the `SYMBOLS` reply repeats the same pairing: `SYMBOLS|COUNT=n|SYMBOLS=...|REF=...`
- a symbol you configured with a non-default `tick_decimals` (e.g. `4`)
  reports that value, not the fallback of `2`

:material-checkbox-blank-outline: Checkpoint: you can explain why `REF` rides the handshake/`SYMBOLS` reply instead of being repeated on every `TOP`/`MD` line, and what a client should assume for a symbol missing from `REF` entirely (older gateway, no capability).

 

## Exercise 5: Protocol Control Messages (PING, UNSUB, EXIT)

Use netcat for manual control-message testing:

```bash
nc 127.0.0.1 5570
```

Then send lines:

```text
HELLO|CLIENT=manual02|PROTO=CALF1
SUB|CH=TOP|SYM=AAPL
PING
UNSUB|CH=TOP|SYM=AAPL
EXIT
```

Expected behavior:

- PING yields PONG
- UNSUB removes delivery for that stream
- EXIT closes session cleanly

:material-checkbox-blank-outline: Checkpoint: you can manually drive and verify control flow.

 

## Exercise 6: Replay and Recovery with RESUME

1. Start a subscriber and note the highest SEQ for (TOP, AAPL).
2. Disconnect client.
3. Generate additional market activity.
4. Reconnect with a plain `HELLO`, then send `RESUME` for that stream:

```text
HELLO|CLIENT=replay01|PROTO=CALF1
RESUME|CH=TOP|SYM=AAPL|LASTSEQ=<saved_seq>
```

`RESUME` is a command in its own right, sent after `WELCOME`, and
repeatable — send one per stream you were following. Older builds carried
it as a `RESUME=1` flag on `HELLO`, which could only ever be honoured once
per connection; that form is no longer accepted.

Observe replay behavior:

- replayed events for SEQ greater than LASTSEQ when retained
- REPLAY_MISS plus a SNAP baseline when outside the replay window — but on
  `TOP`/`STATE`/`INDEX`/`DEPTH`/`CB` only. On `TRADE` and `AUCTION` no SNAP
  follows, because there is no snapshot of a print that already happened.

5. Now repeat step 4 on `TRADE` instead of `TOP`, with a `LASTSEQ` several
   messages behind. Count the prints you receive against the ones you had
   already seen.

The reply carries **everything** past `LASTSEQ`, not just what you missed —
including the message that revealed the gap. Work out what a tape would
look like if the client rendered them all, then read how
`docs/examples/calf/calf_subscriber.py` avoids it.

:material-checkbox-blank-outline: Checkpoint: you can describe recovery for both replay-hit and replay-miss cases, say which channels get a SNAP on a miss, and explain why a replay reply must be de-duplicated.

 

## Exercise 7: Error Conditions and Operational Interpretation

Test typical protocol errors with malformed lines:

```text
SUB|CH=TOP|SYM=AAPL                 (before HELLO)
HELLO|CLIENT=x|PROTO=BAD
SUB|CH=UNKNOWN|SYM=AAPL
SUB|CH=DEPTH|SYM=*                  (invalid wildcard usage — DEPTH requires an explicit symbol)
SUB|CH=CB|SYM=*                     (invalid wildcard usage — CB requires an explicit symbol)
```

Note: as of CALF `1.0.0`, `SYM=*` is valid for `TOP`, `TRADE`, and `STATE`
(e.g. `SUB|CH=TOP|SYM=*` now succeeds and returns one `SNAP` per known
symbol). As of the `AUCTION`/`CB` extension, `SYM=*` is also valid for
`AUCTION`. The wildcard is rejected for `INDEX`, `DEPTH`, and `CB`, which
always require an explicit id/symbol — see the CALF protocol reference for
details.

Map observed ERR codes to operator action:

- AUTH_REQUIRED: client handshake bug or ordering error
- PROTO_MISMATCH: wrong protocol negotiation value
- INVALID_CHANNEL: unsupported CH value
- INVALID_SYMBOL: unknown symbol, or `SYM=*` used with `INDEX`/`DEPTH`/`CB`
- REPLAY_MISS: requested resume point outside replay retention
- SLOW_CLIENT: consumer cannot keep up with delivery rate

:material-checkbox-blank-outline: Checkpoint: you can convert each ERR code into a practical remediation step.

 

## Support Libraries and Example Clients

Reference implementations used in this training chapter:

- docs/examples/calf/calf_parser.py
- docs/examples/calf/calf_subscriber.py
- docs/examples/calf/calf_parser.h
- docs/examples/calf/calf_parser.c
- docs/examples/calf/calf_subscriber.c
- `pm-calf-spy` (installed CLI — no source to read, but the fastest way to
  point at a running gateway and see the wire)

Use these to bootstrap both quick lab subscribers and production-like
integration test harnesses. Note that `calf_subscriber.py`/`.c` only drive
`TOP`, `TRADE`, `STATE`, and `DEPTH` (filtered by `WELCOME|CH_SUPPORTED=`) —
they do not touch `AUCTION`, `INDIC`, or `CB`. Reach for `pm-calf-spy` or a
manual `nc` session for those, as this chapter's exercises do.

 

## Summary

You have now covered major CALF protocol usage patterns:

- provisioning configuration with pm-config-gen
- connecting external clients through example libraries, and through the
  read-only `pm-calf-spy` CLI
- handling channel/symbol subscriptions and snapshots across all seven
  channels
- distinguishing channels with a baseline `SNAP` (`TOP`, `STATE`, `INDEX`,
  `DEPTH`, `CB`) from those without one (`TRADE`, `AUCTION`, `INDIC`)
- reading auction uncross results (`AUCTION`, with `REASON`), indicative
  pricing during a call phase (`INDIC`), and circuit-breaker operational
  detail (`CB`, with `SRC` and Automated Corridor Expansion) alongside the
  simpler `STATE` halt/resume flag and its per-symbol session fan-out
- discovering per-symbol display precision via `REF`
- using control messages and liveness probes
- recovering with `RESUME`/LASTSEQ semantics, including de-duplicating a replay
- diagnosing protocol errors operationally

## Reflection

You have now used both RALF (Chapter 22, post-trade dissemination:
CLEARING/DROP_COPY/AUDIT roles) and CALF (this chapter, market-data
dissemination: TOP/TRADE/state channels). Before moving on, answer this
synthesis question:

If you were building a downstream system, which protocol would you consume
and why — a **risk system that needs to know every fill as it happens**, a
**market-data terminal displaying live top-of-book**, and a **compliance
archive that reconstructs the day's activity after the fact**? For each of
those three consumers, state whether it needs RALF, CALF, or both, and
justify your answer using what each protocol actually carries (trade/clearing
events vs. price/quote state) rather than just their names.

## Further Reading

- [Market Data Feed (CALF)](../user-guide/240-calf-gateway.md)
- [CALF Protocol Spy (pm-calf-spy)](../user-guide/241-calf-spy-cli.md)
- [CALF Protocol Appendix](../user-guide/920-app-calf-protocol.md)
- [Protocol Support Library Examples](../user-guide/800-examples.md)
- [Processes](../user-guide/170-processes.md)

