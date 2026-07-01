"""Tests for src/edumatcher/scheduler/main.py helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.scheduler.main import _load_schedule, _run_now, _time_today


# ---------------------------------------------------------------------------
# _load_schedule
# ---------------------------------------------------------------------------


class TestLoadSchedule:
    def test_returns_default_when_no_config(self) -> None:
        from edumatcher.scheduler.main import DEFAULT_SCHEDULE

        result = _load_schedule(None)
        assert result == DEFAULT_SCHEDULE

    def test_returns_default_when_config_missing(self, tmp_path: Path) -> None:
        from edumatcher.scheduler.main import DEFAULT_SCHEDULE

        result = _load_schedule(tmp_path / "nonexistent.yaml")
        assert result == DEFAULT_SCHEDULE

    def test_loads_schedule_from_yaml(self, tmp_path: Path) -> None:
        config = tmp_path / "sched.yaml"
        config.write_text(
            "schedule:\n"
            "  pre_open: '08:00'\n"
            "  opening_auction_start: '09:00'\n"
            "  continuous_start: '09:30'\n"
            "  closing_auction_start: '16:00'\n"
            "  closing_auction_end: '16:10'\n"
        )
        result = _load_schedule(config)
        states = [state for _, state in result]
        assert "PRE_OPEN" in states
        assert "CONTINUOUS" in states

    def test_falls_back_to_default_on_invalid_yaml(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        from edumatcher.scheduler.main import DEFAULT_SCHEDULE

        config = tmp_path / "bad.yaml"
        config.write_text("schedule: [[[invalid")
        result = _load_schedule(config)
        assert result == DEFAULT_SCHEDULE


# ---------------------------------------------------------------------------
# _time_today
# ---------------------------------------------------------------------------


class TestTimeToday:
    def test_returns_datetime_for_hhmm(self) -> None:
        from datetime import datetime

        result = _time_today("09:30")
        assert isinstance(result, datetime)
        assert result.hour == 9
        assert result.minute == 30


# ---------------------------------------------------------------------------
# _run_now
# ---------------------------------------------------------------------------


class TestRunNow:
    def test_sends_all_transitions(self) -> None:
        mock_sock = MagicMock()
        _run_now(mock_sock, delay=0.0)
        # 5 SessionState transitions
        assert mock_sock.send_multipart.call_count == 5

    def test_closes_nothing_itself(self) -> None:
        # _run_now doesn't close the socket (caller's responsibility)
        mock_sock = MagicMock()
        _run_now(mock_sock, delay=0.0)
        mock_sock.close.assert_not_called()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestSchedulerMain:
    @patch("edumatcher.scheduler.main._run_now")
    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.make_pusher", return_value=MagicMock())
    def test_now_mode(
        self,
        mock_pusher: MagicMock,
        mock_sleep: MagicMock,
        mock_run_now: MagicMock,
    ) -> None:
        with patch("sys.argv", ["pm-scheduler", "--now"]):
            from edumatcher.scheduler.main import main

            main()
        mock_run_now.assert_called_once()
        mock_pusher.return_value.close.assert_called_once()

    @patch("edumatcher.scheduler.main._run_scheduled")
    @patch("edumatcher.scheduler.main._load_schedule", return_value=[])
    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.make_pusher", return_value=MagicMock())
    def test_scheduled_mode(
        self,
        mock_pusher: MagicMock,
        mock_sleep: MagicMock,
        mock_load: MagicMock,
        mock_run_scheduled: MagicMock,
    ) -> None:
        with patch("sys.argv", ["pm-scheduler"]):
            from edumatcher.scheduler.main import main

            main()
        mock_run_scheduled.assert_called_once()
        mock_pusher.return_value.close.assert_called_once()

    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.make_pusher", return_value=MagicMock())
    def test_missing_config_file_exits(
        self, mock_pusher: MagicMock, mock_sleep: MagicMock, tmp_path: Path
    ) -> None:
        missing = str(tmp_path / "nope.yaml")
        with patch("sys.argv", ["pm-scheduler", "--config", missing]):
            from edumatcher.scheduler.main import main

            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# models/instrument.py — InstrumentState enum
# ---------------------------------------------------------------------------


def test_instrument_state_enum() -> None:
    from edumatcher.models.instrument import InstrumentState

    assert InstrumentState.ACTIVE == "ACTIVE"
    assert InstrumentState.HALTED == "HALTED"
    assert set(InstrumentState) == {InstrumentState.ACTIVE, InstrumentState.HALTED}
