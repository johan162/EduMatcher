#!/usr/bin/env python3
"""Interactive ALF client connecting to pm-alf-gwy over TCP.

Mimics the workflow of pm-alf-console but as an external client:
no ZMQ dependency, no edumatcher package import — just a TCP socket
and the ALF text protocol.

Features:
  - Tab-completion for commands and field names (uses readline)
  - Command history (persisted to ~/.alf_client_history)
  - Background receive thread with interleaved event display
  - All trading commands: NEW, AMEND, CANCEL, QUOTE, QUOTE_CANCEL,
    KILL, SYMBOLS, ORDERS, QBOOT, PING
  - Session queries: POS (position/P&L tracking), STATUS
  - Multi-line responses displayed as formatted tables

Usage:
  python3 alf_client.py --id TRADER01
  python3 alf_client.py --host 10.0.0.5 --port 5565 --id TRADER01

Requires Python 3.9+ and the alf_parser.py library in the same directory.
"""

from __future__ import annotations

import argparse
import readline
import sys
import threading
from datetime import datetime
from pathlib import Path

from alf_parser import AlfMessage, AlfParseError, AlfSession

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()

_GREEN = "\033[32m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_CYAN = "\033[36m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_MAGENTA = "\033[35m" if _USE_COLOR else ""
_DIM = "\033[2m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""

HISTORY_FILE = Path.home() / ".alf_client_history"

_HELP_TEXT = f"""
{_BOLD}ALF Gateway Client{_RESET} — external client for pm-alf-gwy

{_BOLD}Order entry{_RESET}
  NEW|SYM=<s>|SIDE=BUY|SELL|TYPE=<t>|QTY=<n>[|PRICE=<p>][|STOP=<p>][|TRAIL=<n>]
              [|VISIBLE=<n>][|TIF=DAY|GTC|ATO|ATC][|SMP=NONE|CANCEL_AGGRESSOR|...]
  ORDER TYPES: MARKET  LIMIT  STOP  STOP_LIMIT  FOK  IOC  ICEBERG  TRAILING_STOP
  OCO:   NEW|TYPE=OCO|OCO_ID=<id>|SYM=<s>|QTY=<n>|TIF=<t>
              |LEG1_SIDE=BUY|SELL|LEG1_TYPE=<t>[|LEG1_PRICE=<p>][|LEG1_STOP=<p>]
              |LEG2_SIDE=BUY|SELL|LEG2_TYPE=<t>[|LEG2_PRICE=<p>][|LEG2_STOP=<p>]
  COMBO: NEW|TYPE=COMBO|COMBO_ID=<id>|COMBO_TYPE=AON|TIF=<t>|LEG_COUNT=<n>
              |LEG0.SYM=<s>|LEG0.SIDE=BUY|SELL|LEG0.QTY=<n>[|LEG0.PRICE=<p>]
              |LEG1.SYM=<s>|LEG1.SIDE=BUY|SELL|LEG1.QTY=<n>[|LEG1.PRICE=<p>]

{_BOLD}Order management{_RESET}
  AMEND|ID=<order-id>[|PRICE=<p>][|QTY=<n>]
  CANCEL|ID=<order-id>          — single order
  CANCEL|COMBO_ID=<id>          — combo and all legs
  CANCEL|OCO_ID=<id>            — OCO pair
  QUOTE|SYM=<s>|BID=<p>|ASK=<p>|BID_QTY=<n>|ASK_QTY=<n>[|TIF=...|QUOTE_ID=...]
  QUOTE_CANCEL|SYM=<s>
  KILL[|SYM=<s>]                — cancel all exposure (optional symbol scope)

{_BOLD}Queries{_RESET}
  SYMBOLS                        List configured instruments
  ORDERS                         Show resting orders for this gateway
  QBOOT[|SYM=<s>]               Quote bootstrap state from engine

{_BOLD}Session{_RESET}
  PING                           Liveness probe
  POS                            Show tracked positions and unrealized P&L
  STATUS                         Show session and connection info
  HELP                           This help text
  EXIT / QUIT                    Disconnect and exit
""".strip()


# ---------------------------------------------------------------------------
# Tab completion
# ---------------------------------------------------------------------------

_TOP_CMDS = [
    "NEW",
    "AMEND",
    "CANCEL",
    "QUOTE",
    "QUOTE_CANCEL",
    "QBOOT",
    "KILL",
    "SYMBOLS",
    "ORDERS",
    "PING",
    "POS",
    "STATUS",
    "HELP",
    "EXIT",
    "QUIT",
]

_CMD_FIELDS: dict[str, list[str]] = {
    "NEW": [
        "SYM=",
        "SIDE=",
        "TYPE=",
        "QTY=",
        "PRICE=",
        "STOP=",
        "TRAIL=",
        "VISIBLE=",
        "TIF=",
        "SMP=",
    ],
    "AMEND": ["ID=", "PRICE=", "QTY="],
    "CANCEL": ["ID=", "COMBO_ID=", "OCO_ID="],
    "QUOTE": ["SYM=", "BID=", "ASK=", "BID_QTY=", "ASK_QTY=", "TIF=", "QUOTE_ID="],
    "QUOTE_CANCEL": ["SYM="],
    "QBOOT": ["SYM="],
    "KILL": ["SYM="],
}

_VALUE_OPTS: dict[str, list[str]] = {
    "SIDE": ["BUY", "SELL"],
    "TYPE": [
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "FOK",
        "IOC",
        "ICEBERG",
        "TRAILING_STOP",
        "OCO",
        "COMBO",
    ],
    "TIF": ["DAY", "GTC", "ATO", "ATC"],
    "SMP": ["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"],
    "COMBO_TYPE": ["AON"],
    # OCO / COMBO leg fields
    "LEG1_SIDE": ["BUY", "SELL"],
    "LEG2_SIDE": ["BUY", "SELL"],
    "LEG1_TYPE": ["LIMIT", "MARKET", "STOP", "STOP_LIMIT", "TRAILING_STOP"],
    "LEG2_TYPE": ["LIMIT", "MARKET", "STOP", "STOP_LIMIT", "TRAILING_STOP"],
}
# Also accept LEGn.SIDE and LEGn.TYPE for combos
for _i in range(10):
    _VALUE_OPTS[f"LEG{_i}.SIDE"] = ["BUY", "SELL"]
    _VALUE_OPTS[f"LEG{_i}.TYPE"] = ["LIMIT", "MARKET", "STOP", "STOP_LIMIT"]

_OCO_FIELDS = [
    "OCO_ID=",
    "SYM=",
    "QTY=",
    "TIF=",
    "LEG1_SIDE=",
    "LEG1_TYPE=",
    "LEG1_PRICE=",
    "LEG1_STOP=",
    "LEG1_TRAIL=",
    "LEG2_SIDE=",
    "LEG2_TYPE=",
    "LEG2_PRICE=",
    "LEG2_STOP=",
    "LEG2_TRAIL=",
]

_COMBO_TOP_FIELDS = ["COMBO_ID=", "COMBO_TYPE=", "TIF=", "LEG_COUNT=", "SMP="]
_COMBO_LEG_FIELDS = [".SYM=", ".SIDE=", ".QTY=", ".PRICE=", ".STOP=", ".TYPE="]


def _combo_leg_fields(n_legs: int) -> list[str]:
    return [f"LEG{i}{f}" for i in range(n_legs) for f in _COMBO_LEG_FIELDS]


class _AlfCompleter:
    """Context-aware readline tab completer for the ALF command format."""

    def __init__(self, symbols_ref: list[str]) -> None:
        self._symbols = (
            symbols_ref  # shared reference — updated when gateway sends SYMBOLS
        )
        self._cache: list[str] = []

    def complete(self, text: str, state: int) -> str | None:
        if state == 0:
            self._cache = self._compute(readline.get_line_buffer(), text)
        return self._cache[state] if state < len(self._cache) else None

    def _compute(self, buf: str, text: str) -> list[str]:
        parts = buf.split("|")

        # First token — complete the command verb
        if len(parts) == 1:
            word = text.upper()
            return [c + "|" for c in _TOP_CMDS if c.startswith(word)]

        cmd = parts[0].upper()
        already_keys = {seg.split("=")[0].upper() for seg in parts[1:] if "=" in seg}

        # Value completion: cursor is after KEY=
        if "=" in text:
            key, partial = text.split("=", 1)
            key_up = key.upper()
            partial_up = partial.upper()
            # Resolve LEGn.SIDE → SIDE etc. for value lookup
            bare = key_up.split(".")[-1] if "." in key_up else key_up
            if bare == "SYM":
                candidates = self._symbols or []
            elif key_up in _VALUE_OPTS:
                candidates = _VALUE_OPTS[key_up]
            elif bare in _VALUE_OPTS:
                candidates = _VALUE_OPTS[bare]
            else:
                return []
            return [
                f"{key}={v}" for v in candidates if v.upper().startswith(partial_up)
            ]

        # Field-name completion: suggest next field
        partial_up = text.upper()

        if cmd == "NEW":
            type_val = next(
                (
                    seg.split("=", 1)[1].upper()
                    for seg in parts[1:]
                    if seg.upper().startswith("TYPE=")
                ),
                None,
            )
            if type_val == "OCO":
                fields = _OCO_FIELDS
            elif type_val == "COMBO":
                n_legs = 2
                for seg in parts[1:]:
                    if seg.upper().startswith("LEG_COUNT="):
                        try:
                            n_legs = int(seg.split("=", 1)[1])
                        except ValueError:
                            pass
                fields = _COMBO_TOP_FIELDS + _combo_leg_fields(n_legs)
            else:
                fields = _CMD_FIELDS.get("NEW", [])
        else:
            fields = _CMD_FIELDS.get(cmd, [])

        return [
            f
            for f in fields
            if f.upper().startswith(partial_up) and f.rstrip("=") not in already_keys
        ]


# ---------------------------------------------------------------------------
# Interactive ALF client
# ---------------------------------------------------------------------------


class AlfClient:
    """Interactive ALF client mimicking pm-alf-console over TCP.

    Connects to pm-alf-gwy, starts a background receive thread for event
    display, and presents an interactive readline REPL for command entry.
    """

    def __init__(self, session: AlfSession) -> None:
        self._session = session
        self._prompt = f"[{session.gateway_id}]> "
        self._running = False
        self._print_lock = threading.Lock()

        # State
        self._orders: dict[str, dict[str, str]] = {}  # order_id → fields
        self._positions: dict[str, dict[str, float]] = {}  # symbol → P&L state
        self._session_state: str = "UNKNOWN"

        # Multi-line response accumulation
        self._collecting: str | None = None  # 'SYMBOLS' | 'ORDERS' | 'QBOOT'
        self._collect_header: AlfMessage | None = None
        self._collect_rows: list[AlfMessage] = []

        # Shared symbol list (reference passed to completer)
        self._known_symbols: list[str] = session.known_symbols

        # Readline setup
        self._completer = _AlfCompleter(self._known_symbols)
        readline.set_completer(self._completer.complete)
        readline.set_completer_delims("")  # treat entire input as one word
        readline.parse_and_bind("tab: complete")
        if HISTORY_FILE.exists():
            try:
                readline.read_history_file(str(HISTORY_FILE))
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Thread-safe printing
    # ------------------------------------------------------------------

    def _pr(self, text: str) -> None:
        """Print an event line without garbling the readline prompt."""
        with self._print_lock:
            saved = readline.get_line_buffer()
            sys.stdout.write("\r\033[K")  # CR + erase line
            sys.stdout.write(text + "\n")
            if self._running:
                sys.stdout.write(self._prompt + saved)
            sys.stdout.flush()

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def _handle(
        self, msg: AlfMessage
    ) -> None:  # noqa: C901 — large dispatch intentional
        t = msg.msg_type
        f = msg.fields
        ts = self._ts()

        if t == "HB":
            return  # heartbeat — silently ignore

        if t == "PONG":
            self._pr(f"[{ts}] {_DIM}PONG{_RESET}  {f.get('TS', '')}")
            return

        if t == "SESSION":
            state = f.get("STATE", "?")
            prev = f.get("PREV_STATE", "?")
            self._session_state = state
            self._pr(f"[{ts}] {_YELLOW}SESSION{_RESET}  {prev} → {state}")
            return

        if t == "HALT":
            sym = f.get("SYMBOL", "?")
            level = f.get("LEVEL", "")
            self._pr(f"[{ts}] {_RED}HALT{_RESET}    {sym}  level={level}")
            return

        if t == "RESUME":
            sym = f.get("SYMBOL", "?")
            mode = f.get("MODE", "")
            self._pr(f"[{ts}] {_GREEN}RESUME{_RESET}  {sym}  mode={mode}")
            return

        if t == "TRADE":
            sym = f.get("SYMBOL", "?")
            price = f.get("PRICE", "?")
            qty = f.get("QTY", "?")
            side = f.get("SIDE", "?")
            self._pr(f"[{ts}] {_DIM}TRADE{_RESET}   {sym}  {side} {qty} @{price}")
            return

        if t == "ERR":
            code = f.get("CODE", "?")
            detail = f.get("DETAIL", "")
            self._pr(f"[{ts}] {_RED}ERR{_RESET}  [{code}]  {detail}")
            return

        if t == "ACK":
            oid = f.get("ORDER_ID", "?")
            accepted = f.get("ACCEPTED", "FALSE") == "TRUE"
            reason = f.get("REASON", "")
            short = oid[:8]
            if accepted:
                self._pr(f"[{ts}] {_GREEN}ACK{_RESET}      {short}  order accepted")
                self._orders.setdefault(oid, {}).update(
                    {
                        "id": oid,
                        "symbol": f.get("SYMBOL", ""),
                        "side": f.get("SIDE", ""),
                        "type": f.get("TYPE", ""),
                        "status": "NEW",
                    }
                )
            else:
                self._pr(f"[{ts}] {_RED}REJECTED{_RESET} {short}  {reason}")
            return

        if t == "FILL":
            oid = f.get("ORDER_ID", "?")
            qty = f.get("FILL_QTY", "?")
            price = f.get("FILL_PRICE", "?")
            rem = f.get("REMAINING", "?")
            st = f.get("STATUS", "?")
            self._pr(
                f"[{ts}] {_CYAN}FILL{_RESET}     {oid[:8]}  "
                f"qty={qty} @{price}  remaining={rem}  [{st}]"
            )
            # Position update — use cached order for symbol/side
            order = self._orders.get(oid, {})
            sym = order.get("symbol") or f.get("SYMBOL", "")
            side = order.get("side") or f.get("SIDE", "")
            if sym and side:
                try:
                    self._update_position(sym, side, int(qty), float(price))
                except (ValueError, TypeError):
                    pass
            if oid in self._orders:
                self._orders[oid].update({"remaining": rem, "status": st})
            return

        if t == "AMENDED":
            oid = f.get("ORDER_ID", "?")
            self._pr(
                f"[{ts}] {_MAGENTA}AMENDED{_RESET}  {oid[:8]}  "
                f"price={f.get('PRICE', '-')}  qty={f.get('QTY', '-')}  "
                f"remaining={f.get('REMAINING', '-')}  "
                f"priority_reset={f.get('PRIORITY_RESET', '-')}"
            )
            if oid in self._orders:
                for k in ("PRICE", "QTY", "REMAINING"):
                    if k in f:
                        self._orders[oid][k.lower()] = f[k]
            return

        if t == "CANCELLED":
            oid = f.get("ORDER_ID", "?")
            self._pr(f"[{ts}] {_YELLOW}CANCELLED{_RESET} {oid[:8]}")
            if oid in self._orders:
                self._orders[oid]["status"] = "CANCELLED"
            return

        if t == "EXPIRED":
            oid = f.get("ORDER_ID", "?")
            self._pr(f"[{ts}] {_DIM}EXPIRED{_RESET}  {oid[:8]}")
            if oid in self._orders:
                self._orders[oid]["status"] = "EXPIRED"
            return

        if t == "QUOTE_ACK":
            qid = f.get("QUOTE_ID", "?")
            if f.get("ACCEPTED", "FALSE") == "TRUE":
                bid = f.get("BID_ID", "?")[:8]
                ask = f.get("ASK_ID", "?")[:8]
                self._pr(
                    f"[{ts}] {_GREEN}QUOTE ACK{_RESET}  {qid}  bid={bid} ask={ask}"
                )
            else:
                self._pr(
                    f"[{ts}] {_RED}QUOTE REJ{_RESET}  {qid}  {f.get('REASON', '')}"
                )
            return

        if t == "QUOTE_STATUS":
            qid = f.get("QUOTE_ID", "?")
            st = f.get("STATUS", "?")
            rsn = f.get("REASON", "")
            self._pr(
                f"[{ts}] {_CYAN}QUOTE {st}{_RESET}  {qid}" + (f"  {rsn}" if rsn else "")
            )
            return

        if t == "COMBO_ACK":
            cid = f.get("COMBO_ID", "?")
            if f.get("ACCEPTED", "FALSE") == "TRUE":
                self._pr(f"[{ts}] {_GREEN}COMBO ACK{_RESET}  {cid}  combo accepted")
            else:
                self._pr(
                    f"[{ts}] {_RED}COMBO REJ{_RESET}  {cid}  {f.get('REASON', '')}"
                )
            return

        if t == "COMBO_STATUS":
            cid = f.get("COMBO_ID", "?")
            st = f.get("STATUS", "?")
            rsn = f.get("REASON", "")
            colours = {
                "MATCHED": _GREEN,
                "PARTIALLY_MATCHED": _YELLOW,
                "FAILED": _RED,
                "CANCELLED": _RED,
            }
            c = colours.get(st, "")
            self._pr(
                f"[{ts}] {c}COMBO {st}{_RESET}  {cid}" + (f"  {rsn}" if rsn else "")
            )
            return

        if t == "OCO_ACK":
            oid = f.get("OCO_ID", "?")
            if f.get("ACCEPTED", "FALSE") == "TRUE":
                l1 = f.get("LEG1_ID", "?")[:8]
                l2 = f.get("LEG2_ID", "?")[:8]
                self._pr(f"[{ts}] {_GREEN}OCO ACK{_RESET}    {oid}  legs={l1}/{l2}")
            else:
                self._pr(
                    f"[{ts}] {_RED}OCO REJ{_RESET}    {oid}  {f.get('REASON', '')}"
                )
            return

        if t == "OCO_CANCELLED":
            oid = f.get("OCO_ID", "?")
            sibl = f.get("CANCELLED_ID", "?")[:8]
            self._pr(
                f"[{ts}] {_YELLOW}OCO CANCEL{_RESET} {oid}  sibling={sibl}  {f.get('REASON', '')}"
            )
            return

        if t == "KILL_ACK":
            if f.get("ACCEPTED", "FALSE") == "TRUE":
                self._pr(
                    f"[{ts}] {_YELLOW}KILL ACK{_RESET}  "
                    f"orders={f.get('ORDERS', 0)}  quotes={f.get('QUOTES', 0)}"
                )
            else:
                self._pr(f"[{ts}] {_RED}KILL REJ{_RESET}  {f.get('REASON', '')}")
            return

        # Unknown message type — show raw for debugging
        self._pr(f"[{ts}] {_DIM}{t}{_RESET}  {f}")

    # ------------------------------------------------------------------
    # Multi-line response flushing
    # ------------------------------------------------------------------

    def _flush_collected(self) -> None:
        kind = self._collecting
        hdr = self._collect_header
        rows = self._collect_rows

        if kind == "SYMBOLS":
            syms = [r.fields.get("SYM", "?") for r in rows]
            # Update known symbols so tab-completion picks them up
            self._known_symbols.clear()
            self._known_symbols.extend(syms)
            self._session.set_known_symbols(syms)
            lines = [f"  {_BOLD}{'SYM':<10} TICK{_RESET}"]
            for r in rows:
                sym = r.fields.get("SYM", "?")
                tick = r.fields.get("TICK", "-")
                lines.append(f"  {sym:<10} {tick}")
            count = hdr.fields.get("COUNT", "?") if hdr else "?"
            self._pr(f"\n{_BOLD}Symbols ({count}){_RESET}\n" + "\n".join(lines) + "\n")

        elif kind == "ORDERS":
            gw = hdr.fields.get("GW", "") if hdr else ""
            header = (
                f"  {'ID'[:8]:<8}  {'SYM':<6} {'SIDE':<5} {'TYPE':<11} "
                f"{'QTY':>6} {'REM':>6} {'PRICE':>8}  STATUS"
            )
            divider = "  " + "-" * 66
            lines = [f"\n{_BOLD}Orders — {gw}{_RESET}", header, divider]
            for r in rows:
                f_ = r.fields
                oid = f_.get("ID", "?")[:8]
                sym = f_.get("SYM", "?")
                side = f_.get("SIDE", "?")
                typ = f_.get("TYPE", "?")
                qty = f_.get("QTY", "?")
                rem = f_.get("REMAINING", "?")
                prc = f_.get("PRICE", "-")
                st = f_.get("STATUS", "?")
                # Update local cache
                if f_.get("ID"):
                    self._orders.setdefault(f_["ID"], {}).update(
                        {
                            "id": f_["ID"],
                            "symbol": sym,
                            "side": side,
                            "type": typ,
                            "qty": qty,
                            "remaining": rem,
                            "price": prc,
                            "status": st,
                        }
                    )
                lines.append(
                    f"  {oid:<8}  {sym:<6} {side:<5} {typ:<11} "
                    f"{qty:>6} {rem:>6} {prc:>8}  {st}"
                )
            count = hdr.fields.get("COUNT", "?") if hdr else "?"
            if not rows:
                lines.append("  (no resting orders)")
            lines.append(f"\n  {count} order(s) total\n")
            self._pr("\n".join(lines))

        elif kind == "QBOOT":
            header = (
                f"  {'QUOTE_ID':<20} {'SYM':<6} {'BID':>8} {'ASK':>8} "
                f"{'B_QTY':>6} {'A_QTY':>6}  STATUS"
            )
            divider = "  " + "-" * 68
            lines = [f"\n{_BOLD}Quote Bootstrap{_RESET}", header, divider]
            for r in rows:
                f_ = r.fields
                lines.append(
                    f"  {f_.get('QUOTE_ID', '?'):<20} {f_.get('SYM', '?'):<6} "
                    f"{f_.get('BID', '-'):>8} {f_.get('ASK', '-'):>8} "
                    f"{f_.get('BID_QTY', '-'):>6} {f_.get('ASK_QTY', '-'):>6}  "
                    f"{f_.get('STATUS', '?')}"
                )
            count = hdr.fields.get("COUNT", "?") if hdr else "?"
            if not rows:
                lines.append("  (no active quotes)")
            lines.append(f"\n  {count} quote(s) total\n")
            self._pr("\n".join(lines))

    # ------------------------------------------------------------------
    # Receive thread
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        """Background thread: read gateway messages and display them."""
        while self._running:
            try:
                msg = self._session.recv_msg()
            except AlfParseError:
                continue  # malformed line — skip
            except Exception as exc:
                if self._running:
                    self._pr(f"\n{_RED}Connection lost: {exc}{_RESET}\n")
                    self._running = False
                return

            t = msg.msg_type

            # Multi-line accumulation
            if self._collecting:
                if t == "SYMBOL" and self._collecting == "SYMBOLS":
                    self._collect_rows.append(msg)
                    continue
                if t == "ORDER" and self._collecting == "ORDERS":
                    self._collect_rows.append(msg)
                    continue
                if t == "QUOTE" and self._collecting == "QBOOT":
                    self._collect_rows.append(msg)
                    continue
                if t == "END" and msg.fields.get("TYPE") == self._collecting:
                    self._flush_collected()
                    self._collecting = None
                    self._collect_header = None
                    self._collect_rows = []
                    continue
                # Non-matching message while collecting — pass through

            if t == "SYMBOLS":
                self._collecting = "SYMBOLS"
                self._collect_header = msg
                self._collect_rows = []
                continue
            if t == "ORDERS":
                self._collecting = "ORDERS"
                self._collect_header = msg
                self._collect_rows = []
                continue
            if t == "QBOOT":
                self._collecting = "QBOOT"
                self._collect_header = msg
                self._collect_rows = []
                continue

            self._handle(msg)

    # ------------------------------------------------------------------
    # Position tracking (mirrors pm-alf-console logic)
    # ------------------------------------------------------------------

    def _update_position(
        self, symbol: str, side: str, fill_qty: int, fill_price: float
    ) -> None:
        pos = self._positions.setdefault(
            symbol, {"net_qty": 0, "avg_cost": 0.0, "realized_pnl": 0.0}
        )
        signed_qty = fill_qty if side == "BUY" else -fill_qty
        old_qty = pos["net_qty"]
        new_qty = old_qty + signed_qty

        # Realize P&L when reducing or flipping position
        if old_qty != 0 and (
            (old_qty > 0 and signed_qty < 0) or (old_qty < 0 and signed_qty > 0)
        ):
            close_qty = min(abs(signed_qty), abs(old_qty))
            pnl_per = (
                (fill_price - pos["avg_cost"])
                if old_qty > 0
                else (pos["avg_cost"] - fill_price)
            )
            pos["realized_pnl"] += pnl_per * close_qty

        # Update average cost
        if new_qty == 0:
            pos["avg_cost"] = 0.0
        elif (old_qty >= 0 and signed_qty > 0) or (old_qty <= 0 and signed_qty < 0):
            total = pos["avg_cost"] * abs(old_qty) + fill_price * abs(signed_qty)
            pos["avg_cost"] = total / abs(new_qty)
        elif abs(new_qty) > abs(old_qty):
            pos["avg_cost"] = fill_price

        pos["net_qty"] = new_qty

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, line: str) -> bool:
        """Parse and send one command.  Returns False to exit the REPL."""
        raw = line.strip()
        if not raw:
            return True

        parts = raw.split("|")
        cmd = parts[0].upper()

        if cmd in ("EXIT", "QUIT"):
            return False

        if cmd == "HELP":
            with self._print_lock:
                print(_HELP_TEXT)
            return True

        if cmd == "POS":
            self._show_pos()
            return True

        if cmd == "STATUS":
            self._show_status()
            return True

        # All other commands: validate minimally and send to gateway
        try:
            # Reconstruct with normalized verb
            reconstructed = "|".join([cmd] + parts[1:])
            self._session.send_raw(reconstructed)
        except OSError as exc:
            with self._print_lock:
                print(f"{_RED}Send error: {exc}{_RESET}")
        return True

    def _show_pos(self) -> None:
        with self._print_lock:
            print(f"\n{_BOLD}Positions — {self._session.gateway_id}{_RESET}")
            if not any(p["net_qty"] != 0 for p in self._positions.values()):
                print("  (flat — no open positions)")
            else:
                print(
                    f"  {'SYMBOL':<10} {'DIR':<6} {'NET_QTY':>8} "
                    f"{'AVG_COST':>10} {'REALIZED_PNL':>14}"
                )
                print("  " + "-" * 54)
                for sym, pos in self._positions.items():
                    if pos["net_qty"] != 0:
                        direction = "LONG" if pos["net_qty"] > 0 else "SHORT"
                        pnl_str = f"{pos['realized_pnl']:>14.2f}"
                        c = _GREEN if pos["net_qty"] > 0 else _RED
                        print(
                            f"  {sym:<10} {c}{direction:<6}{_RESET} {pos['net_qty']:>8}  "
                            f"{pos['avg_cost']:>10.2f}  {pnl_str}"
                        )
            print()

    def _show_status(self) -> None:
        w = self._session.welcome
        with self._print_lock:
            print(f"\n{_BOLD}Session Status{_RESET}")
            print(f"  Gateway:          {self._session.gateway_id}")
            print(f"  Gateway process:  {w.gw_name}")
            print(f"  Protocol:         {w.proto}")
            print(f"  Heartbeat:        {w.heartbeat_interval}s")
            print(f"  Idle timeout:     {w.idle_timeout}s")
            print(f"  Session state:    {self._session_state}")
            syms = self._session.known_symbols
            print(
                f"  Symbols:          {', '.join(syms) if syms else '(none loaded yet)'}"
            )
            print(
                f"  Open orders:      {sum(1 for o in self._orders.values() if o.get('status') not in ('CANCELLED','FILLED','EXPIRED','REJECTED'))}"
            )
            print()

    # ------------------------------------------------------------------
    # Main REPL
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the background receive thread and enter the readline REPL."""
        self._running = True
        recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        recv_thread.start()

        w = self._session.welcome
        print(
            f"\n{_BOLD}{_GREEN}Gateway {self._session.gateway_id} connected.{_RESET}  "
            f"gw={w.gw_name}  hb={w.heartbeat_interval}s  idle={w.idle_timeout}s\n"
            f"Type {_BOLD}HELP{_RESET} for commands.  Tab=complete  ↑↓=history\n"
        )

        try:
            while self._running:
                try:
                    with self._print_lock:
                        pass  # flush any pending output before prompting
                    line = input(self._prompt)
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not self._dispatch(line):
                    break
                if line.strip():
                    readline.add_history(line)
        finally:
            self._running = False
            try:
                readline.write_history_file(str(HISTORY_FILE))
            except OSError:
                pass
            self._session.close()
            print(f"\n{_BOLD}Disconnected.{_RESET}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive ALF client for pm-alf-gwy",
        epilog="Example: alf_client.py --host 10.0.0.5 --port 5565 --id TRADER01",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Gateway host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=5565, help="Gateway port (default: 5565)"
    )
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help="Gateway ID (must be in engine_config.yaml)",
    )
    parser.add_argument(
        "--client",
        default="alf-client",
        help="Client name for gateway logs (default: alf-client)",
    )
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} as {args.id.upper()} …")
    try:
        session = AlfSession.connect(args.host, args.port, args.id, args.client)
    except Exception as exc:
        print(f"{_RED}Connection failed: {exc}{_RESET}", file=sys.stderr)
        sys.exit(1)

    AlfClient(session).run()


if __name__ == "__main__":
    main()
