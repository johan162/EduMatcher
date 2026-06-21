#!/usr/bin/env python3
"""Full working RALF subscriber example.

Uses ralf_parser.py to parse incoming gateway messages.
"""

from __future__ import annotations

import argparse
import socket
from typing import Iterable

from ralf_parser import build_ralf_line, parse_ralf_line


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
    sock.sendall(build_ralf_line(msg_type, fields).encode("utf-8"))


def subscribe_channels(sock: socket.socket, role: str, channels: Iterable[str], symbols: str) -> None:
    for ch in channels:
        send_line(sock, "SUB", {"ROLE": role, "CH": ch, "SYM": symbols})


def main() -> None:
    parser = argparse.ArgumentParser(description="RALF subscriber example")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5580)
    parser.add_argument("--client", default="ext-client-01")
    parser.add_argument("--role", default="CLEARING", choices=["CLEARING", "DROP_COPY", "AUDIT"])
    parser.add_argument("--lastseq", default="0")
    parser.add_argument(
        "--channels",
        default="CLEARING,DROP_COPY,AUDIT",
        help="Comma-separated channels to subscribe",
    )
    parser.add_argument("--symbols", default="*", help="Symbol scope for SUB")
    args = parser.parse_args()

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        reader = LineReader(sock)
        send_line(
            sock,
            "HELLO",
            {
                "CLIENT": args.client,
                "PROTO": "RALF1",
                "ROLE": args.role,
                "LASTSEQ": args.lastseq,
            },
        )

        welcome = parse_ralf_line(reader.recv_line())
        print(f"WELCOME: type={welcome.msg_type} fields={welcome.fields}")

        subscribe_channels(sock, args.role, channels, args.symbols)
        print(f"Subscribed channels={channels} as role={args.role}")

        while True:
            msg = parse_ralf_line(reader.recv_line())
            print(f"{msg.msg_type} {msg.fields}")


if __name__ == "__main__":
    main()
