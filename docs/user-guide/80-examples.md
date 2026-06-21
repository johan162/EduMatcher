# Protocol Support Library Examples

!!! note "Learning objectives"
    After reading this chapter you will understand:

    - where protocol support-library source code lives
    - how to run Python and C example clients for implemented protocols
    - how to validate gateway connectivity quickly using reusable example code
    - how to navigate parser-library source files when integrating external clients


## Scope

This chapter documents source-code examples for currently implemented external
protocol gateways:

- RALF (`pm-ralf-gwy`)
- CALF (`pm-md-gwy`)

BALF support-library examples exist as source code only and are intentionally
not covered here because BALF runtime gateway support is not yet implemented.


## Directory structure

Protocol support libraries and example clients are stored under:

- `docs/examples/ralf`
- `docs/examples/calf`
- `docs/examples/balf` (not covered in this chapter)


## RALF support library and examples

### Source files

- Python parser library: [ralf_parser.py](../examples/ralf/ralf_parser.py)
- Python subscriber example: [ralf_subscriber.py](../examples/ralf/ralf_subscriber.py)
- C parser library header: [ralf_parser.h](../examples/ralf/ralf_parser.h)
- C parser library implementation: [ralf_parser.c](../examples/ralf/ralf_parser.c)
- C subscriber example: [ralf_subscriber.c](../examples/ralf/ralf_subscriber.c)
- Build helper: [Makefile](../examples/ralf/Makefile)

### Python usage pattern

```python
from ralf_parser import build_ralf_line, parse_ralf_line

line = build_ralf_line("HELLO", {
    "CLIENT": "demo01",
    "PROTO": "RALF1",
    "ROLE": "CLEARING",
    "LASTSEQ": "0",
})
msg = parse_ralf_line("WELCOME|PROTO=RALF1|GW=ralf-gwy01|ROLE=CLEARING")
print(msg.msg_type, msg.fields)
```

### Run Python example

```bash
cd docs/examples/ralf
python3 ralf_subscriber.py --host 127.0.0.1 --port 5580 --role CLEARING --channels CLEARING --symbols '*'
```

### Build and run C example

```bash
cd docs/examples/ralf
make
./ralf_subscriber 127.0.0.1 5580 CLEARING
```

### Manual gateway sanity check

```bash
nc 127.0.0.1 5580
```

Then send:

```text
HELLO|CLIENT=manual01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0
SUB|CH=CLEARING|SYM=*
```

See also:

- [Post-Trade Dissemination (RALF)](18-post-trade.md)
- [Appendix - RALF Protocol](93-app-ralf-protocol.md)


## CALF support library and examples

### Source files

- Python parser library: [calf_parser.py](../examples/calf/calf_parser.py)
- Python subscriber example: [calf_subscriber.py](../examples/calf/calf_subscriber.py)
- C parser library header: [calf_parser.h](../examples/calf/calf_parser.h)
- C parser library implementation: [calf_parser.c](../examples/calf/calf_parser.c)
- C subscriber example: [calf_subscriber.c](../examples/calf/calf_subscriber.c)
- Build helper: [Makefile](../examples/calf/Makefile)

### Python usage pattern

```python
from calf_parser import build_calf_line, parse_calf_line

line = build_calf_line("HELLO", {"CLIENT": "demo01", "PROTO": "CALF1"})
msg = parse_calf_line("WELCOME|PROTO=CALF1|GW=md-gwy01|HBINT=1|REPLAY=30")
print(msg.msg_type, msg.fields)
```

### Run Python example

```bash
cd docs/examples/calf
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --channels TOP,TRADE --symbols AAPL
```

### Build and run C example

```bash
cd docs/examples/calf
make
./calf_subscriber 127.0.0.1 5570
```

### Manual gateway sanity check

```bash
nc 127.0.0.1 5570
```

Then send:

```text
HELLO|CLIENT=manual01|PROTO=CALF1
SUB|CH=TOP,TRADE|SYM=AAPL
```

See also:

- [Market Data Feed (CALF)](20-market-data-feed.md)
- [Appendix - CALF Protocol](92-app-calf-protocol.md)


## Integration guidance

Use the parser libraries as the protocol boundary in your client code:

1. Read bytes from TCP.
2. Split by newline into protocol lines.
3. Parse lines using the protocol parser library.
4. Route by `msg_type` and fields.
5. Track `SEQ` checkpoints per protocol rules.

This keeps socket handling separate from protocol semantics and makes testing
much easier.