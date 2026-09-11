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

from edumatcher.engine.order_book import OrderBook
from edumatcher.engine.persistence import (
    _atomic_write_text,
    load_and_bump_run_seq,
    load_gtc_orders,
    save_gtc_orders,
)
from edumatcher.models.trade import Trade, reset_trade_ids_for_tests
from edumatcher.models.message import decode
from edumatcher.models.order import (
    Order,
    OrderOrigin,
    OrderStatus,
    OrderType,
    Side,
    TIF,
)

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


# ---------------------------------------------------------------------------
# AR-0.5 — per-entity recovery events (system.recovery_item)
#
# docs-design/EduMatcher-Audit-Replay.md §14 AR-0.5's verify step: seed a
# persistence file with one deliberately corrupt order, restart, assert
# exactly one recovery_item with outcome FAILED naming that order id, and
# that the failed_orders count is 1. "Corrupt" here is a structurally valid,
# successfully-deserialized Order (load_gtc_orders() already discards a
# malformed JSON record on its own, before _restore_gtc() ever sees it —
# see persistence.py) that nonetheless raises when OrderBook.process()
# tries to rest it, exactly the case _restore_gtc()'s own try/except guards
# against (finding C6).
# ---------------------------------------------------------------------------


def test_a_corrupt_order_gets_exactly_one_failed_recovery_item(
    tmp_path: Path,
) -> None:
    engine = _engine_without_sockets(tmp_path)
    good = _order("GOOD-1", TIF.GTC)
    bad = _order("BAD-1", TIF.GTC)

    gtc_file = tmp_path / "gtc.json"
    save_gtc_orders([good, bad], gtc_file)

    # Force BAD-1 specifically to raise inside book.process(), the same
    # shape of failure the guard in _restore_gtc() exists for — a bad
    # persisted record that must not abort the rest of startup. OrderBook
    # is a slotted instance, so the bound method can't be patched per
    # instance; patch the class and delegate to the real unbound method.
    real_process = OrderBook.process

    def _process_unless_bad(
        self: OrderBook,
        order: Order,
        *,
        match: bool = True,
        now: int | None = None,
        _cascade_stops: bool = True,
    ) -> tuple[list[Trade], list[Order]]:
        if order.id == "BAD-1":
            raise ValueError("simulated corrupt order")
        return real_process(
            self, order, match=match, now=now, _cascade_stops=_cascade_stops
        )

    with (
        patch("edumatcher.engine.main.GTC_ORDERS_FILE", gtc_file),
        patch("edumatcher.engine.main.GTC_COMBOS_FILE", tmp_path / "combos.json"),
        patch.object(OrderBook, "process", _process_unless_bad),
    ):
        engine._restore_gtc()

    sent = _sent_messages(engine)
    items = [m for m in sent if m["topic"] == "system.recovery_item"]
    failed = [m for m in items if m["outcome"] == "FAILED"]
    restored = [m for m in items if m["outcome"] == "RESTORED"]

    assert len(failed) == 1, f"expected exactly one FAILED recovery_item, got {failed}"
    assert failed[0]["entity_id"] == "BAD-1"
    assert failed[0]["kind"] == "ORDER"
    assert failed[0]["symbol"] == "AAPL"
    assert "simulated corrupt order" in failed[0]["detail"]

    assert any(
        r["entity_id"] == "GOOD-1" for r in restored
    ), "the surviving order should still get its own RESTORED recovery_item"

    summaries = [m for m in sent if m["topic"] == "system.startup_recovery"]
    assert len(summaries) == 1
    assert summaries[0]["failed_orders"] == 1
    assert summaries[0]["restored_orders"] == 1


def test_shutdown_persists_quote_legs_gtc_and_day_alike(tmp_path: Path) -> None:
    """Quote-origin orders (origin=QUOTE) are no longer excluded from
    persistence — see docs-design/EduMatcher-Revised-Quote-Persistence.md
    §5.2. A quote leg now persists by the same TIF rule as any other order:
    TIF=GTC and TIF=DAY both survive, since §12-§13 already made TIF=DAY
    resting orders survive a same-day restart too. This is a strictly
    better outcome than the original §5.2 scope (which only covered
    TIF=GTC) — see §13.7."""
    engine = _engine_without_sockets(tmp_path)
    gtc_quote_leg = _quote_leg("GTC-BID", TIF.GTC, Side.BUY)
    day_quote_leg = _quote_leg("DAY-ASK", TIF.DAY, Side.SELL)
    book = engine._book("AAPL")
    book.process(gtc_quote_leg, match=False)
    book.process(day_quote_leg, match=False)

    gtc_file = tmp_path / "gtc.json"
    with (
        patch("edumatcher.engine.main.GTC_ORDERS_FILE", gtc_file),
        patch("edumatcher.engine.main.GTC_COMBOS_FILE", tmp_path / "combos.json"),
        patch("edumatcher.engine.main.BOOK_STATS_FILE", tmp_path / "stats.json"),
    ):
        engine._shutdown()

    saved = {o.id: o for o in load_gtc_orders(gtc_file)}
    assert saved.keys() == {"GTC-BID", "DAY-ASK"}
    assert all(o.origin == OrderOrigin.QUOTE for o in saved.values())
    assert saved["GTC-BID"].quote_id == "Q1"
    assert saved["DAY-ASK"].quote_id == "Q1"


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


def _sent_messages(engine) -> list[dict]:
    """Every message the engine published, decoded, in publish order."""
    calls = engine.pub_sock.send_multipart.call_args_list
    out = []
    for call in calls:
        topic, body = call[0][0][:2]
        out.append({"topic": topic.decode(), **json.loads(body)})
    return out


def _sent_ack(engine) -> dict:
    """The one order.ack the engine published, decoded.

    A handler exception now also publishes a system.diagnostic (see
    docs/user-guide/190-audit.md) alongside the reject, so this filters for
    the ack specifically rather than assuming it is the only message.
    """
    acks = [m for m in _sent_messages(engine) if m["topic"].startswith("order.ack.")]
    assert len(acks) == 1, f"expected exactly one order.ack, got {len(acks)}"
    return acks[0]


def _sent_diagnostic(engine) -> dict:
    """The one system.diagnostic the engine published, decoded."""
    diags = [m for m in _sent_messages(engine) if m["topic"] == "system.diagnostic"]
    assert len(diags) == 1, f"expected exactly one diagnostic, got {len(diags)}"
    return diags[0]


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

    # The client-facing reject stays generic (see _reject_after_error's
    # docstring), but the real exception now reaches a post-mortem via
    # system.diagnostic — this used to be a log line only.
    diag = _sent_diagnostic(engine)
    assert diag["component"] == "DISPATCH_ERROR"
    assert diag["detail"] == "order.new"
    assert diag["error"] == "boom"
    assert diag["count"] == 1


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
    id that is not an order is worse than silence -- but the failure itself
    is still worth a system.diagnostic, since non-order handlers can crash
    too and a post-mortem needs to see that regardless of topic family."""
    engine = _engine_without_sockets(tmp_path)
    with patch.object(
        engine, "_handle_symbols_request", side_effect=RuntimeError("boom")
    ):
        engine._dispatch_pull_message(
            "system.symbols_request", {"gateway_id": "GW01", "id": "REQ-1"}
        )
    messages = _sent_messages(engine)
    assert not any(m["topic"].startswith("order.ack.") for m in messages)
    diag = _sent_diagnostic(engine)
    assert diag["component"] == "DISPATCH_ERROR"
    assert diag["detail"] == "system.symbols_request"
    assert engine._error_count == 1


def test_unaddressable_payload_is_reported_not_guessed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The payload that broke the handler may be the one missing these very
    fields, so there is no one to answer -- the diagnostic still fires."""
    import logging

    engine = _engine_without_sockets(tmp_path)
    with (
        caplog.at_level(logging.ERROR),
        patch.object(engine, "_handle_new_order", side_effect=RuntimeError("boom")),
    ):
        engine._dispatch_pull_message("order.new", {"id": "ORD-3"})  # no gateway_id

    messages = _sent_messages(engine)
    assert not any(m["topic"].startswith("order.ack.") for m in messages)
    assert _sent_diagnostic(engine)["detail"] == "order.new"
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


def _quote_leg(order_id: str, tif: TIF, side: Side, quote_id: str = "Q1") -> Order:
    """A resting order shaped like one leg of a market-maker quote —
    origin=QUOTE with a quote_id, as Engine._load_config()/_handle_quote_new
    produce. See docs-design/EduMatcher-Revised-Quote-Persistence.md §5.2."""
    order = Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=10000 if side == Side.BUY else 10010,
        gateway_id="GW01",
        tif=tif,
    )
    order.id = order_id
    order.origin = OrderOrigin.QUOTE
    order.quote_id = quote_id
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
    a poller or a way to stop the loop. Kept in sync with that block
    (including its guarded system.diagnostic publish, see
    docs/user-guide/190-audit.md) rather than a pre-diagnostic snapshot of
    it, so this helper cannot mask a regression there.
    """
    from edumatcher.models.message import decode as _decode, make_diagnostic_msg

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
        try:
            engine.pub_sock.send_multipart(
                make_diagnostic_msg(
                    component="UNDECODABLE_MESSAGE",
                    error=str(exc),
                    count=engine._undecodable_count,
                )
            )
        except Exception:
            logging.getLogger("edumatcher.engine.main").error(
                "Diagnostic publish for undecodable message failed"
            )
    else:
        engine._dbg_count("pull_messages")
        engine._dbg_count(f"topic_{topic}")
        engine._dispatch_pull_message(topic, payload)
