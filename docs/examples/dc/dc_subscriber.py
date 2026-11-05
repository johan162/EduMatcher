#!/usr/bin/env python3
"""Full working DC1 (drop-copy) subscriber example.

Goes beyond printing raw lines: connects to pm-dc-gwy for one participant's
gateway ID, then puts the received `DC_FILL` lines to use the way a risk or
back-office system would -- a running per-symbol tally of fills, executed
quantity, VWAP and the MAKER/TAKER split, plus a check that the drop-copy
`SEQ` only ever moves forward.

DC1 has no SUB step: the `ID` in `HELLO` is the whole subscription, and
fills start arriving straight after `WELCOME`. A risk system watching several
participants opens one connection per ID.

See docs/books/operator-guide/part-5-gateways/060-drop-copy-gateway.md for
the wire contract and
docs/books/protocols-and-clients/part-3-session-behaviour/060-drop-copy.md
for where the feed comes from. The session rules it relies on are the same in
all three line gateways (pm-ralf-gwy, pm-md-gwy, pm-dc-gwy): send HELLO
straight after connecting (the gateway closes a connection without one after
5 s, with EXIT|REASON=auth_timeout); an ERR in reply to HELLO ends the
session; a gateway-initiated close is announced with a final ERR or
EXIT|REASON=...; a client that keeps reading needs no PING to stay connected,
because the heartbeats count as traffic; and a client may end its own session
with a bare EXIT.

Uses dc_parser.py to parse and build DC1 lines.
"""

from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import dataclass, field

from dc_parser import DcMessage, build_dc_line, parse_dc_line


class LineReader:
    """Buffers raw socket bytes and yields one decoded line at a time.

    TCP is a byte stream, not a message queue: one recv() call may return
    half a line, a whole line, or several lines concatenated together, so
    a real client must buffer and split on '\\n' itself rather than assume
    each recv() lines up with one DC1 message.
    """

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
    sock.sendall(build_dc_line(msg_type, fields).encode("utf-8"))


class SequenceTracker:
    """Checks that drop-copy SEQ values only move forward.

    Unlike RALF and CALF, a gap here is *normal*: SEQ is one engine-wide
    counter shared by the fills of every gateway ID, and this session only
    sees its own ID's share of them (see "Sequence numbers" in the drop-copy
    chapter). So the useful check is the other direction -- a SEQ at or below
    the last one seen. DC1 has no replay, so that is not a duplicate: it means
    the engine restarted and its counter began again from 1. The tracker
    reports it and takes the new value as its baseline.
    """

    def __init__(self) -> None:
        self.last_seq: int | None = None

    def observe(self, seq_field: str | None) -> None:
        if not seq_field:
            return
        try:
            seq = int(seq_field)
        except ValueError:
            return
        if self.last_seq is not None and seq <= self.last_seq:
            print(
                f"!! SEQ went backwards: {seq} after {self.last_seq} "
                f"(engine restarted?); re-baselining",
                file=sys.stderr,
            )
        self.last_seq = seq


@dataclass
class SymbolTally:
    fills: int = 0
    total_qty: int = 0
    notional: float = 0.0
    maker_qty: int = 0
    taker_qty: int = 0

    @property
    def vwap(self) -> float:
        return self.notional / self.total_qty if self.total_qty else 0.0


@dataclass
class FillTracker:
    """Tallies one participant's fills per symbol from `DC_FILL` lines.

    `DC_FILL` carries no `SIDE` (see the gateway reference), so this is an
    activity tally -- volume, VWAP, MAKER/TAKER split -- not a net position.
    A position needs the side, which the participant's own ALF `FILL` lines
    or the RALF `EXEC` feed carry.
    """

    _by_symbol: dict[str, SymbolTally] = field(default_factory=dict)

    def observe(self, fields: dict[str, str]) -> SymbolTally:
        """Record one DC_FILL; return its symbol's updated tally."""
        tally = self._by_symbol.setdefault(fields.get("SYMBOL", ""), SymbolTally())
        try:
            qty = int(fields.get("FILL_QTY", ""))
            price = float(fields.get("FILL_PRICE", ""))
        except ValueError:
            print(f"!! malformed DC_FILL, not tallied: {fields}", file=sys.stderr)
            return tally
        tally.fills += 1
        tally.total_qty += qty
        tally.notional += qty * price
        if fields.get("LIQUIDITY") == "MAKER":
            tally.maker_qty += qty
        elif fields.get("LIQUIDITY") == "TAKER":
            tally.taker_qty += qty
        return tally

    def tally_for(self, symbol: str) -> SymbolTally:
        return self._by_symbol.get(symbol, SymbolTally())

    def summary(self) -> str:
        total_fills = sum(t.fills for t in self._by_symbol.values())
        lines = [f"Fill summary: {total_fills} fill(s)"]
        for symbol, tally in sorted(self._by_symbol.items()):
            lines.append(
                f"  {symbol:<8} {tally.fills} fill(s), {tally.total_qty} qty, "
                f"VWAP {tally.vwap:.4f} "
                f"(maker {tally.maker_qty} / taker {tally.taker_qty})"
            )
        return "\n".join(lines)


def _handle_message(
    msg: DcMessage, seq_tracker: SequenceTracker, fill_tracker: FillTracker
) -> None:
    if msg.msg_type == "DC_FILL":
        seq_tracker.observe(msg.fields.get("SEQ"))
        symbol = msg.fields.get("SYMBOL", "")
        tally = fill_tracker.observe(msg.fields)
        print(
            f"FILL  {symbol:<8} {msg.fields.get('FILL_QTY', '?'):>6} @ "
            f"{msg.fields.get('FILL_PRICE', '?'):>10} "
            f"{msg.fields.get('LIQUIDITY', '?'):<5} "
            f"order={msg.fields.get('ORDER_ID', '?')} "
            f"seq={msg.fields.get('SEQ', '?')}  "
            f"[{symbol}: {tally.total_qty} qty, VWAP {tally.vwap:.4f}]"
        )
    elif msg.msg_type == "HB":
        print("HB    (gateway heartbeat)")
    elif msg.msg_type == "PONG":
        print("PONG  (liveness reply)")
    elif msg.msg_type == "EXIT":
        print(
            f"EXIT  gateway is closing the session "
            f"(reason={msg.fields.get('REASON', '?')})",
            file=sys.stderr,
        )
    elif msg.msg_type == "ERR":
        # ERR|CODE=..|DETAIL=.. -- the same shape in every line gateway.
        # BAD_MESSAGE for an unparseable or unsupported line leaves the
        # session open; a terminal one (SLOW_CLIENT, an oversized line) is
        # followed by the gateway closing the connection, which the read
        # loop reports.
        code = msg.fields.get("CODE", "?")
        detail = msg.fields.get("DETAIL", "")
        print(f"ERR   {code}: {detail}", file=sys.stderr)
    else:
        print(f"{msg.msg_type} {msg.fields}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "DC1 drop-copy subscriber example: one participant's fills with "
            "a per-symbol volume, VWAP and MAKER/TAKER tally."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5590)
    parser.add_argument("--client", default="ext-risk-01")
    parser.add_argument(
        "--id",
        default="TRADER01",
        help="Gateway (participant) ID whose fills to receive. Not checked "
        "against any allowlist: drop copy has no entitlement model.",
    )
    args = parser.parse_args()

    seq_tracker = SequenceTracker()
    fill_tracker = FillTracker()

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        reader = LineReader(sock)
        send_line(
            sock,
            "HELLO",
            {"CLIENT": args.client, "PROTO": "DC1", "ID": args.id},
        )

        welcome = parse_dc_line(reader.recv_line())
        if welcome.msg_type != "WELCOME":
            # AUTH_REQUIRED (missing CLIENT/ID or PROTO not DC1): the gateway
            # closes the session, so there is nothing to receive.
            print(
                f"handshake refused: {welcome.msg_type} "
                f"{welcome.fields.get('CODE', '')}: {welcome.fields.get('DETAIL', '')}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"WELCOME: type={welcome.msg_type} fields={welcome.fields}")
        # The connect timeout above must not apply to the read loop: on a
        # quiet day the next line may be a heartbeat HBINT seconds away.
        sock.settimeout(None)
        print(f"Receiving fills for ID={welcome.fields.get('ID', args.id)}")

        connection_error: Exception | None = None
        try:
            while True:
                msg = parse_dc_line(reader.recv_line())
                _handle_message(msg, seq_tracker, fill_tracker)
                if msg.msg_type == "EXIT":
                    # The gateway ended the session and closes the socket next.
                    connection_error = RuntimeError(
                        f"gateway ended the session ({msg.fields.get('REASON', '?')})"
                    )
                    break
        except KeyboardInterrupt:
            print("\ninterrupted, closing connection", file=sys.stderr)
            # EXIT works in both directions: the gateway flushes, then closes.
            try:
                send_line(sock, "EXIT", {})
            except OSError:
                pass
        except (RuntimeError, OSError) as exc:
            connection_error = exc
            print(f"connection lost: {exc}", file=sys.stderr)

    print()
    print(fill_tracker.summary())
    if connection_error is not None:
        sys.exit(1)


if __name__ == "__main__":
    main()
