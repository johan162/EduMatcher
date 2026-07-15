# RALF Post-Trade Gateway Protocol Training

## Objective

Train on end-to-end usage of the RALF protocol through pm-ralf-gwy using the
example parser/subscriber libraries for the three main external party roles:

- `CLEARING`
- `DROP_COPY`
- `AUDIT`

You will practice connection, subscription, live event handling, heartbeats,
replay checkpoints, and recovery/error behavior.

 

## Prerequisites

- Chapters 01-21 completed.
- Engine running and producing trades.
- `pm-ralf-gwy` running and reachable on TCP (default 5580).
- Support libraries and clients available in `docs/examples/ralf`:
  - ralf_parser.py, ralf_subscriber.py
  - ralf_parser.h, ralf_parser.c, ralf_subscriber.c

Recommended startup terminals:

1. Engine: `pm-engine --verbose`
2. RALF gateway: `pm-ralf-gwy`
3. One or more client terminals for subscriber exercises

 

## Background

RALF is a line-oriented protocol over TCP used for post-trade dissemination.
Clients connect to pm-ralf-gwy, perform HELLO and SUB, then consume events.

In this chapter, the most important operational ideas are:

- Session establishment with HELLO and WELCOME
- Channel and symbol subscription with SUB and UNSUB
- Liveness with HB and PING/PONG
- Replay with LASTSEQ and REPLAY_MISS handling
- Role/channel design for different external consumers

 

## Exercise 1: Prepare a Config That Enables RALF

Generate `engine_config.yaml` with a post_trade_gateway section:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --sessions-enabled \
  --post-trade-gateway \
  --post-trade-bind-address 127.0.0.1 \
  --post-trade-port 5580 \
  --post-trade-allowed-roles CLEARING DROP_COPY AUDIT \
  --output engine_config.yaml
```

Start or restart processes with that config:

```bash
pm-engine --verbose --config engine_config.yaml
pm-ralf-gwy --config engine_config.yaml
```

:material-checkbox-blank-outline: Checkpoint: gateway starts and listens on the configured port.

 

## Exercise 2: Use the Python Example as a CLEARING Consumer

From the example directory:

```bash
cd docs/examples/ralf
python3 ralf_subscriber.py \
  --host 127.0.0.1 \
  --port 5580 \
  --role CLEARING \
  --channels CLEARING \
  --symbols '*'
```

Observe:

- WELCOME line parsed by the Python library
- subscription acknowledgment flow
- incoming EXEC and EOD messages for CLEARING

:material-checkbox-blank-outline: Checkpoint: subscriber prints parsed EXEC events with expected symbols and sequence values.

 

## Exercise 2B: Manual Handshake Probe with nc

Before continuing with richer clients, validate a minimal manual protocol flow:

```bash
nc 127.0.0.1 5580
```

Then send:

```text
HELLO|CLIENT=manual01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0
SUB|CH=CLEARING|SYM=*
```

Expected behavior:

- `WELCOME|...` after `HELLO`
- `SNAP|...` after `SUB`
- live `EXEC|...` / `EOD|...` once trades are produced

:material-checkbox-blank-outline: Checkpoint: manual nc session can establish, subscribe, and receive at least one post-trade message.

 

## Exercise 3: Use the C Example as a DROP_COPY Consumer

Build and run the C subscriber:

```bash
cd docs/examples/ralf
make
./ralf_subscriber 127.0.0.1 5580 DROP_COPY
```

Observe in output:

- WELCOME fields
- SUB flow
- MSG lines for live traffic

Even though the example subscribes broadly for demonstration, run it with a
DROP_COPY role argument and validate that role is accepted.

:material-checkbox-blank-outline: Checkpoint: C subscriber connects, parses, and prints live RALF events.

 

## Exercise 4: Run an AUDIT Session and Compare View Semantics

Run another Python subscriber in a second client terminal:

```bash
python3 docs/examples/ralf/ralf_subscriber.py \
  --host 127.0.0.1 \
  --port 5580 \
  --role AUDIT \
  --channels AUDIT \
  --symbols '*'
```

Compare outputs across CLEARING, DROP_COPY, and AUDIT clients while generating
new trades.

Discussion points:

- channel identifiers in CH
- sequence progression
- symbol filtering behavior

:material-checkbox-blank-outline: Checkpoint: you can explain why separate external roles may consume different channel sets.

 

## Exercise 5: Protocol Control Messages (PING, UNSUB, EXIT)

Use netcat or telnet for manual control-message testing:

```bash
nc 127.0.0.1 5580
```

Then send lines:

```text
HELLO|CLIENT=manual01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0
SUB|CH=CLEARING|SYM=*
PING
UNSUB|CH=CLEARING|SYM=AAPL
EXIT
```

Expected behavior:

- PING yields PONG
- UNSUB updates delivery set
- EXIT closes session cleanly

:material-checkbox-blank-outline: Checkpoint: you can manually drive and verify protocol control flow.

 

## Support Libraries and Example Clients

Reference implementations used in this training chapter:

- docs/examples/ralf/ralf_parser.py
- docs/examples/ralf/ralf_subscriber.py
- docs/examples/ralf/ralf_parser.h
- docs/examples/ralf/ralf_parser.c
- docs/examples/ralf/ralf_subscriber.c

Use these to bootstrap both quick lab subscribers and production-like integration test harnesses.

 

## Exercise 6: Replay and Recovery with LASTSEQ

1. Start a subscriber and note the highest SEQ seen.
2. Disconnect client.
3. Generate additional trades.
4. Reconnect with LASTSEQ set to the saved sequence:

```text
HELLO|CLIENT=replay01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=<saved_seq>
```

Observe replay behavior:

- replayed EXEC/EOD events for SEQ greater than LASTSEQ when retained
- REPLAY_MISS plus SNAP baseline when outside retention window

:material-checkbox-blank-outline: Checkpoint: you can describe the recovery path for both replay-hit and replay-miss cases.

 

## Exercise 7: Error Conditions and Operational Interpretation

Test typical protocol errors with malformed lines:

```text
SUB|CH=CLEARING|SYM=*                (before HELLO)
HELLO|CLIENT=x|PROTO=RALF1           (missing ROLE)
HELLO|CLIENT=x|PROTO=RALF1|ROLE=BAD
SUB|CH=UNKNOWN|SYM=*
```

Map observed ERR codes to operator action:

- AUTH_REQUIRED: client handshake bug or ordering error
- BAD_MESSAGE: parse or field validation issue
- ENTITLEMENT_DENIED: role not allowed by gateway config
- INVALID_CHANNEL: unsupported CH value
- SLOW_CLIENT: consumer cannot keep up with delivery rate

:material-checkbox-blank-outline: Checkpoint: you can convert each ERR code into a practical remediation step.

 

## Suggested Lab Pattern for the Three External Parties

Run three long-lived sessions in parallel:

1. CLEARING client for full clearing consumption
2. DROP_COPY client for compliance/risk copy workflow
3. AUDIT client for forensic/event journaling use

For each session, record:

- client id and role
- channel set
- last checkpoint sequence
- reconnect policy

This produces a realistic external-party operating model for classroom or
integration testing.

 

## Summary

You have now covered major RALF protocol usage patterns:

- provisioning configuration with pm-config-gen
- connecting external clients through example libraries
- handling role/channel subscriptions
- using control messages and liveness probes
- recovering with LASTSEQ replay semantics
- diagnosing protocol errors operationally

## Reflection

Compare the three roles you just used, from a recovery-priorities standpoint:

- **CLEARING**: consumes trade/settlement events. A gap here directly risks
  incorrect positions or P&L — what makes this role the least tolerant of
  missed messages, and how does LASTSEQ replay (Exercise 6) address that?
- **DROP_COPY**: consumes a compliance/risk copy of activity. Is a short gap
  here as operationally urgent as a CLEARING gap? Why or why not — consider
  who consumes this data and on what timescale they act on it.
- **AUDIT**: consumes a forensic/event journal. If AUDIT falls behind or
  drops messages, is it recoverable after the fact from other sources
  (e.g. the exchange's own audit log from Chapter 16), and does that change
  how urgently you'd page an on-call engineer compared to a CLEARING gap?

Write one sentence for each role stating its recovery priority (immediate /
same-day / best-effort) and why — this is the kind of judgment call a real
operations team makes when deciding which reconnect alerts to treat as
incidents versus routine noise.

## Further Reading

- [Post-Trade Dissemination](../user-guide/250-post-trade.md)
- [RALF Protocol Appendix](../user-guide/930-app-ralf-protocol.md)
- [Protocol Support Library Examples](../user-guide/800-examples.md)
- [Processes](../user-guide/170-processes.md)
