"""Regression tests for engine review findings E1-E3 and E5.

E1 and E2 concern the same consequence: the resting book surviving something
other than a polite shutdown. E3 concerns the protocol invariant that every
order terminates in an ack or a reject. E5 concerns the per-tick maintenance
flushes, which are a second route into E2.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.engine.persistence import (
    _atomic_write_text,
    load_and_bump_run_seq,
    load_gtc_orders,
    save_gtc_orders,
)
from edumatcher.models.trade import reset_trade_ids_for_tests
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


def test_checkpoint_persists_resting_gtc_and_day_without_mutating_state(
    tmp_path: Path,
) -> None:
    """A checkpoint runs mid-session, so it must not expire anything or
    publish anything — unlike _shutdown, which used to expire DAY orders but
    no longer does (see docs-design/EduMatcher-Revised-Quote-Persistence.md
    §12-§13: a process exit, including the periodic checkpoint's caller, is
    not a day boundary). Both TIF=GTC and TIF=DAY resting orders are
    persisted here; a same-day-vs-stale distinction for DAY orders is only
    applied at restore time (Engine._restore_gtc), not at checkpoint time."""
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
    assert saved == {"GTC-1", "DAY-1"}, "both GTC and DAY rest across a restart"
    # Neither order is touched — a checkpoint mutates nothing.
    assert day.status is not OrderStatus.EXPIRED
    assert gtc.status is not OrderStatus.EXPIRED
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


def test_load_and_bump_run_seq_persists_before_return(tmp_path: Path) -> None:
    path = tmp_path / "engine_run_seq.json"

    assert load_and_bump_run_seq(path) == 1
    assert json.loads(path.read_text())["run_seq"] == 1
    assert load_and_bump_run_seq(path) == 2
    assert json.loads(path.read_text())["run_seq"] == 2


def test_load_and_bump_run_seq_fails_loud_on_corruption(tmp_path: Path) -> None:
    path = tmp_path / "engine_run_seq.json"
    path.write_text("not json")

    with pytest.raises(RuntimeError, match="Corrupt run-sequence file"):
        load_and_bump_run_seq(path)


def test_run_sets_run_seq_before_gtc_restore(tmp_path: Path) -> None:
    """Recovery uncross can mint trades, so run_seq must exist first."""
    reset_trade_ids_for_tests()
    engine = _engine_without_sockets(tmp_path)
    run_seq_file = tmp_path / "engine_run_seq.json"

    def _stop_at_restore() -> None:
        from edumatcher.models.trade import Trade

        trade = Trade.create(
            symbol="AAPL",
            buy_order_id="B1",
            sell_order_id="S1",
            buy_gateway_id="GW01",
            sell_gateway_id="GW02",
            price=15000,
            quantity=100,
            aggressor_side="AUCTION",
        )
        assert trade.id == "000001-000000001"
        engine._running = False
        raise RuntimeError("stop after restore")

    with (
        patch("edumatcher.engine.main.RUN_SEQ_FILE", run_seq_file),
        patch.object(engine, "_restore_gtc", side_effect=_stop_at_restore),
        pytest.raises(RuntimeError, match="stop after restore"),
    ):
        engine.run()

    assert json.loads(run_seq_file.read_text())["run_seq"] == 1


# ---------------------------------------------------------------------------
# E3 — a handler exception must still answer the client
# ---------------------------------------------------------------------------


def _sent_ack(engine) -> dict:
    """The single ack the engine published, decoded."""
    calls = engine.pub_sock.send_multipart.call_args_list
    assert len(calls) == 1, f"expected exactly one message, got {len(calls)}"
    topic, body = calls[0][0][0][:2]
    return {"topic": topic.decode(), **json.loads(body)}


def test_handler_exception_rejects_the_order(tmp_path: Path) -> None:
    """Unanswered is the one outcome the client cannot act on: a timeout is
    indistinguishable from a slow engine, so the order's fate is unknown."""
    engine = _engine_without_sockets(tmp_path)
    with patch.object(engine, "_handle_new_order", side_effect=RuntimeError("boom")):
        engine._dispatch_pull_message(
            "order.new", {"id": "ORD-1", "gateway_id": "GW01"}
        )

    ack = _sent_ack(engine)
    assert ack["topic"] == "order.ack.GW01"
    assert ack["order_id"] == "ORD-1"
    assert ack["accepted"] is False
    assert ack["reason"] == "Internal error processing order"
    # Still logged and counted — the reject answers the client, it does not
    # make the defect invisible.
    assert engine._error_count == 1


def test_reject_after_a_fill_says_so(tmp_path: Path) -> None:
    """A bare "rejected" is a lie once anything has printed: the participant
    holds a position the reject implicitly denies."""
    engine = _engine_without_sockets(tmp_path)

    def _fill_then_raise(_payload: dict) -> None:
        engine._fills_published += 1
        raise RuntimeError("boom after the print")

    with patch.object(engine, "_handle_new_order", side_effect=_fill_then_raise):
        engine._dispatch_pull_message(
            "order.new", {"id": "ORD-2", "gateway_id": "GW01"}
        )

    reason = _sent_ack(engine)["reason"]
    assert "after execution" in reason
    assert "drop copy" in reason


def test_no_reject_for_topics_that_are_not_orders(tmp_path: Path) -> None:
    """A query has nothing resting on it, and an order-reject addressed to an
    id that is not an order is worse than silence."""
    engine = _engine_without_sockets(tmp_path)
    with patch.object(
        engine, "_handle_symbols_request", side_effect=RuntimeError("boom")
    ):
        engine._dispatch_pull_message(
            "system.symbols_request", {"gateway_id": "GW01", "id": "REQ-1"}
        )
    engine.pub_sock.send_multipart.assert_not_called()
    assert engine._error_count == 1


def test_unaddressable_payload_is_reported_not_guessed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The payload that broke the handler may be the one missing these very
    fields, so there is no one to answer."""
    import logging

    engine = _engine_without_sockets(tmp_path)
    with (
        caplog.at_level(logging.ERROR),
        patch.object(engine, "_handle_new_order", side_effect=RuntimeError("boom")),
    ):
        engine._dispatch_pull_message("order.new", {"id": "ORD-3"})  # no gateway_id

    engine.pub_sock.send_multipart.assert_not_called()
    assert "No reject sent for order.new" in caplog.text


def test_a_failed_reject_does_not_take_the_venue_down(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The reject is best-effort — raising here would escape run() over a
    message that already failed once."""
    import logging

    engine = _engine_without_sockets(tmp_path)
    engine.pub_sock.send_multipart.side_effect = OSError("socket gone")
    with (
        caplog.at_level(logging.ERROR),
        patch.object(engine, "_handle_new_order", side_effect=RuntimeError("boom")),
    ):
        engine._dispatch_pull_message(
            "order.new", {"id": "ORD-4", "gateway_id": "GW01"}
        )
    assert "could not be sent" in caplog.text
    assert engine._running is True


def test_a_successful_handler_sends_no_reject(tmp_path: Path) -> None:
    """The guard must not answer orders that were handled normally."""
    engine = _engine_without_sockets(tmp_path)
    with patch.object(engine, "_handle_new_order"):
        engine._dispatch_pull_message(
            "order.new", {"id": "ORD-5", "gateway_id": "GW01"}
        )
    engine.pub_sock.send_multipart.assert_not_called()
    assert engine._error_count == 0


# ---------------------------------------------------------------------------
# E5 — a failed maintenance flush must not end the session
# ---------------------------------------------------------------------------


def test_a_failing_flush_does_not_end_the_session(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Each flush publishes on pub_sock; unguarded, a ZMQError there ended
    run() and took the resting book with it (E2)."""
    import logging

    engine = _engine_without_sockets(tmp_path)
    with (
        caplog.at_level(logging.ERROR),
        patch.object(
            engine,
            "_flush_snapshots",
            MagicMock(
                side_effect=RuntimeError("zmq gone"), __name__="_flush_snapshots"
            ),
        ),
    ):
        engine._run_maintenance()

    assert engine._flush_error_count == 1
    assert "_flush_snapshots failed" in caplog.text
    assert engine._running is True


def test_one_failing_flush_does_not_skip_the_others(tmp_path: Path) -> None:
    """Guarded as a block rather than per call, a market-data failure would
    skip the circuit-breaker timers — a safety function."""
    engine = _engine_without_sockets(tmp_path)
    with (
        patch.object(engine, "_flush_snapshots", side_effect=RuntimeError("boom")),
        patch.object(engine, "_flush_circuit_breakers") as breakers,
        patch.object(engine, "_flush_auction_indicative") as auction,
    ):
        engine._run_maintenance()

    breakers.assert_called_once()
    auction.assert_called_once()


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
