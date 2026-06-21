# CALF example clients and parser libraries

This directory contains:

- calf_parser.py: Python parser/serializer library for CALF lines
- calf_subscriber.py: Python subscriber example using the Python library
- calf_parser.h + calf_parser.c: C parser library for CALF lines
- calf_subscriber.c: C subscriber example using the C library
- Makefile: build helper for the C client

## CALF wire format

Messages are text lines:

```text
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

## Run Python example

```bash
cd docs-design/examples/calf
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --channels TOP,TRADE --symbols AAPL
```

For single-stream resume handshake example:

```bash
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 --resume --resume-ch TOP --resume-sym AAPL --lastseq 1042
```

## Build and run C example

```bash
cd docs-design/examples/calf
make
./calf_subscriber 127.0.0.1 5570
```

The examples send:

- HELLO|...|PROTO=CALF1
- SUB for TOP and TRADE

Then they parse and print incoming gateway messages.
