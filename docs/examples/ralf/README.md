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
overstate volume up to 3x. They keep separate per-channel counts between EOD
markers to compare against the gateway's interval `TRADE_COUNT`, while the
final summary remains a session-wide unique-trade tally. Both examples also
detect gaps in the per-channel `SEQ` counters and shut down cleanly on Ctrl-C.

See [RALF protocol reference](../../books/protocols-and-clients/part-2-specifications/040-ralf.md)
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
shutdown: the client sends `EXIT`, then prints the final per-symbol tally.

## Session behaviour

The same in all three line gateways (`pm-md-gwy`, `pm-ralf-gwy`,
`pm-dc-gwy`), and what both examples rely on:

- **Send `HELLO` straight after connecting.** A connection that sends none
  within 5 seconds gets `EXIT|REASON=auth_timeout` and is closed.
- **Check the reply.** `ERR|CODE=AUTH_REQUIRED` (missing
  `CLIENT`/`PROTO`/`ROLE`), `ENTITLEMENT_DENIED` (role not in
  `allowed_roles`) or `BAD_MESSAGE` (non-integer `LASTSEQ`) in reply to
  `HELLO` is the gateway refusing the session; it closes the connection, so
  both examples print the error and exit with status 1 instead of
  subscribing.
- **Errors are `ERR|CODE=..|DETAIL=..`.** `SLOW_CLIENT`, and `BAD_MESSAGE`
  for a line over 4096 bytes, end the session (the gateway sends the line,
  then closes); every other code leaves it open.
- **The gateway announces its own closes.** Besides the terminal `ERR`s, it
  sends `EXIT|REASON=idle_timeout` or `EXIT|REASON=auth_timeout` before
  closing. Both examples print the reason and exit with status 1.
- **No `PING` needed.** Traffic in both directions counts against the idle
  timeout, so a client that keeps reading stays connected on the gateway's
  own `HB` lines. The idle timeout only fires once writes to a client have
  stopped succeeding.
- **`EXIT` works both ways.** On Ctrl-C both examples send a bare `EXIT`;
  the gateway flushes what is queued, then closes.
- **`REPLAY_MISS` covers more than an old position.** It also answers a
  `HELLO|LASTSEQ=` that is *ahead* of the stream -- a position from before a
  gateway restart, which numbers its channels from 1 again. It is followed
  by a `SNAP`; both examples take a single-channel `SNAP` as that channel's
  new baseline and let a combined one (`CH=CLEARING,DROP_COPY,AUDIT`) clear
  the baselines, so a reset is never reported as a sequence gap.

## What the examples send

- `HELLO|CLIENT=...|PROTO=RALF1|ROLE=<role>|LASTSEQ=0`
- `SUB|CH=<role's entitled channels>|SYM=*` -- one call covering every
  entitled channel (`CH` accepts a comma-separated list), not one `SUB`
  per channel
- `EXIT` on Ctrl-C

Then they parse incoming gateway messages and put them to use: a
de-duplicated per-symbol trade tally cross-checked against each `EOD`'s
`TRADE_COUNT`, and a `!! sequence gap` warning on stderr if a channel's
`SEQ` counter skips.
