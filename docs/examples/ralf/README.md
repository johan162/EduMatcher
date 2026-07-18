# RALF example clients and parser libraries

This directory contains:

- `ralf_parser.py`: Python parser/serializer library for RALF lines
- `ralf_subscriber.py`: Python subscriber example using the Python library
- `ralf_parser.h` + `ralf_parser.c`: C parser library for RALF lines
- `ralf_subscriber.c`: C subscriber example using the C library
- `Makefile`: build helper for the C client

Both subscribers subscribe to every channel a role is actually entitled to
(see the §7 entitlement matrix in the protocol reference) in **one**
combined `SUB`, then put the received `EXEC`/`EOD` data to use: a running
per-symbol executed-volume tally that correctly de-duplicates `EXEC` lines
by `EXEC_ID`. A single executed trade is delivered once *per subscribed
channel* -- an `AUDIT` client subscribed to all three channels receives
the *same* trade three times, and naively counting raw lines would
overstate volume up to 3x. Both examples also detect gaps in the
per-channel `SEQ` counters and shut down cleanly on Ctrl-C, printing the
final tally.

See [docs/user-guide/930-app-ralf-protocol.md](../../user-guide/930-app-ralf-protocol.md)
for the normative wire contract both clients follow.

## RALF wire format

Messages are text lines:

```text
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

## Run Python example

```bash
cd docs/examples/ralf
python3 ralf_subscriber.py --host 127.0.0.1 --port 5580 --role CLEARING
```

`--role` defaults the subscribed channel(s) to exactly what that role may
access (`CLEARING`/`DROP_COPY` -> that channel only, `AUDIT` -> all
three); pass `--channels` explicitly to override, e.g. to see
`ERR|CODE=ENTITLEMENT_DENIED` on purpose:

```bash
python3 ralf_subscriber.py --role CLEARING --channels AUDIT
```

Run `python3 ralf_subscriber.py --help` for the full flag list.

## Build and run C example

```bash
cd docs/examples/ralf
make
./ralf_subscriber 127.0.0.1 5580 AUDIT
```

Arguments are positional: `host [port [role]]` (`role` one of `CLEARING`,
`DROP_COPY`, `AUDIT`; default `CLEARING`). Press Ctrl-C for a clean
shutdown that prints the final per-symbol tally.

## What the examples send

- `HELLO|CLIENT=...|PROTO=RALF1|ROLE=<role>|LASTSEQ=0`
- `SUB|CH=<role's entitled channels>|SYM=*` -- one call covering every
  entitled channel (`CH` accepts a comma-separated list), not one `SUB`
  per channel

Then they parse incoming gateway messages and put them to use: a
de-duplicated per-symbol trade tally cross-checked against each `EOD`'s
`TRADE_COUNT`, and a `!! sequence gap` warning on stderr if a channel's
`SEQ` counter skips.
