#!/usr/bin/env python3
"""Full working CALF subscriber example.

Goes beyond a single trivial subscription: top-of-book (`TOP`), trade
prints (`TRADE`), session/symbol state (`STATE`, including the `SYM=*`
wildcard), a Level 2 depth-of-book ladder (`DEPTH`), and an optional index
level feed (`INDEX`) -- one client, several channels, each parsed and put
to some use (a live top-of-book cache, a formatted depth ladder, gap
detection) rather than just dumped to the terminal as raw fields.

See docs/user-guide/920-app-calf-protocol.md for the normative wire
contract this client follows.

Uses calf_parser.py to parse and build CALF lines.
"""

from __future__ import annotations

import argparse
import socket
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from calf_parser import CalfMessage, build_calf_line, parse_calf_line

# Error codes the protocol defines as connection-terminal (see "Terminal
# behavior" in the protocol reference). Anything else -- e.g.
# RATE_LIMITED, or a code introduced by a future protocol revision -- is
# treated as non-terminal: log it and keep reading.
_TERMINAL_ERROR_CODES = frozenset(
    {"PROTO_MISMATCH", "AUTH_REQUIRED", "SLOW_CLIENT", "BAD_MESSAGE"}
)

# Channels guaranteed to exist even when a gateway build predates the
# WELCOME|CH_SUPPORTED= advertisement (see the WELCOME field table).
_BASELINE_CHANNELS = frozenset({"TOP", "TRADE", "STATE"})


class LineReader:
    """Buffers raw socket bytes and yields one decoded line at a time.

    TCP is a byte stream, not a message queue: one recv() call may return
    half a line, a whole line, or several lines concatenated together, so
    a real client must buffer and split on '\\n' itself rather than assume
    each recv() lines up with one CALF message.
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
    sock.sendall(build_calf_line(msg_type, fields).encode("utf-8"))


def subscribe(
    sock: socket.socket, channels: Iterable[str], symbols: Iterable[str]
) -> None:
    """One SUB request covering the Cartesian product of channels x symbols."""
    send_line(sock, "SUB", {"CH": ",".join(channels), "SYM": ",".join(symbols)})


@dataclass
class TopOfBook:
    """Latest known top-of-book state for one symbol, as seen client-side.

    `MD` updates omit sides that did not change, so this must be merged
    into persistent state rather than treated as a full replacement --
    printing a raw `MD` line in isolation would show blanks for whichever
    side didn't move.
    """

    bid: str = "-"
    bid_size: str = "-"
    ask: str = "-"
    ask_size: str = "-"
    last: str = "-"

    def apply(self, fields: dict[str, str]) -> None:
        self.bid = fields.get("BID", self.bid)
        self.bid_size = fields.get("BIDSZ", self.bid_size)
        self.ask = fields.get("ASK", self.ask)
        self.ask_size = fields.get("ASKSZ", self.ask_size)
        self.last = fields.get("LAST", self.last)

    def render(self, symbol: str) -> str:
        return (
            f"TOP   {symbol:<8} bid {self.bid:>10} x{self.bid_size:<6} "
            f"ask {self.ask:>10} x{self.ask_size:<6} last {self.last}"
        )


class SequenceTracker:
    """Detects gaps in the per-(CH, SYM) SEQ counters CALF streams use.

    A gap means either a bug in this client's line-buffering or a
    dropped/delayed segment the OS didn't fully recover -- either way,
    client-side state derived from the stream (TopOfBook, the depth
    ladder, ...) may now be stale, so surfacing the gap immediately is
    more useful than silently continuing with wrong data. A production
    client would typically resync here (fresh SUB, or HELLO|RESUME=1);
    this example only reports it.
    """

    def __init__(self) -> None:
        self._last_seq: dict[tuple[str, str], int] = {}

    def observe(self, channel: str, symbol: str, seq_field: str | None) -> None:
        if not channel or not seq_field:
            return
        try:
            seq = int(seq_field)
        except ValueError:
            return
        key = (channel, symbol)
        previous = self._last_seq.get(key)
        if previous is not None and seq != previous + 1:
            print(
                f"!! sequence gap on ({channel},{symbol}): "
                f"expected {previous + 1}, got {seq}",
                file=sys.stderr,
            )
        self._last_seq[key] = seq


def render_depth_side(label: str, levels: str | None) -> str:
    """Format one side ("BIDS"/"ASKS") of a DEPTH/SNAP ladder for display.

    Levels are encoded "PRICE:QTY:COUNT,PRICE:QTY:COUNT,..." -- see the
    "Level encoding grammar" in the protocol reference. A side is omitted
    entirely on the wire (not sent as an empty string) when that side of
    the book has no resting orders yet.
    """
    if not levels:
        return f"        {label}: (none)"
    rows = []
    for entry in levels.split(","):
        price, qty, count = entry.split(":")
        rows.append(f"          {price:>10} x{qty:<8} ({count} orders)")
    return f"        {label}:\n" + "\n".join(rows)


def _handle_message(
    msg: CalfMessage, books: dict[str, TopOfBook], seq_tracker: SequenceTracker
) -> None:
    channel = msg.fields.get("CH", "")
    symbol = msg.fields.get("SYM", "")
    seq_tracker.observe(channel, symbol, msg.fields.get("SEQ"))

    if channel == "TOP" and msg.msg_type in ("SNAP", "MD"):
        book = books.setdefault(symbol, TopOfBook())
        book.apply(msg.fields)
        print(book.render(symbol))
    elif msg.msg_type == "TRADE":
        print(
            f"TRADE {symbol:<8} {msg.fields.get('QTY', '?'):>6} @ "
            f"{msg.fields.get('PX', '?'):>10} ({msg.fields.get('SIDE', '?')})"
        )
    elif channel == "STATE" and msg.msg_type in ("SNAP", "STATE"):
        prev = msg.fields.get("PREV")
        prev_note = f" (was {prev})" if prev else ""
        scope = "session" if symbol == "*" else symbol
        print(f"STATE {scope:<8} -> {msg.fields.get('SESSION', '?')}{prev_note}")
    elif channel == "DEPTH" and msg.msg_type in ("SNAP", "DEPTH"):
        print(f"DEPTH {symbol} (levels={msg.fields.get('LEVELS', '?')}):")
        print(render_depth_side("BIDS", msg.fields.get("BIDS")))
        print(render_depth_side("ASKS", msg.fields.get("ASKS")))
    elif channel == "INDEX" and msg.msg_type in ("SNAP", "IDX"):
        chg = msg.fields.get("CHG")
        pct = msg.fields.get("PCTCHG")
        change_note = f" chg={chg} ({pct}%)" if chg else ""
        print(f"INDEX {symbol:<8} level={msg.fields.get('LEVEL', '?')}{change_note}")
    elif msg.msg_type == "HB":
        print("HB    (gateway heartbeat)")
    elif msg.msg_type == "ERR":
        code = msg.fields.get("CODE", "?")
        detail = msg.fields.get("MSG", "")
        print(f"ERR   {code}: {detail}", file=sys.stderr)
        if code in _TERMINAL_ERROR_CODES:
            raise SystemExit(f"gateway closed the session ({code})")
    else:
        print(f"{msg.msg_type} {msg.fields}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "CALF subscriber example: top-of-book, trades, session/symbol "
            "state, Level 2 depth, and (optionally) an index feed."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5570)
    parser.add_argument("--client", default="ext-client-01")
    parser.add_argument(
        "--symbols",
        default="AAPL",
        help="Comma-separated symbols to subscribe TOP/TRADE/STATE/DEPTH for",
    )
    parser.add_argument(
        "--index",
        default="",
        help="Optional index id to also subscribe on the INDEX channel "
        "(e.g. EDU100); omit to skip the index feed entirely",
    )
    parser.add_argument(
        "--no-state-wildcard",
        action="store_true",
        help="Skip the extra SUB|CH=STATE|SYM=* session-wide subscription",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Enable single-stream resume"
    )
    parser.add_argument("--resume-ch", default="TOP")
    parser.add_argument("--resume-sym", default="AAPL")
    parser.add_argument("--lastseq", default="0")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    hello_fields = {"CLIENT": args.client, "PROTO": "CALF1"}
    if args.resume:
        hello_fields.update(
            {
                "RESUME": "1",
                "CH": args.resume_ch,
                "SYM": args.resume_sym,
                "LASTSEQ": args.lastseq,
            }
        )

    books: dict[str, TopOfBook] = {}
    seq_tracker = SequenceTracker()

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        reader = LineReader(sock)

        send_line(sock, "HELLO", hello_fields)
        welcome = parse_calf_line(reader.recv_line())
        print(f"WELCOME: type={welcome.msg_type} fields={welcome.fields}")

        # A gateway build that predates WELCOME|CH_SUPPORTED= omits the
        # field entirely; fall back to the channels guaranteed since CALF
        # 1.0.0 rather than risk an ERR|CODE=INVALID_CHANNEL by assuming
        # DEPTH/INDEX/wildcard support that may not be there.
        raw_supported = welcome.fields.get("CH_SUPPORTED")
        supported = (
            set(raw_supported.split(",")) if raw_supported else set(_BASELINE_CHANNELS)
        )

        # One multi-channel, multi-symbol SUB: the Cartesian product of
        # the supported subset of {TOP,TRADE,STATE,DEPTH} x symbols --
        # not a separate round-trip per channel.
        channels = [ch for ch in ("TOP", "TRADE", "STATE", "DEPTH") if ch in supported]
        subscribe(sock, channels, symbols)
        print(f"Subscribed {channels} for {symbols}")

        # STATE|SYM=* is a *different* stream from the per-symbol STATE
        # subscription above: SYM=* only carries session-wide transitions
        # (PRE_OPEN -> CONTINUOUS -> ...), while SYM=AAPL carries that
        # symbol's own HALT/resume events. A client that wants both needs
        # both subscriptions.
        if not args.no_state_wildcard and "STATE" in supported:
            subscribe(sock, ["STATE"], ["*"])
            print("Subscribed STATE|SYM=* (session-wide state)")

        # INDEX lives in a separate id namespace from instrument symbols
        # and never accepts SYM=*, so it is always its own SUB call.
        if args.index and "INDEX" in supported:
            subscribe(sock, ["INDEX"], [args.index.upper()])
            print(f"Subscribed INDEX for {args.index.upper()}")
        elif args.index:
            print(
                "INDEX channel not advertised by this gateway build; skipping",
                file=sys.stderr,
            )

        try:
            while True:
                _handle_message(parse_calf_line(reader.recv_line()), books, seq_tracker)
        except KeyboardInterrupt:
            print("\ninterrupted, closing connection", file=sys.stderr)
        except (RuntimeError, OSError) as exc:
            print(f"connection lost: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
