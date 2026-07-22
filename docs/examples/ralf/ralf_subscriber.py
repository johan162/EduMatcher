#!/usr/bin/env python3
"""Full working RALF subscriber example.

Goes beyond a single trivial subscription: subscribes to every channel a
role is actually entitled to (see the §7 entitlement matrix in the
protocol reference), then puts the received `EXEC`/`EOD` data to use --
a running per-symbol executed-volume tally that correctly de-duplicates
`EXEC` lines by `EXEC_ID` (an `AUDIT` client subscribed to more than one
channel receives the *same* trade once per channel, by design, see §6)
and a per-channel sequence-gap check.

See docs/user-guide/930-app-ralf-protocol.md for the normative wire
contract this client follows.

Uses ralf_parser.py to parse and build RALF lines.
"""

from __future__ import annotations

import argparse
import socket
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field

from ralf_parser import RalfMessage, build_ralf_line, parse_ralf_line

# Which channels each role may subscribe to (protocol reference §7). AUDIT
# is the only role entitled to more than its own name.
_ROLE_CHANNELS: dict[str, tuple[str, ...]] = {
    "CLEARING": ("CLEARING",),
    "DROP_COPY": ("DROP_COPY",),
    "AUDIT": ("CLEARING", "DROP_COPY", "AUDIT"),
}


class LineReader:
    """Buffers raw socket bytes and yields one decoded line at a time.

    TCP is a byte stream, not a message queue: one recv() call may return
    half a line, a whole line, or several lines concatenated together, so
    a real client must buffer and split on '\\n' itself rather than assume
    each recv() lines up with one RALF message.
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
    sock.sendall(build_ralf_line(msg_type, fields).encode("utf-8"))


def subscribe(sock: socket.socket, channels: Iterable[str], symbols: str) -> None:
    """One SUB covering every channel in *channels*, all scoped to *symbols*.

    `CH` accepts a comma-separated list (protocol reference §6, `SUB`), so
    an AUDIT client subscribing to all three channels is one round trip
    and one `SNAP`, not three.
    """
    send_line(sock, "SUB", {"CH": ",".join(channels), "SYM": symbols})


class ChannelSequenceTracker:
    """Detects gaps in the per-channel SEQ counters RALF streams use.

    Unlike CALF, RALF sequences are per-*channel*, not per-(channel,
    symbol) -- see §8 of the protocol reference: "SEQ is maintained per
    channel ... across different channels, SEQ values are independent."
    """

    def __init__(self) -> None:
        self._last_seq: dict[str, int] = {}

    def observe(self, channel: str, seq_field: str | None) -> None:
        if not channel or not seq_field:
            return
        try:
            seq = int(seq_field)
        except ValueError:
            return
        previous = self._last_seq.get(channel)
        if previous is not None and seq != previous + 1:
            print(
                f"!! sequence gap on channel {channel}: "
                f"expected {previous + 1}, got {seq}",
                file=sys.stderr,
            )
        self._last_seq[channel] = seq


@dataclass
class SymbolTally:
    unique_trades: int = 0
    total_qty: int = 0


@dataclass
class ExecTracker:
    """Tallies executed volume per symbol from `EXEC` lines.

    A single executed trade is delivered once *per subscribed channel*
    (protocol reference §6, `EXEC`): a role subscribed to more than one
    channel -- only `AUDIT` can be -- sees the same `EXEC_ID` repeated,
    once per channel. Counting raw lines would overstate volume by up to
    3x for an AUDIT client subscribed to everything, so this tracker
    de-duplicates by `EXEC_ID` before tallying and separately reports the
    raw (as-delivered) line count so the distinction is visible rather
    than silently hidden.
    """

    _seen_exec_ids: set[str] = field(default_factory=set)
    _by_symbol: dict[str, SymbolTally] = field(default_factory=dict)
    _raw_lines_by_channel: dict[str, int] = field(default_factory=dict)

    def observe(self, channel: str, fields: dict[str, str]) -> tuple[bool, SymbolTally]:
        """Record one EXEC line; return (is_new_unique_trade, its symbol's tally)."""
        self._raw_lines_by_channel[channel] = (
            self._raw_lines_by_channel.get(channel, 0) + 1
        )
        exec_id = fields.get("EXEC_ID", "")
        symbol = fields.get("SYM", "")
        tally = self._by_symbol.setdefault(symbol, SymbolTally())
        is_new = bool(exec_id) and exec_id not in self._seen_exec_ids
        if is_new:
            self._seen_exec_ids.add(exec_id)
            tally.unique_trades += 1
            try:
                tally.total_qty += int(fields.get("QTY", "0"))
            except ValueError:
                pass
        return is_new, tally

    def tally_for(self, symbol: str) -> SymbolTally:
        return self._by_symbol.get(symbol, SymbolTally())

    def summary(self) -> str:
        raw_total = sum(self._raw_lines_by_channel.values())
        unique_total = len(self._seen_exec_ids)
        by_channel = ", ".join(
            f"{ch}={n}" for ch, n in sorted(self._raw_lines_by_channel.items())
        )
        lines = [
            f"Execution summary: {unique_total} unique trade(s) "
            f"({raw_total} raw EXEC line(s): {by_channel or 'none'})"
        ]
        for symbol, tally in sorted(self._by_symbol.items()):
            lines.append(
                f"  {symbol:<8} {tally.unique_trades} unique trade(s), "
                f"{tally.total_qty} total qty"
            )
        return "\n".join(lines)


def _handle_message(
    msg: RalfMessage, seq_tracker: ChannelSequenceTracker, exec_tracker: ExecTracker
) -> None:
    channel = msg.fields.get("CH", "")
    symbol = msg.fields.get("SYM", "")
    seq_tracker.observe(channel, msg.fields.get("SEQ"))

    if msg.msg_type == "SNAP":
        print(f"SNAP  CH={channel} SYM={symbol} SEQ={msg.fields.get('SEQ', '?')}")
    elif msg.msg_type == "EXEC":
        is_new, _tally = exec_tracker.observe(channel, msg.fields)
        dup_note = "" if is_new else "  (duplicate copy of an already-counted trade)"
        print(
            f"EXEC  {symbol:<8} {msg.fields.get('QTY', '?'):>6} @ "
            f"{msg.fields.get('PX', '?'):>10} {msg.fields.get('SIDE', '?'):<4} "
            f"ch={channel}{dup_note}"
        )
    elif msg.msg_type == "EOD":
        tally = exec_tracker.tally_for(symbol)
        print(
            f"EOD   {symbol:<8} gateway TRADE_COUNT="
            f"{msg.fields.get('TRADE_COUNT', '?')} "
            f"(client tallied {tally.unique_trades} unique trade(s), "
            f"{tally.total_qty} total qty)"
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
        # RALF's error field is DETAIL, not MSG (CALF's error field name) --
        # see protocol reference §10.
        code = msg.fields.get("CODE", "?")
        detail = msg.fields.get("DETAIL", "")
        print(f"ERR   {code}: {detail}", file=sys.stderr)
    else:
        print(f"{msg.msg_type} {msg.fields}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "RALF subscriber example: role-entitled channel subscription "
            "plus a de-duplicated per-symbol executed-volume tally."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5580)
    parser.add_argument("--client", default="ext-client-01")
    parser.add_argument(
        "--role",
        default="CLEARING",
        choices=["CLEARING", "DROP_COPY", "AUDIT"],
    )
    parser.add_argument(
        "--channels",
        default=None,
        help="Comma-separated channels to subscribe; defaults to every "
        "channel --role is entitled to (CLEARING->CLEARING, "
        "DROP_COPY->DROP_COPY, AUDIT->all three). Requesting a channel "
        "outside the role's entitlement will get ERR|CODE=ENTITLEMENT_DENIED.",
    )
    parser.add_argument("--symbols", default="*", help="Symbol scope for SUB")
    parser.add_argument("--lastseq", default="0")
    args = parser.parse_args()

    channels = (
        [c.strip().upper() for c in args.channels.split(",") if c.strip()]
        if args.channels
        else list(_ROLE_CHANNELS[args.role])
    )

    seq_tracker = ChannelSequenceTracker()
    exec_tracker = ExecTracker()

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

        subscribe(sock, channels, args.symbols)
        print(f"Subscribed CH={channels} SYM={args.symbols} as role={args.role}")

        connection_error: Exception | None = None
        try:
            while True:
                msg = parse_ralf_line(reader.recv_line())
                _handle_message(msg, seq_tracker, exec_tracker)
        except KeyboardInterrupt:
            print("\ninterrupted, closing connection", file=sys.stderr)
        except (RuntimeError, OSError) as exc:
            connection_error = exc
            print(f"connection lost: {exc}", file=sys.stderr)

    print()
    print(exec_tracker.summary())
    if connection_error is not None:
        sys.exit(1)


if __name__ == "__main__":
    main()
