from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from edumatcher.board.main import MarketBoard, _build_rows_table


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.closed = False

    def send_multipart(self, msg: Any) -> None:
        self.sent.append(msg)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _new_board() -> MarketBoard:
    # MarketBoard.__init__ opens real ZeroMQ sockets (make_subscriber /
    # make_pusher) — patch those out so constructing one in a test doesn't
    # touch the network.
    with (
        patch("edumatcher.board.main.make_subscriber", return_value=_FakeSub()),
        patch("edumatcher.board.main.make_pusher", return_value=_FakePush()),
    ):
        return MarketBoard(rows_per_page=8, interval=10)


def test_board_main_aggregates_book_and_trade_before_render() -> None:
    """Intent: board should combine book and trade streams into one symbol
    view (best bid/ask + last price + cumulative volume) before rendering.

    MarketBoard._handle is what actually does that aggregation (called from
    the background _receive thread in real operation); _render/
    _build_rows_table is what turns the aggregated state into a Table. This
    drives both directly rather than the old approach of mocking zmq.Poller
    and stepping main()'s loop — _handle now runs on its own thread,
    decoupled from the render loop, so there's no single-threaded call
    sequence left to intercept the way the old test did.
    """
    board = _new_board()

    board._handle(
        "book.AAPL",
        {
            "last_price": 100.5,
            "last_buy_price": 100.4,
            "last_sell_price": 100.6,
            "bids": [{"price": 100.4, "qty": 10}],
            "asks": [{"price": 100.6, "qty": 12}],
        },
    )
    board._handle(
        "trade.executed",
        {
            "symbol": "AAPL",
            "price": 100.7,
            "quantity": 5,
        },
    )

    with board._lock:
        aapl = board._symbols["AAPL"]
        assert aapl["best_bid"] == 100.4
        assert aapl["best_ask"] == 100.6
        assert aapl["last_price"] == 100.7
        assert aapl["volume"] == 5

    # And the aggregated state actually renders — same page_symbols shape
    # _render builds from self._symbols.
    table = _build_rows_table([("AAPL", dict(board._symbols["AAPL"]))])
    assert table.row_count == 1
