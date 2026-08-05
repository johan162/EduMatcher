#!/usr/bin/env python3
"""Full working CALF subscriber example.

Goes beyond a single trivial subscription: top-of-book (`TOP`), trade
prints (`TRADE`), session/symbol state (`STATE`, including the `SYM=*`
wildcard), a Level 2 depth-of-book ladder (`DEPTH`), and an optional index
level feed (`INDEX`) -- one client, several channels, each parsed and put
to some use (a live top-of-book cache, a formatted depth ladder, gap
detection and repair) rather than just dumped to the terminal as raw
fields.

Two things here are worth copying rather than reinventing:

* **Per-symbol display precision.** `WELCOME|REF=` and the `SYMBOLS` reply
  carry `SYM:DECIMALS` tuples. A client that renders a price without them
  is guessing, and guesses right only for the instruments that happen to
  quote to two decimals.
* **Gap detection *and* repair.** Noticing a gap is half the job; `RESUME`
  is the other half. The subtleties that make this more than a two-line
  change -- replay overlapping live traffic, and `SNAP` as a baseline --
  are commented at `SequenceTracker` below.

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

# Channels whose current state a SNAP can express, and so the only ones a
# REPLAY_MISS is followed by a fresh baseline on. TRADE and AUCTION carry
# discrete events: a print that was missed is missed (protocol reference,
# "Reconnect behavior").
_SNAPSHOT_CHANNELS = frozenset({"TOP", "STATE", "INDEX", "DEPTH", "CB"})

# What a price means when the gateway told us nothing about the symbol --
# the documented fallback, not a guess of our own.
_DEFAULT_TICK_DECIMALS = 2


class ReferenceData:
    """Per-symbol display precision, from `WELCOME|REF=` / `SYMBOLS|REF=`.

    `REF` is a comma-separated list of `SYM:DECIMALS` tuples. Its mere
    *presence* is the capability signal: a gateway too old to send it
    leaves this empty and every price falls back to the documented default
    of 2 -- knowingly, rather than by accident.

    Merged rather than replaced, because `WELCOME` and the `SYMBOLS` reply
    are two views of the same reference data arriving at different moments.
    """

    def __init__(self) -> None:
        self._decimals: dict[str, int] = {}

    def learn(self, ref_field: str | None) -> None:
        if not ref_field:
            return
        for entry in ref_field.split(","):
            symbol, _, raw = entry.partition(":")
            try:
                self._decimals[symbol.strip().upper()] = int(raw)
            except ValueError:
                continue  # a future tuple shape (SYM:DEC:MULT:CCY) we don't parse

    def decimals(self, symbol: str) -> int:
        return self._decimals.get(symbol, _DEFAULT_TICK_DECIMALS)

    def price(self, symbol: str, raw: str | None) -> str:
        """Render a wire price at the instrument's own precision."""
        if raw is None or raw == "-":
            return "-"
        try:
            return f"{float(raw):.{self.decimals(symbol)}f}"
        except ValueError:
            return raw


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

    def render(self, symbol: str, refdata: ReferenceData) -> str:
        # Every price goes through `refdata`: the instrument's own
        # tick_decimals, not this client's assumption about them.
        return (
            f"TOP   {symbol:<8} bid {refdata.price(symbol, self.bid):>10} "
            f"x{self.bid_size:<6} ask {refdata.price(symbol, self.ask):>10} "
            f"x{self.ask_size:<6} last {refdata.price(symbol, self.last)}"
        )


class SequenceTracker:
    """Detects gaps in the per-(CH, SYM) SEQ counters, and repairs them.

    A gap means client-side state derived from the stream (TopOfBook, the
    depth ladder, ...) may now be stale, so it is worth both surfacing and
    closing. `RESUME|CH=..|SYM=..|LASTSEQ=..` is a standalone, repeatable
    command -- send one per stream, whenever a gap appears, not only after
    a reconnect.

    Three rules make this correct rather than merely plausible:

    1. **A replay is not disjoint from live traffic.** `RESUME|LASTSEQ=n`
       returns *everything* the gateway still buffers past `n`, and `n` is
       this client's position from before the gap -- so the reply re-sends
       the message that revealed the gap, plus anything that arrived live
       while the request was in flight. Replayed and live lines share one
       ordered connection, so duplicates always arrive after their
       originals. `_holes` is what separates the backfill actually wanted
       from a message already handled: without it, a client either prints
       every trade twice or throws away the repair it just asked for.
    2. **A SNAP re-baselines and is never a gap.** It re-anchors the stream
       wherever the gateway now is. Gap-checking one would ask to replay
       history it just superseded -- and since a `REPLAY_MISS` is answered
       with a `SNAP`, would loop `RESUME` against a window already known to
       be too old.
    3. **Never let a lower SEQ move the baseline backward.** That turns the
       next ordinary message into a phantom gap, or hides a real one.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._last_seq: dict[tuple[str, str], int] = {}
        self._holes: dict[tuple[str, str], tuple[int, int]] = {}

    def accept(
        self, msg_type: str, channel: str, symbol: str, seq_field: str | None
    ) -> bool:
        """Whether the caller should go on to process this message.

        False means a duplicate the gateway replayed and this client has
        already handled.
        """
        if not channel or not seq_field:
            return True  # nothing to sequence against; pass it through
        try:
            seq = int(seq_field)
        except ValueError:
            return True
        if seq <= 0:
            return True

        key = (channel, symbol)
        previous = self._last_seq.get(key)

        if msg_type == "SNAP":  # rule 2
            self._last_seq[key] = seq
            self._holes.pop(key, None)
            return True

        if previous is None:  # first sighting establishes the baseline
            self._last_seq[key] = seq
            return True

        if seq <= previous:  # rule 1 / rule 3
            low, high = self._holes.get(key, (0, -1))
            if not low <= seq <= high:
                return False  # already seen it
            if seq + 1 > high:
                self._holes.pop(key, None)
            else:
                self._holes[key] = (seq + 1, high)
            return True

        self._last_seq[key] = seq
        if seq == previous + 1:
            return True

        print(
            f"!! sequence gap on ({channel},{symbol}): "
            f"expected {previous + 1}, got {seq} -- resuming",
            file=sys.stderr,
        )
        self._holes[key] = (previous + 1, seq - 1)
        send_line(
            self._sock,
            "RESUME",
            {"CH": channel, "SYM": symbol, "LASTSEQ": str(previous)},
        )
        return True

    def replay_missed(self, channel: str, symbol: str) -> None:
        """The gap outlived the gateway's replay window: it is permanent.

        On `TOP`/`STATE`/`INDEX`/`DEPTH`/`CB` a fresh `SNAP` follows this
        error and re-baselines the stream. On `TRADE`/`AUCTION` nothing
        follows, because there is no snapshot of a print that already
        happened -- a client presenting the tape as a record should mark
        the hole rather than close over it.
        """
        self._holes.pop((channel, symbol), None)
        if channel and channel not in _SNAPSHOT_CHANNELS:
            print(
                f"!! gap on ({channel},{symbol}) is permanent: "
                f"outside the gateway's replay window, and this channel "
                f"has no SNAP to fall back on",
                file=sys.stderr,
            )


def render_depth_side(
    label: str, levels: str | None, symbol: str, refdata: ReferenceData
) -> str:
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
        rows.append(
            f"          {refdata.price(symbol, price):>10} x{qty:<8} ({count} orders)"
        )
    return f"        {label}:\n" + "\n".join(rows)


def _handle_message(
    msg: CalfMessage,
    books: dict[str, TopOfBook],
    seq_tracker: SequenceTracker,
    refdata: ReferenceData,
) -> None:
    channel = msg.fields.get("CH", "")
    symbol = msg.fields.get("SYM", "")

    # A replayed duplicate is dropped here, before it can be applied twice.
    if not seq_tracker.accept(msg.msg_type, channel, symbol, msg.fields.get("SEQ")):
        return

    # A SNAP on TRADE or AUCTION carries an envelope and no payload -- an
    # older gateway sends one after REPLAY_MISS. Decoded by CH like any
    # other line it reads as a print of zero shares at zero price, so drop
    # it rather than show a trade that never happened.
    if msg.msg_type == "SNAP" and channel and channel not in _SNAPSHOT_CHANNELS:
        return

    if channel == "TOP" and msg.msg_type in ("SNAP", "MD"):
        book = books.setdefault(symbol, TopOfBook())
        book.apply(msg.fields)
        print(book.render(symbol, refdata))
    elif msg.msg_type == "TRADE":
        print(
            f"TRADE {symbol:<8} {msg.fields.get('QTY', '?'):>6} @ "
            f"{refdata.price(symbol, msg.fields.get('PX')):>10} "
            f"({msg.fields.get('SIDE', '?')})"
        )
    elif channel == "STATE" and msg.msg_type in ("SNAP", "STATE"):
        prev = msg.fields.get("PREV")
        prev_note = f" (was {prev})" if prev else ""
        scope = "session" if symbol == "*" else symbol
        print(f"STATE {scope:<8} -> {msg.fields.get('SESSION', '?')}{prev_note}")
    elif channel == "DEPTH" and msg.msg_type in ("SNAP", "DEPTH"):
        print(f"DEPTH {symbol} (levels={msg.fields.get('LEVELS', '?')}):")
        print(render_depth_side("BIDS", msg.fields.get("BIDS"), symbol, refdata))
        print(render_depth_side("ASKS", msg.fields.get("ASKS"), symbol, refdata))
    elif channel == "INDEX" and msg.msg_type in ("SNAP", "IDX"):
        chg = msg.fields.get("CHG")
        pct = msg.fields.get("PCTCHG")
        change_note = f" chg={chg} ({pct}%)" if chg else ""
        print(f"INDEX {symbol:<8} level={msg.fields.get('LEVEL', '?')}{change_note}")
    elif msg.msg_type == "SYMBOLS":
        # Asked for explicitly at startup: WELCOME|SYMBOLS= is optional, so
        # this reply is the reliable route to the universe -- and to REF.
        refdata.learn(msg.fields.get("REF"))
        print(
            f"SYMBOLS {msg.fields.get('COUNT', '?')}: {msg.fields.get('SYMBOLS', '')}"
        )
    elif msg.msg_type == "HB":
        print("HB    (gateway heartbeat)")
    elif msg.msg_type == "ERR":
        code = msg.fields.get("CODE", "?")
        detail = msg.fields.get("MSG", "")
        print(f"ERR   {code}: {detail}", file=sys.stderr)
        if code == "REPLAY_MISS":
            seq_tracker.replay_missed(
                msg.fields.get("CH", ""), msg.fields.get("SYM", "")
            )
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
        "--resume",
        action="store_true",
        help="Send an explicit RESUME for one stream after the handshake, "
        "to demonstrate replay from a known position. Gaps found while "
        "running are resumed automatically regardless of this flag",
    )
    parser.add_argument("--resume-ch", default="TOP")
    parser.add_argument("--resume-sym", default="AAPL")
    parser.add_argument("--lastseq", default="0")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    books: dict[str, TopOfBook] = {}
    refdata = ReferenceData()

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        reader = LineReader(sock)
        seq_tracker = SequenceTracker(sock)

        # HELLO carries identification only. Replay is requested with the
        # standalone RESUME command below -- as a HELLO flag it could only
        # ever run once per connection, which is useless to a client
        # following more than one stream.
        send_line(sock, "HELLO", {"CLIENT": args.client, "PROTO": "CALF1"})
        welcome = parse_calf_line(reader.recv_line())
        print(f"WELCOME: type={welcome.msg_type} fields={welcome.fields}")

        # Display precision, if this gateway is new enough to advertise it.
        # The presence of REF is the capability signal; its absence means
        # falling back to 2 decimals knowingly rather than by accident.
        refdata.learn(welcome.fields.get("REF"))
        if welcome.fields.get("REF") is None:
            print(
                "note: gateway sent no REF=; prices render at the default "
                f"{_DEFAULT_TICK_DECIMALS} decimals",
                file=sys.stderr,
            )

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

        # Ask rather than rely on WELCOME|SYMBOLS=, which is optional and
        # absent whenever the gateway could not read an engine config. The
        # reply carries REF= too, so this doubles as the reliable route to
        # display precision.
        send_line(sock, "SYMBOLS", {})

        # One explicit RESUME, to show the shape. Note it is a command in
        # its own right, sent after WELCOME and repeatable -- send one per
        # stream being recovered.
        if args.resume:
            send_line(
                sock,
                "RESUME",
                {
                    "CH": args.resume_ch.upper(),
                    "SYM": args.resume_sym.upper(),
                    "LASTSEQ": args.lastseq,
                },
            )
            print(
                f"RESUME {args.resume_ch.upper()}/{args.resume_sym.upper()} "
                f"from LASTSEQ={args.lastseq}"
            )

        try:
            while True:
                _handle_message(
                    parse_calf_line(reader.recv_line()), books, seq_tracker, refdata
                )
        except KeyboardInterrupt:
            print("\ninterrupted, closing connection", file=sys.stderr)
        except (RuntimeError, OSError) as exc:
            print(f"connection lost: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
