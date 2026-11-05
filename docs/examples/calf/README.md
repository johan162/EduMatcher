# CALF example clients and parser libraries

This directory contains:

- `calf_parser.py`: Python parser/serializer library for CALF lines
- `calf_subscriber.py`: Python subscriber example using the Python library
- `calf_parser.h` + `calf_parser.c`: C parser library for CALF lines
- `calf_recovery.h` + `calf_recovery.c`: C sequence tracking, gap detection
  and replay reconciliation -- pure functions, no sockets or threads
- `calf_recovery_test.c`: self-test for the above (`make test`)
- `calf_subscriber.c`: C subscriber example using both C libraries
- `Makefile`: build helper for the C client and its test

> **Writing a Python client?** Prefer
> `src/edumatcher/calf_client/client.py`, which is
> shipped with the package and handles reconnect, gap repair, replay
> de-duplication, `REF` precision and optional cached state for you:
>
> ```python
> from edumatcher.calf_client import CalfClient, CalfClientOptions
>
> client = CalfClient(CalfClientOptions(symbols=["AAPL"]))
> client.run(on_frame=lambda f: print(f.msg_type, f.fields))
> ```
>
> The examples here stay deliberately standalone -- they show the protocol
> itself rather than a library over it, which is what you want when porting
> to a language that has no library yet.

Both subscribers demonstrate more than a single trivial subscription: they
combine `TOP`, `TRADE`, `STATE` (including the session-wide `SYM=*`
wildcard), and Level 2 `DEPTH` in one client, maintain a small top-of-book
cache (so incremental `MD` updates -- which omit unchanged sides -- render
correctly), pretty-print the `DEPTH` ladder, detect gaps in the
per-`(CH,SYM)` `SEQ` counters **and repair them with `RESUME`**, and check
`WELCOME|CH_SUPPORTED=` before relying on channels that may not exist on an
older gateway build.

The Python client additionally reads `WELCOME|REF=` / `SYMBOLS|REF=` and
renders every price at that symbol's own `tick_decimals`. The C client
prints wire values verbatim and so needs no `REF` handling -- reformatting
a decimal is what creates the chance to reformat it wrongly.

See [CALF protocol reference](../../books/protocols-and-clients/part-2-specifications/030-calf.md)
for the normative wire contract both clients follow.

## CALF wire format

Messages are text lines:

```text
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

## Run Python example

```bash
cd docs/examples/calf
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --symbols AAPL,MSFT
```

Also subscribe to an index feed (skipped if the gateway doesn't advertise
`INDEX` support):

```bash
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --symbols AAPL --index EDU100
```

To send one explicit `RESUME` after the handshake, replaying a stream from
a known position:

```bash
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --resume --resume-ch TOP --resume-sym AAPL --lastseq 1042
```

`RESUME` is a standalone, repeatable command, not a `HELLO` flag -- as a
flag it could only ever run once per connection, which is no use to a
client following several streams. Both examples also send one
automatically for any gap they notice while running, so this flag is only
needed to demonstrate the message in isolation.

Run `python3 calf_subscriber.py --help` for the full flag list.

## Session behaviour

The same in all three line gateways (`pm-md-gwy`, `pm-ralf-gwy`,
`pm-dc-gwy`), and what both examples rely on:

- **Send `HELLO` straight after connecting.** A connection that sends none
  within 5 seconds gets `EXIT|REASON=auth_timeout` and is closed.
- **Check the reply.** `ERR|CODE=AUTH_REQUIRED` in reply to `HELLO` (missing
  `CLIENT`, or `PROTO` not `CALF1`) is the gateway refusing the session; it
  closes the connection, so both examples print the error and exit with
  status 1 instead of subscribing.
- **Errors are `ERR|CODE=..|DETAIL=..`.** `AUTH_REQUIRED`, `SLOW_CLIENT`,
  and `BAD_MESSAGE` for a line over 4096 bytes end the session (the gateway
  sends the line, then closes); every other code leaves it open.
- **The gateway announces its own closes.** Besides the terminal `ERR`s, it
  sends `EXIT|REASON=idle_timeout` or `EXIT|REASON=auth_timeout` before
  closing. Both examples print the reason and exit with status 1.
- **No `PING` needed.** Traffic in both directions counts against the idle
  timeout, so a client that keeps reading stays connected on the gateway's
  own market data and `HB` lines. The idle timeout only fires once writes to
  a client have stopped succeeding.
- **`EXIT` works both ways.** On Ctrl-C both examples send a bare `EXIT`;
  the gateway flushes what is queued, then closes.
- **`REPLAY_MISS` covers more than an old position.** It also answers a
  `RESUME|LASTSEQ=` that is *ahead* of the stream -- a position from before
  a gateway restart, which numbers its streams from 1 again. A fresh `SNAP`
  follows on `TOP`/`STATE`/`INDEX`/`DEPTH`/`CB`, which both examples take as
  the new baseline; on `TRADE`/`AUCTION` nothing follows and the gap is
  permanent.

## Build and run C example

```bash
cd docs/examples/calf
make
./calf_subscriber 127.0.0.1 5570 AAPL,MSFT EDU100
```

Arguments are positional: `host [port [symbols [index_id]]]`. `symbols` is
a comma-separated list (default `AAPL`); `index_id` is optional (default:
skip the `INDEX` subscription). Press Ctrl-C for a clean shutdown: the
client sends `EXIT` and closes.

## What the examples send

- `HELLO|CLIENT=...|PROTO=CALF1`
- `SUB|CH=TOP,TRADE,STATE,DEPTH|SYM=<symbols>` (one call, whichever of
  these the gateway's `CH_SUPPORTED` actually advertises)
- `SUB|CH=STATE|SYM=*` (a *separate* subscription -- session-wide state is
  a different stream from a symbol's own state)
- `SUB|CH=INDEX|SYM=<index_id>` (only if `--index`/an index id argument is given)
- `SYMBOLS` (Python only -- `WELCOME|SYMBOLS=` is optional, so this is the
  reliable route to the instrument universe, and it carries `REF=` too)
- `RESUME|CH=..|SYM=..|LASTSEQ=..`, one per stream, whenever a `SEQ` gap
  appears
- `EXIT` on Ctrl-C

Then they parse incoming gateway messages and put them to use: a
formatted top-of-book line per symbol, a rendered `DEPTH` ladder, clear
`STATE`/`TRADE`/`IDX` lines, and a `!! sequence gap` warning on stderr if
a stream's `SEQ` counter skips.

Three details in the gap handling are worth reading the code for, because
each is easy to get wrong and none is obvious:

- A `RESUME` reply carries **everything** past `LASTSEQ`, so it re-sends
  messages already delivered. Both clients track which sequence ranges
  they are actually missing; without that a client either prints every
  trade twice or discards the backfill it just asked for.
- A `SNAP` re-baselines a stream and is never a gap.
- A `REPLAY_MISS` on `TRADE`/`AUCTION` is **not** followed by a `SNAP` --
  those events are simply gone.
