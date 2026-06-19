# RALF example clients and parser libraries

This directory contains:

- `ralf_parser.py`: Python parser/serializer library for RALF lines
- `ralf_subscriber.py`: Python subscriber example using the Python library
- `ralf_parser.h` + `ralf_parser.c`: C parser library for RALF lines
- `ralf_subscriber.c`: C subscriber example using the C library
- `Makefile`: build helper for the C client

## RALF wire format

Messages are text lines:

```text
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

## Run Python example

```bash
cd docs-design/examples/ralf
python3 ralf_subscriber.py --host 127.0.0.1 --port 5580 --role CLEARING --channels CLEARING,DROP_COPY,AUDIT --symbols '*'
```

## Build and run C example

```bash
cd docs-design/examples/ralf
make
./ralf_subscriber 127.0.0.1 5580 CLEARING
```

The examples send:

- `HELLO|...|PROTO=RALF1|...`
- three `SUB` requests for `CLEARING`, `DROP_COPY`, and `AUDIT`

Then they parse and print incoming gateway messages.
