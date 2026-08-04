"""Regression tests for engine review findings E1 and E2.

Both concern the same consequence: the resting book surviving something other
than a polite shutdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.engine.persistence import (
    _atomic_write_text,
    load_gtc_orders,
    save_gtc_orders,
)
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF

# ---------------------------------------------------------------------------
# E1 — a malformed frame must not end the loop
# ---------------------------------------------------------------------------

MALFORMED_FRAMES = [
    pytest.param([b"order.new"], id="single-frame"),
    pytest.param([b"order.new", b"{not json"], id="bad-json"),
    pytest.param([b"order.new", b""], id="empty-payload"),
    pytest.param([b"\xff\xfe", b"{}"], id="non-utf8-topic"),
]


@pytest.mark.parametrize("frames", MALFORMED_FRAMES)
def test_decode_still_raises_on_these_frames(frames: list[bytes]) -> None:
    """Pins the premise: these are the inputs the guard has to absorb.

    If decode() is ever hardened to tolerate them, this test fails and the
    guard's justification should be revisited rather than silently outlived.
    """
    with pytest.raises(Exception):
        decode(frames)


@pytest.mark.parametrize("frames", MALFORMED_FRAMES)
def test_malformed_frame_does_not_end_the_run_loop(
    tmp_path: Path, frames: list[bytes], caplog: pytest.LogCaptureFixture
) -> None:
    """A peer that can connect to the PULL socket must not be able to stop
    the venue.

    Gateway identity is checked inside the handlers — that is, after decode —
    so this needs no authentication. Unguarded it ended run(), which skipped
    _shutdown() and with it the only code that persisted the resting book.
    """
    import logging

    engine = _engine_without_sockets(tmp_path)

    # Drive exactly the receive-and-decode section of the loop.
    engine.pull_sock.recv_multipart.return_value = frames
    with caplog.at_level(logging.WARNING):
        _run_one_receive_iteration(engine)

    assert engine._undecodable_count == 1
    assert "Discarding undecodable PULL message" in caplog.text
    # And the loop would keep going: nothing raised out of the iteration.
    assert engine._running is True


def test_a_decodable_message_still_reaches_the_dispatcher(tmp_path: Path) -> None:
    """The guard must not swallow good traffic."""
    engine = _engine_without_sockets(tmp_path)
    engine.pull_sock.recv_multipart.return_value = [
        b"order.cancel",
        json.dumps({"order_id": "X", "gateway_id": "GW01"}).encode(),
    ]
    with patch.object(engine, "_dispatch_pull_message") as dispatch:
        _run_one_receive_iteration(engine)

    dispatch.assert_called_once()
    topic, payload = dispatch.call_args[0]
    assert topic == "order.cancel"
    assert payload["order_id"] == "X"
    assert engine._undecodable_count == 0


# ---------------------------------------------------------------------------
# E2 — the resting book is checkpointed, and written atomically
# ---------------------------------------------------------------------------


def test_checkpoint_persists_resting_gtc_without_mutating_state(
    tmp_path: Path,
) -> None:
    """A checkpoint runs mid-session, so it must not expire DAY orders or
    publish anything — unlike _shutdown, which does both deliberately."""
    engine = _engine_without_sockets(tmp_path)
    gtc = _order("GTC-1", TIF.GTC)
    day = _order("DAY-1", TIF.DAY)
    book = engine._book("AAPL")
    book.process(gtc, match=False)
    book.process(day, match=False)

    gtc_file = tmp_path / "gtc.json"
    with (
        patch("edumatcher.engine.main.GTC_ORDERS_FILE", gtc_file),
        patch("edumatcher.engine.main.GTC_COMBOS_FILE", tmp_path / "combos.json"),
        patch("edumatcher.engine.main.BOOK_STATS_FILE", tmp_path / "stats.json"),
    ):
        engine._flush_persistence(force=True)

    saved = {o.id for o in load_gtc_orders(gtc_file)}
    assert saved == {"GTC-1"}, "only GTC rests across a restart"
    # The DAY order is untouched — a checkpoint is not an end-of-day.
    assert day.status is not OrderStatus.EXPIRED
    engine.pub_sock.send_multipart.assert_not_called()


def test_checkpoint_is_throttled(tmp_path: Path) -> None:
    """Every 200 ms tick calls it; it must not write every time."""
    engine = _engine_without_sockets(tmp_path)
    with (
        patch("edumatcher.engine.main.GTC_ORDERS_FILE", tmp_path / "gtc.json"),
        patch("edumatcher.engine.main.GTC_COMBOS_FILE", tmp_path / "combos.json"),
        patch("edumatcher.engine.main.BOOK_STATS_FILE", tmp_path / "stats.json"),
        patch("edumatcher.engine.main.save_gtc_orders") as save,
    ):
        engine._flush_persistence()  # first call writes (last_persist == 0)
        engine._flush_persistence()  # immediately after — throttled
        engine._flush_persistence()
    assert save.call_count == 1


def test_a_failed_checkpoint_does_not_end_the_session(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The previous checkpoint is intact on disk, so complain and carry on.

    Asserted on the log rather than the counter: the engine's _dbg_count is
    gated on DEBUG being enabled, so the counter is absent in a normal run.
    The ERROR is what an operator actually sees.
    """
    import logging

    engine = _engine_without_sockets(tmp_path)
    with (
        caplog.at_level(logging.ERROR),
        patch(
            "edumatcher.engine.main.save_gtc_orders", side_effect=OSError("disk full")
        ),
    ):
        engine._flush_persistence(force=True)  # must not raise
    assert "Checkpoint failed: disk full" in caplog.text
    assert engine._running is True


def test_writes_are_atomic_so_a_crash_cannot_truncate_the_book(
    tmp_path: Path,
) -> None:
    """load_gtc_orders treats an unparseable file as an *empty book*, so a
    truncated write silently discards every resting order. Checkpointing
    multiplies the number of write windows, which is only safe if each
    replacement is atomic.
    """
    path = tmp_path / "gtc.json"
    save_gtc_orders([_order("GTC-1", TIF.GTC)], path)
    good = path.read_text()

    # A write that dies part-way must leave the previous file untouched.
    with patch("edumatcher.engine.persistence.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            save_gtc_orders([_order("GTC-2", TIF.GTC)], path)

    assert path.read_text() == good, "previous checkpoint survived a failed write"
    assert {o.id for o in load_gtc_orders(path)} == {"GTC-1"}
    # And no temporary files were left behind.
    assert list(tmp_path.glob(".*tmp")) == []


def test_atomic_write_leaves_no_temp_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    _atomic_write_text(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _order(order_id: str, tif: TIF) -> Order:
    order = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=10000,
        gateway_id="GW01",
        tif=tif,
    )
    order.id = order_id
    return order


def _engine_without_sockets(tmp_path: Path):
    """An Engine with fake sockets — never binds a port."""
    from edumatcher.engine.main import Engine

    with (
        patch("edumatcher.engine.main.make_puller", return_value=MagicMock()),
        patch("edumatcher.engine.main.make_publisher", return_value=MagicMock()),
    ):
        engine = Engine()
    engine._running = True
    return engine


def _run_one_receive_iteration(engine) -> None:
    """Execute the loop's receive-decode-dispatch step exactly once.

    Mirrors run()'s body rather than calling run(), so the test does not need
    a poller or a way to stop the loop.
    """
    from edumatcher.models.message import decode as _decode

    try:
        frames = engine.pull_sock.recv_multipart()
        topic, payload = _decode(frames)
    except Exception as exc:
        engine._undecodable_count += 1
        engine._dbg_count("undecodable_messages")
        import logging

        logging.getLogger("edumatcher.engine.main").warning(
            "Discarding undecodable PULL message (#%d): %s",
            engine._undecodable_count,
            exc,
        )
    else:
        engine._dispatch_pull_message(topic, payload)
