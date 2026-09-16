"""The §12 findings that need more than one message (task AR-5.1).

Every code gets two tests in effect: the one below that fires it, and
:class:`TestAHealthyLogIsSilent`, which runs the same detector over the
fixtures that are meant to be clean and asserts nothing at all comes out. The
second is the one that matters. A detector with a false positive is worse than
no detector: a report that cries wolf on a healthy log is a report nobody reads
on an unhealthy one, and by then the finding that mattered is on page three.

Each test writes the smallest log that fires its code, so what the code means
is the four or five lines above the assertion rather than a fixture file the
reader has to go and open.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.query import AuditEntry, iter_entries
from edumatcher.audit.replay.anomalies import (
    ACK_DUPLICATE,
    ACK_MISSING,
    ARRIVAL_SEQ_GAP,
    CANCEL_UNMATCHED,
    CANCEL_UNSOLICITED,
    CLIENT_CLOCK_ABSURD,
    ARRIVAL_SEQ_REUSED,
    CLOCK_SKEW,
    COMMAND_UNACKED,
    DROP_COPY_DISAGREE,
    DROP_COPY_MISSING,
    DROP_COPY_SEQ_GAP,
    FILL_BEFORE_ACK,
    FILL_STATUS_DISAGREE,
    FILL_WITHOUT_TRADE,
    HALT_UNRESUMED,
    LEG_PRICE_DISAGREE,
    LEG_QTY_DISAGREE,
    LIQUIDITY_FLAG_DISAGREE,
    PARSE_FAILURE,
    PRICE_OUTSIDE_CORRIDOR,
    PRICE_THROUGH_LIMIT,
    PRINT_PRICE_DISAGREE,
    PRINT_QTY_DISAGREE,
    QTY_MISMATCH,
    SEVERITY_ERROR,
    TERMINAL_MISSING,
    TRADE_COUNTER_GAP,
    TRADE_LEG_MISSING,
    TRADE_LEG_UNKNOWN,
    Anomaly,
)
from edumatcher.audit.replay.detect import Detector, detected, observed
from edumatcher.audit.replay.episodes import assemble
from edumatcher.audit.replay.facts import normalise
from edumatcher.audit.replay.pipeline import reconstruct
from tests.replay_goldens import fixture_log

BASE = datetime(2026, 9, 8, 9, 31, 0, tzinfo=timezone.utc)
ORDER = "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8"
OTHER = "9ab1c47f2e5d48a1b3c6f9078e2d15b4"
TRADE = "000042-000001873"
GATEWAY = "TRADER01"


class Log:
    """A script of audit lines, run through the whole of pass one.

    Lines are stamped a millisecond apart in the order they are added, which
    is what makes the canonical order predictable without every test having to
    spell timestamps out. ``ts_ns`` is left off unless a test is about clocks,
    because a payload clock that disagrees with receipt is itself a finding.
    """

    def __init__(self, **detector_options: Any) -> None:
        self._entries: list[AuditEntry] = []
        self._options = detector_options

    def line(self, topic: str, payload: dict[str, Any] | None = None) -> Log:
        index = len(self._entries)
        when = BASE + timedelta(milliseconds=index)
        meta = {"msg": f"M{index:03d}", "chain": "M000"}
        self._entries.append(
            AuditEntry(
                when.isoformat(timespec="milliseconds"),
                topic,
                payload or {},
                meta,
                file="audit.log",
                line_no=index + 1,
            )
        )
        return self

    def findings(self) -> list[Anomaly]:
        run, steps = reconstruct(self._entries)
        detector = Detector(run.state, **self._options)
        episodes = list(
            detected(
                assemble(observed(steps, detector), run.state, run.links), detector
            )
        )
        return [
            anomaly
            for episode in episodes
            for anomaly in (
                [a for event in episode.events for a in event.step.anomalies]
                + list(episode.anomalies)
            )
        ]

    def codes(self) -> list[str]:
        return [anomaly.code for anomaly in self.findings()]

    def detail(self, code: str) -> str:
        matching = [a.detail for a in self.findings() if a.code == code]
        assert len(matching) == 1, f"expected one {code}, got {matching}"
        return matching[0]


def _submitted(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ORDER,
        "symbol": "AAPL",
        "side": "BUY",
        "order_type": "LIMIT",
        "tif": "DAY",
        "quantity": 200,
        "remaining_qty": 200,
        "gateway_id": GATEWAY,
        "tick_decimals": 2,
        "price_ticks": 7500,
        "status": "NEW",
    }
    payload.update(over)
    return payload


def _ack(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gateway_id": GATEWAY,
        "order_id": ORDER,
        "accepted": True,
        "symbol": "AAPL",
        "qty": 200,
        "price": 75.0,
    }
    payload.update(over)
    return payload


def _fill(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gateway_id": GATEWAY,
        "order_id": ORDER,
        "fill_qty": 200,
        "fill_price": 75.0,
        "remaining_qty": 0,
        "status": "FILLED",
        "symbol": "AAPL",
        "trade_ids": [TRADE],
    }
    payload.update(over)
    return payload


def _trade(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": TRADE,
        "run_seq": 42,
        "symbol": "AAPL",
        "buy_order_id": ORDER,
        "sell_order_id": OTHER,
        "price": 75.0,
        "quantity": 200,
        "tick_decimals": 2,
    }
    payload.update(over)
    return payload


def _copy(**over: Any) -> dict[str, Any]:
    """One ``drop_copy.event``: the clearing feed's account of a fill."""
    payload: dict[str, Any] = {
        "seq": 1,
        "gateway_id": GATEWAY,
        "event_type": "order.fill",
        "order_id": ORDER,
        "trade_ids": [TRADE],
        "symbol": "AAPL",
        "fill_qty": 200,
        "fill_price": 75.0,
        "liquidity_flag": "TAKER",
    }
    payload.update(over)
    return payload


def _nanos(when: datetime) -> int:
    return int(when.timestamp() * 1_000_000_000)


# ---------------------------------------------------------------------------
# 12.1 — lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_an_order_never_acked_is_reported(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line(
            "order.cancelled." + GATEWAY, {"order_id": ORDER, "cancel_reason": "USER"}
        )

        assert ACK_MISSING in log.codes()

    def test_an_acked_order_is_not(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line(
            "order.cancelled." + GATEWAY, {"order_id": ORDER, "cancel_reason": "USER"}
        )

        assert ACK_MISSING not in log.codes()

    def test_a_fill_ahead_of_its_ack_is_an_inversion(self) -> None:
        """Not a reordering artefact: the ordering pass has already run, so
        this is the engine reporting an execution before it admitted the
        order."""
        log = Log().line("order.new", _submitted()).line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill())

        assert FILL_BEFORE_ACK in log.codes()

    def test_a_fill_for_an_order_this_window_never_saw_is_not(self) -> None:
        """The guard that stops every order whose ack fell before ``--from``
        being reported as inverted."""
        log = (
            Log()
            .line("trade.executed", _trade())
            .line("order.fill." + GATEWAY, _fill())
        )

        assert FILL_BEFORE_ACK not in log.codes()

    def test_an_order_still_open_at_the_end_is_reported(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())

        assert TERMINAL_MISSING in log.codes()

    def test_a_cancellation_with_no_request_and_no_reason_is_reported(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line("order.cancelled." + GATEWAY, {"order_id": ORDER, "symbol": "AAPL"})

        assert CANCEL_UNSOLICITED in log.codes()

    def test_a_cancellation_naming_its_cause_is_not(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line(
            "order.cancelled." + GATEWAY,
            {"order_id": ORDER, "symbol": "AAPL", "cancel_reason": "KILL_SWITCH"},
        )

        assert CANCEL_UNSOLICITED not in log.codes()

    def test_a_cancel_request_that_goes_unanswered_is_reported(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line("order.cancel", {"order_id": ORDER, "gateway_id": GATEWAY})

        assert CANCEL_UNMATCHED in log.codes()

    def test_a_cancel_request_that_is_answered_is_not(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line("order.cancel", {"order_id": ORDER, "gateway_id": GATEWAY})
        log.line("order.cancelled." + GATEWAY, {"order_id": ORDER, "symbol": "AAPL"})

        assert CANCEL_UNMATCHED not in log.codes()


# ---------------------------------------------------------------------------
# 12.2 — conservation
# ---------------------------------------------------------------------------


class TestConservation:
    def test_a_trade_with_one_leg_is_a_dropped_message(self) -> None:
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill())

        assert TRADE_LEG_MISSING in log.codes()
        assert "1 fill leg(s), not 2" in log.detail(TRADE_LEG_MISSING)

    def test_a_trade_with_both_legs_is_not(self) -> None:
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill())
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, side="SELL"))

        assert TRADE_LEG_MISSING not in log.codes()

    def test_a_fill_naming_a_trade_the_window_lacks_is_reported(self) -> None:
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line("order.fill." + GATEWAY, _fill())

        assert FILL_WITHOUT_TRADE in log.codes()
        assert TRADE in log.detail(FILL_WITHOUT_TRADE)

    def test_legs_reporting_different_quantities_are_reported(self) -> None:
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill(fill_qty=200))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_qty=150))

        assert LEG_QTY_DISAGREE in log.codes()

    def test_legs_reporting_different_prices_are_reported(self) -> None:
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill(fill_price=75.0))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_price=75.5))

        assert LEG_PRICE_DISAGREE in log.codes()

    def test_a_buy_filled_above_its_limit_is_reported(self) -> None:
        # 7500 ticks at two decimals is a 75.00 limit; 76.00 is through it.
        log = Log().line("order.new", _submitted(price_ticks=7500))
        log.line("order.ack." + GATEWAY, _ack()).line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill(fill_price=76.0))

        assert PRICE_THROUGH_LIMIT in log.codes()
        assert "through its 75 limit" in log.detail(PRICE_THROUGH_LIMIT)

    def test_a_buy_filled_at_its_limit_is_not(self) -> None:
        """Price improvement and an exact fill are both normal; only the
        wrong side of the limit is a finding."""
        log = Log().line("order.new", _submitted(price_ticks=7500))
        log.line("order.ack." + GATEWAY, _ack()).line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill(fill_price=75.0))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_price=75.0))

        assert PRICE_THROUGH_LIMIT not in log.codes()

    def test_a_sell_filled_below_its_limit_is_reported(self) -> None:
        log = Log().line("order.new", _submitted(side="SELL", price_ticks=7500))
        log.line("order.ack." + GATEWAY, _ack()).line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill(side="SELL", fill_price=74.0))

        assert PRICE_THROUGH_LIMIT in log.codes()

    def test_a_print_outside_the_corridor_is_reported(self) -> None:
        log = Log().line(
            "circuit_breaker.halt.AAPL",
            {
                "symbol": "AAPL",
                "corridor_low": 70.0,
                "corridor_high": 80.0,
                "halt_source": "BREAKER",
            },
        )
        log.line("trade.executed", _trade(price=85.0))

        assert PRICE_OUTSIDE_CORRIDOR in log.codes()
        assert "70-80 corridor" in log.detail(PRICE_OUTSIDE_CORRIDOR)

    def test_a_print_inside_it_is_not(self) -> None:
        log = Log().line(
            "circuit_breaker.halt.AAPL",
            {
                "symbol": "AAPL",
                "corridor_low": 70.0,
                "corridor_high": 80.0,
                "halt_source": "BREAKER",
            },
        )
        log.line("trade.executed", _trade(price=75.0))

        assert PRICE_OUTSIDE_CORRIDOR not in log.codes()


# ---------------------------------------------------------------------------
# 12.3 — clocks and sequence
# ---------------------------------------------------------------------------


class TestClocksAndSequence:
    def test_an_engine_clock_far_from_receipt_is_reported(self) -> None:
        log = Log().line(
            "trade.executed", _trade(ts_ns=_nanos(BASE + timedelta(seconds=2)))
        )

        assert CLOCK_SKEW in log.codes()
        assert "2.000s from receipt" in log.detail(CLOCK_SKEW)

    def test_ordinary_transit_delay_is_not(self) -> None:
        """A few milliseconds between publishing and receipt is the bus doing
        its job, and a report that fires on every line is no report."""
        log = Log().line(
            "trade.executed", _trade(ts_ns=_nanos(BASE - timedelta(milliseconds=5)))
        )

        assert CLOCK_SKEW not in log.codes()

    def test_a_client_clock_hours_out_is_reported(self) -> None:
        log = Log().line(
            "order.new", _submitted(ts_ns=_nanos(BASE - timedelta(hours=2)))
        )

        assert CLIENT_CLOCK_ABSURD in log.codes()

    def test_the_client_clock_is_not_measured_against_the_engine_tolerance(
        self,
    ) -> None:
        """Two seconds out is a fault in the engine's clock and nothing at all
        in a client's -- the book never reads this field."""
        log = Log().line(
            "order.new", _submitted(ts_ns=_nanos(BASE - timedelta(seconds=2)))
        )

        assert CLOCK_SKEW not in log.codes()
        assert CLIENT_CLOCK_ABSURD not in log.codes()

    def test_an_arrival_seq_gap_is_reported_under_strict(self) -> None:
        log = Log(strict=True).line("order.new", _submitted(arrival_seq=10))
        log.line("order.new", _submitted(id=OTHER, arrival_seq=14))

        assert ARRIVAL_SEQ_GAP in log.codes()
        assert "3 submission(s) not in this window" in log.detail(ARRIVAL_SEQ_GAP)

    def test_it_is_silent_without_strict(self) -> None:
        """A window that omits another gateway's orders has gaps by
        construction (section 12.3)."""
        log = Log().line("order.new", _submitted(arrival_seq=10))
        log.line("order.new", _submitted(id=OTHER, arrival_seq=14))

        assert ARRIVAL_SEQ_GAP not in log.codes()

    def test_a_reused_arrival_seq_is_reported(self) -> None:
        """Two orders claiming one queue position. Time priority is keyed on
        this counter, so a repeat is a priority bug rather than a window
        edge -- which is why it fires without ``--strict``."""
        log = Log().line("order.new", _submitted(arrival_seq=8814))
        log.line("order.new", _submitted(id=OTHER, arrival_seq=8814))

        assert ARRIVAL_SEQ_REUSED in log.codes()
        assert "two orders claim one queue position" in log.detail(ARRIVAL_SEQ_REUSED)

    def test_a_decreasing_arrival_seq_is_too(self) -> None:
        log = Log().line("order.new", _submitted(arrival_seq=8814))
        log.line("order.new", _submitted(id=OTHER, arrival_seq=8810))

        assert ARRIVAL_SEQ_REUSED in log.codes()
        assert "the counter went backwards" in log.detail(ARRIVAL_SEQ_REUSED)

    def test_an_unassigned_arrival_seq_is_not_a_reuse(self) -> None:
        """``order.yaml``: "0 = unassigned". ``order.new`` is the command as
        the engine received it and the sequence is stamped when the book
        accepts it, so on a real trail every order carries 0 -- which read as
        2854 orders claiming one queue position."""
        log = Log().line("order.new", _submitted(arrival_seq=0))
        log.line("order.new", _submitted(id=OTHER, arrival_seq=0))

        assert ARRIVAL_SEQ_REUSED not in log.codes()

    def test_a_restart_restarts_the_counter(self) -> None:
        """The counter lives with the engine process. Reporting the restart as
        a reuse is the publisher-restart false positive ``SEQ_GAP`` already
        learned to avoid."""
        log = Log().line("trade.executed", _trade(run_seq=42))
        log.line("order.new", _submitted(arrival_seq=8814))
        log.line("trade.executed", _trade(id="000043-000000001", run_seq=43))
        log.line("order.new", _submitted(id=OTHER, arrival_seq=1))

        assert ARRIVAL_SEQ_REUSED not in log.codes()

    def test_the_engine_clock_is_found_under_its_other_name(self) -> None:
        """``drop_copy`` calls its publication clock ``timestamp``. Keying the
        check on the literal ``ts_ns`` exempted the whole clearing feed from
        it, in silence (AR-8.6)."""
        log = Log().line(
            "drop_copy.event." + GATEWAY,
            _copy(timestamp=_nanos(BASE + timedelta(seconds=2))),
        )

        assert CLOCK_SKEW in log.codes()

    def test_a_gap_in_the_trade_counter_is_reported(self) -> None:
        log = Log().line("trade.executed", _trade(id="000042-000000001"))
        log.line("trade.executed", _trade(id="000042-000000005"))

        assert TRADE_COUNTER_GAP in log.codes()
        assert "3 trade(s) missing" in log.detail(TRADE_COUNTER_GAP)

    def test_consecutive_trades_are_not(self) -> None:
        log = Log().line("trade.executed", _trade(id="000042-000000001"))
        log.line("trade.executed", _trade(id="000042-000000002"))

        assert TRADE_COUNTER_GAP not in log.codes()


# ---------------------------------------------------------------------------
# 12.4 — command reconciliation
# ---------------------------------------------------------------------------


class TestCommands:
    def test_a_command_with_no_ack_is_reported(self) -> None:
        log = Log().line(
            "risk.kill_switch",
            {"gateway_id": "RISK01", "symbol": "AAPL", "command_id": "8812"},
        )

        assert COMMAND_UNACKED in log.codes()

    def test_an_acked_command_is_not(self) -> None:
        log = Log().line(
            "risk.kill_switch",
            {"gateway_id": "RISK01", "symbol": "AAPL", "command_id": "8812"},
        )
        log.line(
            "admin.action.RISK01",
            {
                "gateway_id": "RISK01",
                "command_id": "8812",
                "action": "KILL_SWITCH",
                "accepted": True,
            },
        )

        assert COMMAND_UNACKED not in log.codes()

    def test_a_halt_with_no_resume_is_reported(self) -> None:
        log = Log().line(
            "circuit_breaker.halt.AAPL", {"symbol": "AAPL", "halt_source": "BREAKER"}
        )

        assert HALT_UNRESUMED in log.codes()

    def test_a_halt_that_is_resumed_is_not(self) -> None:
        log = Log().line(
            "circuit_breaker.halt.AAPL", {"symbol": "AAPL", "halt_source": "BREAKER"}
        )
        log.line(
            "circuit_breaker.resume.AAPL", {"symbol": "AAPL", "halt_source": "BREAKER"}
        )

        assert HALT_UNRESUMED not in log.codes()


# ---------------------------------------------------------------------------
# 12.5 — coverage
# ---------------------------------------------------------------------------


class TestParseFailure:
    """``PARSE_FAILURE`` is the one code detected by an absence.

    ``iter_entries`` drops a line the audit format does not match, so nothing
    downstream ever sees it. What it leaves is a hole in ``line_no``, and that
    is only visible in read order -- before the ordering pass, which is why
    this lives in ``normalise`` and not in the detector.
    """

    def _log(self, tmp_path: Path, lines: list[str]) -> list[str]:
        path = tmp_path / "audit.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return [
            anomaly.code
            for fact in normalise(iter_entries([path]))
            for anomaly in fact.anomalies
        ]

    def test_a_line_that_did_not_parse_is_reported(self, tmp_path: Path) -> None:
        good = (
            "[2026-09-08T09:31:02.110+00:00] [order.cancel] "
            '{"order_id": "%s", "gateway_id": "TRADER01"}'
        )
        codes = self._log(
            tmp_path,
            [good % ORDER, "this line is not an audit record at all", good % OTHER],
        )

        assert PARSE_FAILURE in codes

    def test_an_intact_log_is_not(self, tmp_path: Path) -> None:
        good = (
            "[2026-09-08T09:31:02.110+00:00] [order.cancel] "
            '{"order_id": "%s", "gateway_id": "TRADER01"}'
        )
        codes = self._log(tmp_path, [good % ORDER, good % OTHER])

        assert PARSE_FAILURE not in codes

    def test_it_is_an_error_and_says_how_many_were_lost(self, tmp_path: Path) -> None:
        good = (
            "[2026-09-08T09:31:02.110+00:00] [order.cancel] "
            '{"order_id": "%s", "gateway_id": "TRADER01"}'
        )
        path = tmp_path / "audit.log"
        path.write_text(
            "\n".join([good % ORDER, "junk", "more junk", good % OTHER]) + "\n",
            encoding="utf-8",
        )
        found = [
            anomaly
            for fact in normalise(iter_entries([path]))
            for anomaly in fact.anomalies
            if anomaly.code == PARSE_FAILURE
        ]

        assert len(found) == 1
        assert found[0].severity == SEVERITY_ERROR
        assert "2 line(s)" in found[0].detail
        assert found[0].line_no == 4


# ---------------------------------------------------------------------------
# What a real engine run does that the fixtures never did
# ---------------------------------------------------------------------------


class TestTheEngineSPublicationShape:
    """Five checks that fired on a healthy trail and should not have.

    AR-5.1 was verified against five hand-written fixtures and every check had
    a firing case paired with one that must not fire. All of it passed, and the
    detector was still wrong about how the engine publishes: the first real
    ``pm-audit`` trail produced 2450 findings, of which ~2100 were these.

    Each test below is one of those, reduced to the smallest log that shows it.
    """

    def test_a_fill_may_be_read_before_the_trade_that_produced_it(self) -> None:
        """The engine publishes ``order.fill, order.fill, trade.executed``.

        The check used to be made when the fill was read, on the assumption
        that a trade is published before its fills. Every fill in the log was
        reported as missing its trade -- 603 out of 603.
        """
        log = Log().line("order.new", _submitted()).line("order.ack." + GATEWAY, _ack())
        log.line("order.fill." + GATEWAY, _fill())
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, side="SELL"))
        log.line("trade.executed", _trade())

        assert FILL_WITHOUT_TRADE not in log.codes()

    def test_one_fill_may_cover_several_trades(self) -> None:
        """An aggressor sweeping two resting orders is reported *once*, at a
        VWAP, citing both trades (``order.fill.trade_ids``, H5/H6). On a real
        run 316 of 603 fills did this.

        Its quantity is the sweep's, so comparing it against either passive
        leg is comparing different things -- which reported 635 quantity
        disagreements and 277 price disagreements that were not.
        """
        other_trade = "000042-000001874"
        log = Log().line("trade.executed", _trade())
        log.line("trade.executed", _trade(id=other_trade, price=75.5))
        log.line(
            "order.fill." + GATEWAY,
            _fill(fill_qty=300, fill_price=75.25, trade_ids=[TRADE, other_trade]),
        )
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_qty=100))
        log.line(
            "order.fill.TRADER10",
            _fill(
                order_id="c" * 32,
                fill_qty=200,
                fill_price=75.5,
                trade_ids=[other_trade],
            ),
        )

        codes = log.codes()

        assert LEG_QTY_DISAGREE not in codes
        assert LEG_PRICE_DISAGREE not in codes

    def test_two_plain_legs_are_still_compared(self) -> None:
        """The exemption is for coalesced legs only. A trade whose two legs
        each name it and nothing else still has to agree."""
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill(fill_qty=200))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_qty=150))

        assert LEG_QTY_DISAGREE in log.codes()

    def test_an_amended_limit_is_the_limit(self) -> None:
        """``order.amended`` moves the price the fills are measured against.

        Holding the price from ``order.new`` reported 63 fills as trading
        through a limit the order no longer had.
        """
        log = Log().line("order.new", _submitted(price_ticks=7500))
        log.line("order.ack." + GATEWAY, _ack())
        log.line(
            "order.amended." + GATEWAY,
            {"gateway_id": GATEWAY, "order_id": ORDER, "price": 76.0, "qty": 200},
        )
        log.line("trade.executed", _trade(price=76.0))
        log.line("order.fill." + GATEWAY, _fill(fill_price=76.0))

        assert PRICE_THROUGH_LIMIT not in log.codes()

    def test_the_limit_still_binds_after_an_amendment(self) -> None:
        """Following the amendment must not mean ignoring the limit."""
        log = Log().line("order.new", _submitted(price_ticks=7500))
        log.line("order.ack." + GATEWAY, _ack())
        log.line(
            "order.amended." + GATEWAY,
            {"gateway_id": GATEWAY, "order_id": ORDER, "price": 76.0, "qty": 200},
        )
        log.line("trade.executed", _trade(price=77.0))
        log.line("order.fill." + GATEWAY, _fill(fill_price=77.0))

        assert PRICE_THROUGH_LIMIT in log.codes()

    def test_an_acceptance_then_a_refusal_is_not_a_duplicate(self) -> None:
        """The engine acks a FOK and then rejects it when the book cannot fill
        it whole; a triggered stop is acked again when it converts. Both are
        two acks for one order and neither is a duplicate acceptance."""
        log = Log().line("order.new", _submitted(order_type="FOK"))
        log.line("order.ack." + GATEWAY, _ack())
        log.line(
            "order.ack." + GATEWAY, _ack(accepted=False, reject_code="NO_LIQUIDITY")
        )

        assert ACK_DUPLICATE not in log.codes()

    def test_two_acceptances_still_are(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("order.ack." + GATEWAY, _ack())

        assert ACK_DUPLICATE in log.codes()


# ---------------------------------------------------------------------------
# The property that makes the report worth reading
# ---------------------------------------------------------------------------

#: The fixtures that depict a healthy exchange. ``02`` carries a deliberate
#: discrepancy, ``03`` is an archive from before the envelope existed, and ``04``
#: omits the ``order.ack`` the engine publishes for every order -- none of the
#: three claims to be clean.
CLEAN_FIXTURES = ("01_simple_limit_partial_fill", "05_session_and_index")


class TestAHealthyLogIsSilent:
    @pytest.mark.parametrize("name", CLEAN_FIXTURES)
    def test_no_finding_of_any_kind(self, name: str) -> None:
        run, steps = reconstruct(iter_entries([fixture_log(name)]))
        detector = Detector(run.state)
        episodes = list(
            detected(
                assemble(observed(steps, detector), run.state, run.links), detector
            )
        )
        found = [
            str(anomaly)
            for episode in episodes
            for anomaly in (
                [a for event in episode.events for a in event.step.anomalies]
                + list(episode.anomalies)
            )
        ]

        assert found == []


# ---------------------------------------------------------------------------
# Findings that were not findings (holistic review, 2026-09-15)
# ---------------------------------------------------------------------------


class TestTheDetectorDoesNotInventFindings:
    """Four checks that fired on healthy input.

    A false positive costs more than a missed one here: the tool's whole claim
    is that a clean run means something, and a reader who has learned to
    ignore a code has lost the code.
    """

    def test_a_window_opening_mid_order_is_not_a_quantity_mismatch(self) -> None:
        """``filled_qty`` is a tally that starts at zero, so without the
        submission it is short by everything before the window while
        ``quantity - remaining_qty`` is not. ``--from``/``--last`` is the
        normal way this tool is used, and every later fill reported an error.
        """
        log = Log()
        log.line("order.fill." + GATEWAY, _fill(fill_qty=100, remaining_qty=100))
        log.line("order.fill." + GATEWAY, _fill(fill_qty=100, remaining_qty=0))

        assert QTY_MISMATCH not in log.codes()

    def test_a_tally_that_really_disagrees_still_is(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("order.fill." + GATEWAY, _fill(fill_qty=50, remaining_qty=100))

        assert QTY_MISMATCH in log.codes()

    def test_an_unrecognised_side_does_not_trade_through_its_limit(self) -> None:
        """The comparison was a two-way branch, so anything that was not
        ``BUY`` was measured as a sell: a corrupt side turned a fill *below* a
        buy limit into an error-severity finding about trading through it."""
        log = Log().line("order.new", _submitted(side="BUYY"))
        log.line("order.ack." + GATEWAY, _ack())
        log.line("trade.executed", _trade(price=74.0))
        log.line("order.fill." + GATEWAY, _fill(fill_price=74.0, side="BUYY"))

        assert PRICE_THROUGH_LIMIT not in log.codes()

    def test_a_real_limit_breach_still_is(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("trade.executed", _trade(price=76.0))
        log.line("order.fill." + GATEWAY, _fill(fill_price=76.0))

        assert PRICE_THROUGH_LIMIT in log.codes()

    def test_a_refused_cancel_is_answered(self) -> None:
        """Section 12.1 is "no resulting order.cancelled *or rejection*". The
        rejection was left out, so a properly refused cancel — ORDER_NOT_FOUND
        on an order that had already filled — read as one the engine ignored.
        """
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("order.cancel", {"order_id": ORDER, "gateway_id": GATEWAY})
        log.line(
            "order.ack." + GATEWAY,
            _ack(accepted=False, reject_code="ORDER_NOT_FOUND"),
        )

        assert CANCEL_UNMATCHED not in log.codes()

    def test_a_cancel_that_vanished_still_is(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("order.cancel", {"order_id": ORDER, "gateway_id": GATEWAY})

        assert CANCEL_UNMATCHED in log.codes()


# ---------------------------------------------------------------------------
# Phase 8 — the invariants the tool used to take on trust
# ---------------------------------------------------------------------------


class TestThePrintIsTheThirdParty:
    """AR-8.1. ``_legs_agree`` compares the legs to each other, and two
    equally wrong legs agree: a trade printing 200 whose fills both report 150
    was a public tape and a pair of private reports saying different things,
    in silence."""

    def test_legs_that_agree_with_each_other_and_not_with_the_print(self) -> None:
        log = Log().line("trade.executed", _trade(quantity=200))
        log.line("order.fill." + GATEWAY, _fill(fill_qty=150))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_qty=150))

        codes = log.codes()

        assert PRINT_QTY_DISAGREE in codes
        # The two checks answer different questions and neither covers the
        # other: the legs really do agree.
        assert LEG_QTY_DISAGREE not in codes

    def test_the_same_for_the_price(self) -> None:
        log = Log().line("trade.executed", _trade(price=75.0))
        log.line("order.fill." + GATEWAY, _fill(fill_price=80.0))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_price=80.0))

        codes = log.codes()

        assert PRINT_PRICE_DISAGREE in codes
        assert LEG_PRICE_DISAGREE not in codes

    def test_legs_that_match_the_print_are_silent(self) -> None:
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill())
        log.line("order.fill.TRADER09", _fill(order_id=OTHER))

        codes = log.codes()

        assert PRINT_QTY_DISAGREE not in codes
        assert PRINT_PRICE_DISAGREE not in codes

    def test_a_coalesced_leg_is_exempt(self) -> None:
        """A sweep is reported once at a VWAP, so it is not any one trade's
        quantity or price (H5/H6) -- the exemption ``LEG_QTY_DISAGREE``
        already makes."""
        other_trade = "000042-000001874"
        log = Log().line("trade.executed", _trade())
        log.line("trade.executed", _trade(id=other_trade, price=75.5))
        log.line(
            "order.fill." + GATEWAY,
            _fill(fill_qty=300, fill_price=75.25, trade_ids=[TRADE, other_trade]),
        )
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, fill_qty=200))
        log.line(
            "order.fill.TRADER10",
            _fill(
                order_id="c" * 32,
                fill_qty=200,
                fill_price=75.5,
                trade_ids=[other_trade],
            ),
        )

        codes = log.codes()

        assert PRINT_QTY_DISAGREE not in codes
        assert PRINT_PRICE_DISAGREE not in codes

    def test_a_leg_on_an_order_the_trade_does_not_name(self) -> None:
        """Counting legs cannot tell a fill on the right order from one on an
        order this trade never touched, and two of the wrong legs count as
        two."""
        stranger = "c" * 32
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill())
        log.line("order.fill.TRADER10", _fill(order_id=stranger))

        assert TRADE_LEG_UNKNOWN in log.codes()
        assert stranger in log.detail(TRADE_LEG_UNKNOWN)

    def test_a_single_leg_is_still_identified(self) -> None:
        """``TRADE_LEG_MISSING`` says one leg is missing; it does not say the
        one that arrived belongs to this trade."""
        log = Log().line("trade.executed", _trade())
        log.line("order.fill.TRADER10", _fill(order_id="c" * 32))

        codes = log.codes()

        assert TRADE_LEG_MISSING in codes
        assert TRADE_LEG_UNKNOWN in codes


class TestAMessageMayNotContradictItself:
    """AR-8.2. ``order.yaml``: "remaining_qty reaching zero is what marks the
    order done; status FILLED says the same thing and the two must agree"."""

    def test_filled_with_quantity_remaining(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("order.fill." + GATEWAY, _fill(fill_qty=150, remaining_qty=50))

        assert FILL_STATUS_DISAGREE in log.codes()

    def test_partial_with_nothing_left(self) -> None:
        """The direction that costs a reader most: a blotter line closed while
        the order is still resting."""
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line("order.fill." + GATEWAY, _fill(status="PARTIAL", remaining_qty=0))

        assert FILL_STATUS_DISAGREE in log.codes()
        assert "nothing left to fill" in log.detail(FILL_STATUS_DISAGREE)

    def test_a_fill_that_agrees_with_itself_is_silent(self) -> None:
        log = Log().line("order.new", _submitted())
        log.line("order.ack." + GATEWAY, _ack())
        log.line(
            "order.fill." + GATEWAY,
            _fill(fill_qty=150, remaining_qty=50, status="PARTIAL"),
        )

        assert FILL_STATUS_DISAGREE not in log.codes()


class TestLiquidityAttribution:
    """AR-8.3. Maker and taker fees invert on this flag, so a wrong one is not
    a display problem."""

    def test_both_sides_flagged_taker(self) -> None:
        log = Log().line("trade.executed", _trade(aggressor_side="BUY"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="TAKER"))

        assert LIQUIDITY_FLAG_DISAGREE in log.codes()
        assert OTHER in log.detail(LIQUIDITY_FLAG_DISAGREE)

    def test_the_aggressor_is_the_taker(self) -> None:
        log = Log().line("trade.executed", _trade(aggressor_side="BUY"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))

        assert LIQUIDITY_FLAG_DISAGREE not in log.codes()

    def test_an_uncross_print_has_two_makers(self) -> None:
        """Both sides rested, so there is no aggressor and the engine flags
        both MAKER."""
        log = Log().line("trade.executed", _trade(aggressor_side="AUCTION"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="MAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))

        assert LIQUIDITY_FLAG_DISAGREE not in log.codes()

    def test_an_uncross_print_with_a_taker_is_not(self) -> None:
        log = Log().line("trade.executed", _trade(aggressor_side="AUCTION"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))

        assert LIQUIDITY_FLAG_DISAGREE in log.codes()


class TestTheDropCopyFeed:
    """AR-8.4. The feed clearing and prime brokers reconcile on, about which
    the tool had no opinion at all: no state handler, no branch in
    ``Detector.observe``, and a documented sequence counter nothing read."""

    def _matched(self) -> Log:
        """One execution, completely reported: the print, both private fills
        and both drop copies."""
        log = Log().line("trade.executed", _trade(aggressor_side="BUY"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))
        log.line("drop_copy.event." + GATEWAY, _copy())
        log.line(
            "drop_copy.event.TRADER09",
            _copy(seq=2, gateway_id="TRADER09", order_id=OTHER, liquidity_flag="MAKER"),
        )
        return log

    def test_a_complete_execution_is_silent(self) -> None:
        assert self._matched().codes() == []

    def test_a_gap_in_the_feed_counter(self) -> None:
        log = Log().line("drop_copy.event." + GATEWAY, _copy(seq=1))
        log.line("drop_copy.event.TRADER09", _copy(seq=9, gateway_id="TRADER09"))

        assert DROP_COPY_SEQ_GAP in log.codes()
        assert "7 event(s) missing" in log.detail(DROP_COPY_SEQ_GAP)

    def test_a_repeat_in_the_feed_counter(self) -> None:
        """``drop_copy.yaml``: a recipient "detects loss from a gap and a
        duplicate from a repeat", which is the whole reason it is sequenced --
        so a repeat counts, unlike ``SEQ_GAP``."""
        log = Log().line("drop_copy.event." + GATEWAY, _copy(seq=4))
        log.line("drop_copy.event.TRADER09", _copy(seq=4, gateway_id="TRADER09"))

        assert DROP_COPY_SEQ_GAP in log.codes()
        assert "repeated an event" in log.detail(DROP_COPY_SEQ_GAP)

    def test_the_counter_is_one_stream_across_the_gateways(self) -> None:
        """``engine/drop_copy.py`` counts on a module-level
        ``itertools.count``, so consecutive events on two gateways' topics are
        consecutive numbers -- reading it per gateway would report every
        second event as a gap."""
        log = Log().line("drop_copy.event." + GATEWAY, _copy(seq=1))
        log.line("drop_copy.event.TRADER09", _copy(seq=2, gateway_id="TRADER09"))
        log.line("drop_copy.event." + GATEWAY, _copy(seq=3))

        assert DROP_COPY_SEQ_GAP not in log.codes()

    def test_a_restart_restarts_the_counter(self) -> None:
        log = Log().line("trade.executed", _trade(run_seq=42))
        log.line("drop_copy.event." + GATEWAY, _copy(seq=880))
        log.line("trade.executed", _trade(id="000043-000000001", run_seq=43))
        log.line("drop_copy.event." + GATEWAY, _copy(seq=1))

        assert DROP_COPY_SEQ_GAP not in log.codes()

    def test_a_copy_that_disagrees_with_the_fill_it_copies(self) -> None:
        log = Log().line("trade.executed", _trade(aggressor_side="BUY"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))
        log.line("drop_copy.event." + GATEWAY, _copy(fill_qty=999))
        log.line(
            "drop_copy.event.TRADER09",
            _copy(seq=2, gateway_id="TRADER09", order_id=OTHER, liquidity_flag="MAKER"),
        )

        assert DROP_COPY_DISAGREE in log.codes()
        assert "fill_qty 999 against 200" in log.detail(DROP_COPY_DISAGREE)

    def test_a_copy_of_a_coalesced_fill_is_exempt(self) -> None:
        """The drop copy reports one execution and the coalesced fill reports
        the whole sweep at a VWAP, so the two *should* differ."""
        other_trade = "000042-000001874"
        log = Log().line("trade.executed", _trade())
        log.line("trade.executed", _trade(id=other_trade, price=75.5))
        log.line(
            "order.fill." + GATEWAY,
            _fill(fill_qty=300, fill_price=75.25, trade_ids=[TRADE, other_trade]),
        )
        log.line("drop_copy.event." + GATEWAY, _copy(fill_qty=200, fill_price=75.0))

        assert DROP_COPY_DISAGREE not in log.codes()

    def test_a_trade_that_produced_one_copy(self) -> None:
        log = Log().line("trade.executed", _trade(aggressor_side="BUY"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))
        log.line("drop_copy.event." + GATEWAY, _copy())

        assert DROP_COPY_MISSING in log.codes()
        assert "1 drop copy(ies), not 2" in log.detail(DROP_COPY_MISSING)

    def test_two_copies_of_one_side_are_not_two_copies(self) -> None:
        """A count would pass this: the buyer's clearing broker was told
        twice and the seller's not at all."""
        log = Log().line("trade.executed", _trade(aggressor_side="BUY"))
        log.line("order.fill." + GATEWAY, _fill(liquidity_flag="TAKER"))
        log.line("order.fill.TRADER09", _fill(order_id=OTHER, liquidity_flag="MAKER"))
        log.line("drop_copy.event." + GATEWAY, _copy())
        log.line("drop_copy.event." + GATEWAY, _copy(seq=2))

        assert DROP_COPY_MISSING in log.codes()

    def test_a_log_with_no_drop_copy_feed_at_all_is_silent(self) -> None:
        """An engine configured without the publisher would otherwise have
        every trade it ever printed reported as missing both copies."""
        log = Log().line("trade.executed", _trade())
        log.line("order.fill." + GATEWAY, _fill())
        log.line("order.fill.TRADER09", _fill(order_id=OTHER))

        assert DROP_COPY_MISSING not in log.codes()
