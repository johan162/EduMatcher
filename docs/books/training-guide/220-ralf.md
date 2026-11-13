# RALF Post-Trade Gateway Protocol Training

## Objective

Train on end-to-end usage of the RALF protocol through pm-ralf-gwy using the
example parser/subscriber libraries for the three main external party roles:

- `CLEARING`
- `DROP_COPY`
- `AUDIT`

You will practice connection, subscription, live event handling, heartbeats,
replay checkpoints, and recovery/error behavior.

 


!!! abstract "Background reading"
    - [RALF Gateway](../operator-guide/part-5-gateways/040-ralf-gateway.md)
    - [RALF Protocol](../protocols-and-clients/part-2-specifications/040-ralf.md)

## Prerequisites

- Chapters 01-22 completed.
- Engine running and producing trades.
- `pm-ralf-gwy` running and reachable on TCP (default 5580).
- Support libraries and clients available in `docs/examples/ralf`:
  - ralf_parser.py, ralf_subscriber.py
  - ralf_parser.h, ralf_parser.c, ralf_subscriber.c

Recommended startup terminals:

1. Engine: `pm-engine --verbose`
2. RALF gateway: `pm-ralf-gwy`
3. One or more client terminals for subscriber exercises

!!! note "Where the example files are, and port 5580"
    - `docs/examples/ralf` exists in a repository checkout. On a container or
      `pipx` install use the copy that ships with the package:
      `EX=$(python -c "from edumatcher.config_deploy import examples_root; print(examples_root().parent)")`
      and then `$EX/ralf/…` wherever this chapter says `docs/examples/ralf`.
      The C example needs `make` and a C compiler, which the container image
      does not have; the Python subscriber is enough for every other exercise.
    - Several exercises type protocol lines by hand with `nc 127.0.0.1 5580`.
      The container image has no `nc`; define this small helper once in each
      container terminal that needs it, and use `tcp 127.0.0.1 5580` wherever
      the chapter says `nc 127.0.0.1 5580`:

      ```bash
      tcp() { ( exec 3<>/dev/tcp/"$1"/"$2"; cat <&3 & trap "kill $! 2>/dev/null" EXIT; cat >&3 ); }
      ```

      It uses bash's built-in `/dev/tcp`: what you type goes to the gateway,
      what the gateway sends is printed. `Ctrl-C` ends the session. When the
      gateway closes the connection (after an error, say), press `Ctrl-C` too.
    - Port 5580 can only have one owner. If the AI-simulation container is
      running, its own `pm-ralf-gwy` holds the port: yours will fail to start,
      and `nc 127.0.0.1 5580` would talk to the *simulation's* gateway (you
      would see symbols you never configured). Stop the simulation first, or
      pick another port in Exercise 1.
    - There are no market makers in this chapter's configuration. To create a
      trade, put a limit order in from each trader, for example
      `NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY` on
      `TRADER01` and then `NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=60|PRICE=150.00|TIF=DAY`
      on `TRADER02`.

 

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
  --participants TRADER01 TRADER02 OPS01:ADMIN \
  --sessions-enabled \
  --post-trade-gateway \
  --post-trade-bind-address 127.0.0.1 \
  --post-trade-port 5580 \
  --post-trade-allowed-roles CLEARING DROP_COPY AUDIT \
  --output engine_config.yaml --force
```

!!! note "Back up, check, deploy — then restart"
    This chapter starts from a fresh configuration (its operator is `OPS01`),
    and `--force` replaces your `engine_config.yaml`: save a copy first if you
    want to come back to it (`cp engine_config.yaml engine_config.before-ch23.yaml`).
    As always, nothing changes until you deploy it and restart the engine:
    `pm-cverifier engine_config.yaml`, then `pm-config-deploy engine_config.yaml`. Sessions are enabled, so the restarted engine starts in `CLOSED`: open
    the market from the operator console (`pm-admin --id OPS01`, then
    `SESSION|STATE=PRE_OPEN` and `SESSION|STATE=CONTINUOUS`).

Start or restart processes with that config:

```bash
pm-engine --verbose
pm-ralf-gwy -v
```

Without `-v` the gateway starts silently. With it, it ends its startup with
`listening on 127.0.0.1:5580 (engine_pub=tcp://127.0.0.1:5556)`. (In the
container the address is `0.0.0.0`: the container sets
`EDUMATCHER_GATEWAY_BIND_HOST` so that the port can be reached from outside.)

:material-checkbox-blank-outline: Checkpoint: gateway starts and listens on the configured port.

 

## Exercise 2: Use the Python Example as a CLEARING Consumer

From the example directory (`cd "$EX/ralf"` on a container or `pipx`
install):

```bash
cd docs/examples/ralf
python3 ralf_subscriber.py \
  --host 127.0.0.1 \
  --port 5580 \
  --role CLEARING \
  --channels CLEARING \
  --symbols '*'
```

Then make a trade (the two limit orders in the note above). Expected:

```
WELCOME: type=WELCOME fields={'PROTO': 'RALF1', 'GW': 'ralf-gwy01', 'ROLE': 'CLEARING', 'REPLAY': '86400', 'HBINT': '2'}
Subscribed CH=['CLEARING'] SYM=* as role=CLEARING
SNAP  CH=CLEARING SYM=* SEQ=0
HB    (gateway heartbeat)
EXEC  AAPL         60 @      150.0 BUY  ch=CLEARING
```

`HB` arrives every 2 seconds (`HBINT=2`). An `EOD` line follows only when the
engine shuts down cleanly (chapter 12).

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

 

## Optional Exercise 3: Use the C Example as a DROP_COPY Consumer

This C exercise requires `make` and a C compiler, which are not installed in
the container image. Skip it there, or build it on a host with those tools.
Exercise 2's Python subscriber can also consume RALF channels without a
compiler.

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

:material-checkbox-blank-outline: Optional checkpoint: C subscriber connects,
parses, and prints live RALF events.

 

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
```

Expected behavior:

- PING yields `PONG|TS=…`
- UNSUB updates the delivery set and sends no reply of its own: trades in AAPL
  stop arriving, other symbols continue

!!! note "`EXIT` goes both ways"
    The gateway sends `EXIT|REASON=…|TS=…` when it ends a session (e.g.
    `EXIT|REASON=idle_timeout`). A client may send a bare `EXIT` to end its
    own session; the gateway closes after flushing pending output. All three
    line gateways (`pm-md-gwy`, `pm-ralf-gwy`, `pm-dc-gwy`) behave the same.

:material-checkbox-blank-outline: Checkpoint: you can manually drive and verify protocol control flow, and you can explain what each side's `EXIT` means.

 

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

- replayed EXEC/EOD events for SEQ greater than LASTSEQ when retained; they
  arrive immediately after `WELCOME`, before you have sent `SUB`
- `ERR|CODE=REPLAY_MISS|DETAIL=requested seq outside retention` followed by a
  `SNAP` baseline when outside the retention window (try `LASTSEQ=999`)

:material-checkbox-blank-outline: Checkpoint: you can describe the recovery path for both replay-hit and replay-miss cases.

 

## Exercise 7: Error Conditions and Operational Interpretation

Test typical protocol errors with malformed lines:

```text
SUB|CH=CLEARING|SYM=*                (before HELLO)
HELLO|CLIENT=x|PROTO=RALF1           (missing ROLE)
HELLO|CLIENT=x|PROTO=RALF1|ROLE=BAD
SUB|CH=UNKNOWN|SYM=*
```

The gateway closes the connection after a handshake error, so open a fresh
`nc` session for each line.

What you should see for each line, in order:
`ERR|CODE=AUTH_REQUIRED|DETAIL=send HELLO first`;
`ERR|CODE=AUTH_REQUIRED|DETAIL=CLIENT/PROTO/ROLE required`;
`ERR|CODE=ENTITLEMENT_DENIED|DETAIL=role not allowed`;
`ERR|CODE=INVALID_CHANNEL|DETAIL=unsupported CH=UNKNOWN` (this one needs a valid
`HELLO` first). A valid `HELLO` followed by `SUB|CH=AUDIT|SYM=*` as role
`CLEARING` gives `ENTITLEMENT_DENIED` too, because a role may only subscribe
to its own channel. `BAD_MESSAGE` and `SLOW_CLIENT` are not easy to trigger by
hand.

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

- [Post-Trade Dissemination](../operator-guide/part-5-gateways/040-ralf-gateway.md)
- [RALF Protocol Spy (pm-ralf-spy)](../protocols-and-clients/part-4-writing-clients/040-the-spy-tools-ralf.md)
- [RALF Protocol Appendix](../protocols-and-clients/part-2-specifications/040-ralf.md)
- [Protocol Support Library Examples](../protocols-and-clients/part-4-writing-clients/030-example-libraries.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
