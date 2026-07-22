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

- Session establishment with HELLO and WELCOME
- Channel and symbol subscription with SUB and UNSUB
- Baseline snapshots (`SNAP`) plus incremental live events (`MD`, `TRADE`, `STATE`, `AUCTION`, `CB`)
- Liveness with HB and PING/PONG
- Replay with RESUME=1 / LASTSEQ and REPLAY_MISS handling
- Auction uncross results (`AUCTION`) and circuit-breaker detail (`CB`) as
  the two newer channels beyond the original TOP/TRADE/STATE/INDEX/DEPTH set

 

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
pm-engine --verbose --config engine_config.yaml
pm-md-gwy --config engine_config.yaml
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
  and, if a residual exists, `IMBSIDE`/`IMBQTY`
- a `CB|...` line on the next halt (`STATUS=HALTED` with `LEVEL`,
  `TRIGGERPX`, `REFPX`, `RESUMEAT`, `MODE`) and a matching one on resume
  (`STATUS=ACTIVE` with `MODE`)
- a `STATE|...` line for the same halt/resume, independently — compare the
  two: `STATE` gives you the simple `SESSION=HALTED`/`SESSION=CONTINUOUS`
  flag, `CB` gives you the operational detail behind it. They fire
  independently, not in a guaranteed order relative to each other

In a second `nc` session, try `SUB|CH=CB|SYM=*` and confirm it is rejected
with `ERR|CODE=INVALID_SYMBOL` — unlike `AUCTION`, `TOP`, `TRADE`, and
`STATE`, `CB` never accepts a wildcard symbol.

:material-checkbox-blank-outline: Checkpoint: you can explain why `AUCTION` has no `SNAP` but `CB` does, and why `CB` rejects `SYM=*` while `AUCTION` accepts it.

 

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

 

## Exercise 6: Replay and Recovery with RESUME=1

1. Start a subscriber and note the highest SEQ for (TOP, AAPL).
2. Disconnect client.
3. Generate additional market activity.
4. Reconnect with RESUME=1 for that stream:

```text
HELLO|CLIENT=replay01|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=<saved_seq>
```

Observe replay behavior:

- replayed events for SEQ greater than LASTSEQ when retained
- REPLAY_MISS plus SNAP baseline when outside replay window

:material-checkbox-blank-outline: Checkpoint: you can describe recovery for both replay-hit and replay-miss cases.

 

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

Use these to bootstrap both quick lab subscribers and production-like integration test harnesses.

 

## Summary

You have now covered major CALF protocol usage patterns:

- provisioning configuration with pm-config-gen
- connecting external clients through example libraries
- handling channel/symbol subscriptions and snapshots
- distinguishing channels with a baseline `SNAP` (`TOP`, `STATE`, `INDEX`,
  `DEPTH`, `CB`) from those without one (`TRADE`, `AUCTION`)
- reading auction uncross results (`AUCTION`) and circuit-breaker operational
  detail (`CB`) alongside the simpler `STATE` halt/resume flag
- using control messages and liveness probes
- recovering with RESUME=1/LASTSEQ semantics
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

- [Market Data Feed (CALF)](../user-guide/240-market-data-feed.md)
- [CALF Protocol Spy (pm-calf-spy)](../user-guide/241-calf-spy-cli.md)
- [CALF Protocol Appendix](../user-guide/920-app-calf-protocol.md)
- [Protocol Support Library Examples](../user-guide/800-examples.md)
- [Processes](../user-guide/170-processes.md)

