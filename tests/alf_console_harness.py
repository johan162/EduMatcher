"""Real-socket harness for pm-alf-console tests.

A ``Gateway`` whose sockets connect to real ZeroMQ sockets bound here: the
engine's PUB (through ``make_publisher``, so every message carries the real
``seq|eseq|envelope`` trailer), the engine's PULL, the drop-copy PUB and the
index PUB/PULL. The listener runs in its own thread, as in ``run()``. Feed it
with the engine's own builders, not hand-made frames.

``sync()`` publishes a marker trade behind everything sent so far and waits
until the listener has handled it: one PUB socket delivers in order, so every
earlier message on it has been handled too.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from edumatcher.messaging.bus import make_publisher, make_puller
from edumatcher.models.message import decode, make_trade_msg
from tests.conftest import free_ports

_SYNC_SYMBOL = "ZZSYNC"


def trade_frames(seq: int, symbol: str = "AAPL", price: float = 100.0) -> list[bytes]:
    """One ``trade.executed`` between two other participants."""
    return make_trade_msg(
        {
            "id": f"000001-{seq:09d}",
            "run_seq": 1,
            "symbol": symbol,
            "buy_order_id": "b",
            "sell_order_id": "s",
            "buy_gateway_id": "OTHER1",
            "sell_gateway_id": "OTHER2",
            "price": price,
            "quantity": 10,
            "aggressor_side": "BUY",
            "ts_ns": time.time_ns(),
            "tick_decimals": 2,
            "price_ticks": round(price * 100),
            "match_type": "CONTINUOUS",
        }
    )


class ConsoleHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, gateway_id: str) -> None:
        from edumatcher.alf_console import main as console_main
        from edumatcher.alf_console.display import console

        pub_port, pull_port, dc_port, index_pub_port, index_pull_port = free_ports(5)
        self.pub_addr = f"tcp://127.0.0.1:{pub_port}"
        self.pull_addr = f"tcp://127.0.0.1:{pull_port}"
        self.dc_addr = f"tcp://127.0.0.1:{dc_port}"
        for name, addr in (
            ("ENGINE_PUB_ADDR", self.pub_addr),
            ("ENGINE_PULL_ADDR", self.pull_addr),
            ("DROP_COPY_PUB_ADDR", self.dc_addr),
            ("INDEX_PUB_CONNECT_ADDR", f"tcp://127.0.0.1:{index_pub_port}"),
            ("INDEX_PULL_CONNECT_ADDR", f"tcp://127.0.0.1:{index_pull_port}"),
        ):
            monkeypatch.setattr(console_main, name, addr)

        self.pub = make_publisher(self.pub_addr)
        self.dc_pub = make_publisher(self.dc_addr)
        self.pull = make_puller(self.pull_addr)

        self.lines: list[str] = []
        self._lines_lock = threading.Lock()

        def _record(*objects: Any, **_kw: Any) -> None:
            with self._lines_lock:
                self.lines.append(" ".join(str(o) for o in objects))

        monkeypatch.setattr(console, "print", _record)

        self.gw = console_main.Gateway(gateway_id)
        self._listener = threading.Thread(target=self.gw._listen, daemon=True)
        self._listener.start()
        self._sync_seq = 0
        self.sync()

    def sync(self, timeout: float = 5.0) -> None:
        """Wait until everything published so far has been handled."""
        self._sync_seq += 1
        price = float(self._sync_seq)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pub.send_multipart(trade_frames(self._sync_seq, _SYNC_SYMBOL, price))
            end = time.monotonic() + 0.1
            while time.monotonic() < end:
                if self.gw._last_prices.get(_SYNC_SYMBOL) == price:
                    self.gw._last_prices.pop(_SYNC_SYMBOL, None)
                    return
                time.sleep(0.002)
        raise AssertionError("console listener did not catch up")

    def pushed(self, timeout: float = 0.5) -> list[tuple[str, dict[str, Any]]]:
        """Every request the console pushed to the engine since the last call."""
        out: list[tuple[str, dict[str, Any]]] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.pull.poll(20):
                out.append(decode(self.pull.recv_multipart()))
        return out

    def close(self) -> None:
        self.gw._running = False
        self._listener.join(timeout=5)
        for sock in (
            self.gw.push_sock,
            self.gw._index_push_sock,
            self.gw.sub_sock,
            self.gw._index_sub_sock,
            self.gw._dc_sub_sock,
        ):
            sock.close(linger=0)
        self.pub.close(linger=0)
        self.dc_pub.close(linger=0)
        self.pull.close(linger=0)


@pytest.fixture
def console_harness(monkeypatch: pytest.MonkeyPatch):
    """Factory: ``console_harness("TRADER1")`` returns a started harness."""
    made: list[ConsoleHarness] = []

    def _make(gateway_id: str) -> ConsoleHarness:
        harness = ConsoleHarness(monkeypatch, gateway_id)
        made.append(harness)
        return harness

    yield _make
    for harness in made:
        harness.close()


__all__ = ["ConsoleHarness", "console_harness", "trade_frames"]
