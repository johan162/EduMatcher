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
    ACK_MISSING,
    ARRIVAL_SEQ_GAP,
    CANCEL_UNMATCHED,
    CANCEL_UNSOLICITED,
    CLIENT_CLOCK_ABSURD,
    CLOCK_SKEW,
    COMMAND_UNACKED,
    FILL_BEFORE_ACK,
    FILL_WITHOUT_TRADE,
    HALT_UNRESUMED,
    LEG_PRICE_DISAGREE,
    LEG_QTY_DISAGREE,
    PARSE_FAILURE,
    PRICE_OUTSIDE_CORRIDOR,
    PRICE_THROUGH_LIMIT,
    SEVERITY_ERROR,
    TERMINAL_MISSING,
    TRADE_COUNTER_GAP,
    TRADE_LEG_MISSING,
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
