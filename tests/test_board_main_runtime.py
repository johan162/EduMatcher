from __future__ import annotations

import logging
from typing import Any, Literal
from unittest.mock import patch
import sys

import pytest
import zmq

from edumatcher.board import main as board_main


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False

    def recv_multipart(self) -> list[bytes]:
        return [b"topic", b"payload"]

    def close(self) -> None:
        self.closed = True


class _PollerTwoEventsThenInterrupt:
    def __init__(self, sub: Any) -> None:
        self._sub = sub
        self._i = 0

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        self._i += 1
        if self._i in (1, 2):
            return [(self._sub, zmq.POLLIN)]
        raise KeyboardInterrupt()


class _FakeLive:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    def __enter__(self) -> "_FakeLive":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        _ = (exc_type, exc, tb)
        return False

    def update(self, _table: Any) -> None:
        return None

    def refresh(self) -> None:
        return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_board_main_aggregates_book_and_trade_before_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intent: board should combine book and trade streams into one symbol view
    (best bid/ask + last price + cumulative volume) before rendering.
    """
    fake_sub = _FakeSub()
    snapshots: list[dict[str, dict[str, Any]]] = []

    def _capture_build_table(
        symbols: dict[str, dict[str, Any]],
        page: int,
        rows_per_page: int,
        interval: int,
    ) -> object:
        _ = (page, rows_per_page, interval)
        snapshots.append({k: dict(v) for k, v in symbols.items()})
        return object()

    decode_values = [
        (
            "book.AAPL",
            {
                "last_price": 100.5,
                "last_buy_price": 100.4,
                "last_sell_price": 100.6,
                "bids": [{"price": 100.4, "qty": 10}],
                "asks": [{"price": 100.6, "qty": 12}],
            },
        ),
        (
            "trade.executed",
            {
                "symbol": "AAPL",
                "price": 100.7,
                "quantity": 5,
            },
        ),
    ]

    monkeypatch.setattr(sys, "argv", ["pm-board", "--rows", "2", "--interval", "1"])

    with (
        patch("edumatcher.board.main._configure_logging", return_value=logging.WARNING),
        patch("edumatcher.board.main.make_subscriber", return_value=fake_sub),
        patch(
            "edumatcher.board.main.zmq.Poller",
            return_value=_PollerTwoEventsThenInterrupt(fake_sub),
        ),
        patch("edumatcher.board.main.decode", side_effect=decode_values),
        patch("edumatcher.board.main.Live", _FakeLive),
        patch("edumatcher.board.main._build_table", side_effect=_capture_build_table),
        patch.object(sys.stdin, "isatty", return_value=False),
    ):
        board_main.main()

    assert fake_sub.closed is True
    assert snapshots, "board should render at least once"

    latest = snapshots[-1]
    assert "AAPL" in latest
    aapl = latest["AAPL"]
    assert aapl["best_bid"] == 100.4
    assert aapl["best_ask"] == 100.6
    assert aapl["last_price"] == 100.7
    assert aapl["volume"] == 5
