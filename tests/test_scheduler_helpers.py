"""Tests for src/edumatcher/scheduler/main.py helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.config_deploy import deploy
from edumatcher.engine.config_loader import ScheduleConfig
from edumatcher.scheduler.main import (
    DEFAULT_SCHEDULE,
    _run_now,
    _schedule_from_config,
    _time_today,
)


def _deploy(tmp_path: Path) -> Path:
    """Compile a minimal configuration into tmp_path and return the artifact."""
    source = tmp_path / "authored.yaml"
    source.write_text(
        "symbols:\n  AAPL: {tick_decimals: 2, last_buy_price: 150.0}\n"
        "gateways:\n  alf: [{id: TRADER01, role: TRADER}]\n"
    )
    dest = tmp_path / "engine_config.json"
    deploy(source, dest)
    return dest


# ---------------------------------------------------------------------------
# _load_schedule
# ---------------------------------------------------------------------------


class TestScheduleFromConfig:
    """`_load_schedule` is gone: its YAML parsing now lives in
    ``load_engine_config`` and its tolerance for a missing or malformed raw
    file is the compile step's job. What remains is the mapping from a
    compiled ScheduleConfig onto the engine's transition sequence.
    """

    def test_maps_every_phase_in_order(self) -> None:
        result = _schedule_from_config(ScheduleConfig())
        assert [state for _time, state in result] == [
            "PRE_OPEN",
            "OPENING_AUCTION",
            "CONTINUOUS",
            "CLOSING_AUCTION",
            "CLOSED",
        ]

    def test_the_default_schedule_matches_the_default_config(self) -> None:
        # Two spellings of the same timetable; if they drift, a deployment
        # with no `schedule:` block would run different times from one that
        # spelled out the documented defaults.
        assert _schedule_from_config(ScheduleConfig()) == DEFAULT_SCHEDULE

    def test_carries_configured_times_through(self) -> None:
        result = _schedule_from_config(ScheduleConfig(pre_open="08:00"))
        assert result[0] == ("08:00", "PRE_OPEN")


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

    @patch("edumatcher.scheduler.main.make_subscriber", return_value=MagicMock())
    @patch("edumatcher.scheduler.main._run_scheduled")
    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.make_pusher", return_value=MagicMock())
    def test_scheduled_mode(
        self,
        mock_pusher: MagicMock,
        mock_sleep: MagicMock,
        mock_run_scheduled: MagicMock,
        mock_subscriber: MagicMock,
        tmp_path: Path,
    ) -> None:
        # The schedule now comes from the compiled artifact, so this deploys
        # one rather than patching a YAML path.
        _deploy(tmp_path)
        with (
            patch("sys.argv", ["pm-scheduler"]),
            patch(
                "edumatcher.config_artifact.COMPILED_CONFIG_FILE",
                tmp_path / "engine_config.json",
            ),
        ):
            from edumatcher.scheduler.main import main

            main()
        mock_run_scheduled.assert_called_once()
        mock_pusher.return_value.close.assert_called_once()

    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.make_pusher", return_value=MagicMock())
    def test_missing_config_file_exits(
        self, mock_pusher: MagicMock, mock_sleep: MagicMock, tmp_path: Path
    ) -> None:
        # Nothing deployed at all: running a timetable the engine has never
        # seen is worse than not starting.
        missing = tmp_path / "absent" / "engine_config.json"
        with (
            patch("sys.argv", ["pm-scheduler"]),
            patch("edumatcher.config_artifact.COMPILED_CONFIG_FILE", missing),
        ):
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
