#!/usr/bin/env python3
"""Full working CALF subscriber example.

Uses calf_parser.py to parse incoming gateway messages.
"""

from __future__ import annotations

import argparse
import socket
from typing import Iterable

from calf_parser import build_calf_line, parse_calf_line


class LineReader:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = bytearray()

    def recv_line(self) -> str:
        while True:
            nl = self.buf.find(b"\n")
            if nl >= 0:
                line = bytes(self.buf[:nl])
                del self.buf[: nl + 1]
                return line.decode("utf-8", errors="replace")

            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("gateway closed connection")
            self.buf.extend(chunk)


def send_line(sock: socket.socket, msg_type: str, fields: dict[str, str]) -> None:
    sock.sendall(build_calf_line(msg_type, fields).encode("utf-8"))


def subscribe(sock: socket.socket, channels: Iterable[str], symbols: Iterable[str]) -> None:
    send_line(sock, "SUB", {"CH": ",".join(channels), "SYM": ",".join(symbols)})


def main() -> None:
    parser = argparse.ArgumentParser(description="CALF subscriber example")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5570)
    parser.add_argument("--client", default="ext-client-01")
    parser.add_argument("--channels", default="TOP,TRADE")
    parser.add_argument("--symbols", default="AAPL")
    parser.add_argument("--resume", action="store_true", help="Enable single-stream resume")
    parser.add_argument("--resume-ch", default="TOP")
    parser.add_argument("--resume-sym", default="AAPL")
    parser.add_argument("--lastseq", default="0")
    args = parser.parse_args()

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    hello_fields = {
        "CLIENT": args.client,
        "PROTO": "CALF1",
    }

    if args.resume:
        hello_fields.update(
            {
                "RESUME": "1",
                "CH": args.resume_ch,
                "SYM": args.resume_sym,
                "LASTSEQ": args.lastseq,
            }
        )

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        reader = LineReader(sock)

        send_line(sock, "HELLO", hello_fields)
        welcome = parse_calf_line(reader.recv_line())
        print(f"WELCOME: type={welcome.msg_type} fields={welcome.fields}")

        subscribe(sock, channels, symbols)
        print(f"Subscribed channels={channels} symbols={symbols}")

        while True:
            msg = parse_calf_line(reader.recv_line())
            print(f"{msg.msg_type} {msg.fields}")


if __name__ == "__main__":
    main()
