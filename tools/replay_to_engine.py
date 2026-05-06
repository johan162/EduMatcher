#!/usr/bin/env python3
"""
replay_to_engine.py — Replay mm_orders.fix + test_orders.fix to the live engine.

Connects as gateway VERIFY01, sends every order in sequence (waiting for each
ACK before proceeding), then requests book snapshots and saves them to
data/verify/engine_result.json.

Requirements
------------
  * The engine must already be running with verify_engine_config.yaml:
        poetry run pm-engine --config data/verify/verify_engine_config.yaml
  * data/verify/mm_orders.fix and test_orders.fix must exist (run
    gen_verification_set.py first).

Usage
-----
    poetry run python tools/replay_to_engine.py
    poetry run python tools/replay_to_engine.py --pull tcp://localhost:5555 \\
                                                 --pub  tcp://localhost:5556
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import zmq

from edumatcher.config import ENGINE_PULL_ADDR, ENGINE_PUB_ADDR
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    encode,
    make_gateway_connect_msg,
    make_order_new_msg,
    make_book_snapshot_request_msg,
)
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VERIFY_DIR    = ROOT / "data" / "verify"
MM_FIX_FILE   = VERIFY_DIR / "mm_orders.fix"
TEST_FIX_FILE = VERIFY_DIR / "test_orders.fix"
ENGINE_RESULT = VERIFY_DIR / "engine_result.json"

GATEWAY_ID = "VERIFY01"
SYMBOLS    = ["AAPL", "AMAZ", "MSFT", "GOOG"]

# Timeouts
ACK_TIMEOUT_MS   = 2_000   # ms to wait for a single ACK
AUTH_TIMEOUT_MS  = 3_000   # ms to wait for gateway auth
SNAP_TIMEOUT_MS  = 5_000   # ms to wait for a book snapshot after request
DRAIN_PAUSE_S    = 0.5     # seconds to pause after last order before snapshots


# ---------------------------------------------------------------------------
# FIX parser (same as paper trader — kept local to avoid cross-file deps)
# ---------------------------------------------------------------------------

def _parse_fix_line(line: str) -> Order | None:
    """Parse a FIX-like NEW order line into an Order object."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split("|")
    if not parts or parts[0].upper() != "NEW":
        return None

    kv: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.upper()] = v

    try:
        symbol     = kv["SYM"].upper()
        side       = Side(kv["SIDE"].upper())
        order_type = OrderType(kv["TYPE"].upper())
        quantity   = int(kv["QTY"])
        tif_val    = TIF(kv.get("TIF", "DAY").upper())
        price      = float(kv["PRICE"])  if "PRICE"   in kv else None
        stop_price = float(kv["STOP"])   if "STOP"    in kv else None
        visible    = int(kv["VISIBLE"])  if "VISIBLE" in kv else None
        trail      = float(kv["TRAIL"])  if "TRAIL"   in kv else None
    except (KeyError, ValueError) as exc:
        print(f"[REPLAY] Parse error '{line}': {exc}", file=sys.stderr)
        return None

    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        gateway_id=GATEWAY_ID,
        tif=tif_val,
        price=price,
        stop_price=stop_price,
        visible_qty=visible,
        trail_offset=trail,
        smp_action=SmpAction.NONE,
    )


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------

class ReplayClient:
    """ZMQ-based order replay client."""

    def __init__(self, pull_addr: str, pub_addr: str) -> None:
        self.push_sock = make_pusher(pull_addr)
        self.sub_sock = make_subscriber(
            pub_addr,
            f"order.ack.{GATEWAY_ID}",
            f"order.fill.{GATEWAY_ID}",
            f"order.cancelled.{GATEWAY_ID}",
            f"system.gateway_auth.{GATEWAY_ID}",
            "book.AAPL",
            "book.AMAZ",
            "book.MSFT",
            "book.GOOG",
        )
        self._poller = zmq.Poller()
        self._poller.register(self.sub_sock, zmq.POLLIN)

    def _recv(self, timeout_ms: int) -> tuple[str, dict] | None:
        """Poll for one message; return (topic, payload) or None on timeout."""
        ready = dict(self._poller.poll(timeout=timeout_ms))
        if self.sub_sock not in ready:
            return None
        frames = self.sub_sock.recv_multipart()
        topic, payload = decode(frames)
        return topic, payload

    def authenticate(self) -> bool:
        """Send gateway_connect and wait for auth confirmation."""
        time.sleep(0.15)   # allow SUB filters to propagate
        self.push_sock.send_multipart(make_gateway_connect_msg(GATEWAY_ID))
        deadline = time.monotonic() + AUTH_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            msg = self._recv(200)
            if msg is None:
                continue
            topic, payload = msg
            if f"system.gateway_auth.{GATEWAY_ID}" in topic:
                if payload.get("accepted"):
                    print(f"[REPLAY] Gateway {GATEWAY_ID} authenticated.")
                    return True
                else:
                    reason = payload.get("reason", "unknown")
                    print(f"[REPLAY] Auth REJECTED: {reason}", file=sys.stderr)
                    return False
        print(f"[REPLAY] Auth timed out after {AUTH_TIMEOUT_MS} ms", file=sys.stderr)
        return False

    def send_order_and_wait_ack(self, order: Order) -> bool:
        """
        Send one order and block until the engine acknowledges it.

        Returns True if accepted, False if rejected.
        Fills are consumed silently while waiting.
        """
        self.push_sock.send_multipart(make_order_new_msg(order.to_dict()))

        deadline = time.monotonic() + ACK_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            msg = self._recv(200)
            if msg is None:
                continue
            topic, payload = msg
            if f"order.ack.{GATEWAY_ID}" in topic:
                if payload.get("order_id") == order.id:
                    return bool(payload.get("accepted", False))
                # ACK for a different order (e.g. triggered stop) — keep waiting
            # Fills / cancels — consume silently
        print(
            f"[REPLAY] WARN: no ACK for {order.id[:8]} within {ACK_TIMEOUT_MS} ms",
            file=sys.stderr,
        )
        return False

    def request_snapshot(self, symbol: str) -> dict | None:
        """
        Send a book snapshot request and wait for the response.

        Returns the snapshot dict or None on timeout.
        """
        self.push_sock.send_multipart(make_book_snapshot_request_msg(symbol))
        deadline = time.monotonic() + SNAP_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            msg = self._recv(300)
            if msg is None:
                continue
            topic, payload = msg
            if topic == f"book.{symbol}":
                return payload
        print(f"[REPLAY] WARN: no snapshot for {symbol}", file=sys.stderr)
        return None

    def close(self) -> None:
        self.push_sock.close()
        self.sub_sock.close()


def _load_fix_file(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _snapshot_for_result(snap: dict) -> dict:
    """Normalise a raw snapshot to the same shape as paper_result.json."""
    return {
        "bids": [{"price": b["price"], "qty": b["qty"]} for b in snap.get("bids", [])],
        "asks": [{"price": a["price"], "qty": a["qty"]} for a in snap.get("asks", [])],
        "last_price":      snap.get("last_price"),
        "last_buy_price":  snap.get("last_buy_price"),
        "last_sell_price": snap.get("last_sell_price"),
    }


def run_replay(pull_addr: str, pub_addr: str) -> None:
    """Main replay flow: connect → send all orders → collect snapshots → save."""

    if not MM_FIX_FILE.exists() or not TEST_FIX_FILE.exists():
        print(
            "[REPLAY] ERROR: FIX files not found.  Run gen_verification_set.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    mm_lines   = _load_fix_file(MM_FIX_FILE)
    test_lines = _load_fix_file(TEST_FIX_FILE)
    all_lines  = mm_lines + test_lines

    client = ReplayClient(pull_addr, pub_addr)

    if not client.authenticate():
        client.close()
        sys.exit(1)

    # ── Send all orders ──────────────────────────────────────────────────────
    total       = 0
    accepted    = 0
    rejected    = 0
    parse_errs  = 0
    t_start     = time.monotonic()

    for raw in all_lines:
        order = _parse_fix_line(raw)
        if order is None:
            parse_errs += 1
            continue
        ok = client.send_order_and_wait_ack(order)
        total += 1
        if ok:
            accepted += 1
        else:
            rejected += 1
        if total % 100 == 0:
            print(f"[REPLAY] … {total} orders sent ({accepted} acc, {rejected} rej)")

    elapsed = time.monotonic() - t_start
    print(
        f"[REPLAY] Sent {total} orders in {elapsed:.2f}s  "
        f"({accepted} accepted, {rejected} rejected, {parse_errs} parse errors)"
    )

    # Let the engine process any lingering async work (e.g. throttled snapshots)
    print(f"[REPLAY] Pausing {DRAIN_PAUSE_S}s for engine to drain …")
    time.sleep(DRAIN_PAUSE_S)

    # ── Collect book snapshots ───────────────────────────────────────────────
    print("[REPLAY] Requesting book snapshots …")
    result: dict[str, dict] = {}
    for sym in SYMBOLS:
        snap = client.request_snapshot(sym)
        if snap:
            result[sym] = _snapshot_for_result(snap)
            r = result[sym]
            print(
                f"  {sym:6s}  bids={len(r['bids'])} levels  "
                f"asks={len(r['asks'])} levels  "
                f"last={r['last_price']}"
            )
        else:
            print(f"  {sym:6s}  — no snapshot received", file=sys.stderr)

    client.close()

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    ENGINE_RESULT.write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"[REPLAY] Saved engine result → {ENGINE_RESULT}")
    print("[REPLAY] Done — run compare_results.py to verify.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument(
        "--pull", default=ENGINE_PULL_ADDR,
        metavar="ADDR", help=f"Engine PULL address (default: {ENGINE_PULL_ADDR})"
    )
    ap.add_argument(
        "--pub", default=ENGINE_PUB_ADDR,
        metavar="ADDR", help=f"Engine PUB address (default: {ENGINE_PUB_ADDR})"
    )
    args = ap.parse_args()
    run_replay(args.pull, args.pub)


if __name__ == "__main__":
    main()
