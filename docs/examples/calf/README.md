# CALF example clients and parser libraries

This directory contains:

- `calf_parser.py`: Python parser/serializer library for CALF lines
- `calf_subscriber.py`: Python subscriber example using the Python library
- `calf_parser.h` + `calf_parser.c`: C parser library for CALF lines
- `calf_subscriber.c`: C subscriber example using the C library
- `Makefile`: build helper for the C client

Both subscribers demonstrate more than a single trivial subscription: they
combine `TOP`, `TRADE`, `STATE` (including the session-wide `SYM=*`
wildcard), and Level 2 `DEPTH` in one client, maintain a small top-of-book
cache (so incremental `MD` updates -- which omit unchanged sides -- render
correctly), pretty-print the `DEPTH` ladder, detect gaps in the
per-`(CH,SYM)` `SEQ` counters, and check `WELCOME|CH_SUPPORTED=` before
relying on channels that may not exist on an older gateway build.

See [docs/user-guide/920-app-calf-protocol.md](../../user-guide/920-app-calf-protocol.md)
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

For the single-stream resume handshake:

```bash
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --resume --resume-ch TOP --resume-sym AAPL --lastseq 1042
```

Run `python3 calf_subscriber.py --help` for the full flag list.

## Build and run C example

```bash
cd docs/examples/calf
make
./calf_subscriber 127.0.0.1 5570 AAPL,MSFT EDU100
```

Arguments are positional: `host [port [symbols [index_id]]]`. `symbols` is
a comma-separated list (default `AAPL`); `index_id` is optional (default:
skip the `INDEX` subscription). Press Ctrl-C for a clean shutdown.

## What the examples send

- `HELLO|CLIENT=...|PROTO=CALF1`
- `SUB|CH=TOP,TRADE,STATE,DEPTH|SYM=<symbols>` (one call, whichever of
  these the gateway's `CH_SUPPORTED` actually advertises)
- `SUB|CH=STATE|SYM=*` (a *separate* subscription -- session-wide state is
  a different stream from a symbol's own state)
- `SUB|CH=INDEX|SYM=<index_id>` (only if `--index`/an index id argument is given)

Then they parse incoming gateway messages and put them to use: a
formatted top-of-book line per symbol, a rendered `DEPTH` ladder, clear
`STATE`/`TRADE`/`IDX` lines, and a `!! sequence gap` warning on stderr if
a stream's `SEQ` counter skips.
