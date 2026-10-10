"""pm-market-sim's core, driven with a logical clock (no sockets)."""

from __future__ import annotations

import math
import statistics
from pathlib import Path

import pytest

from edumatcher.market_sim.config import SimConfig, SimConfigError
from edumatcher.market_sim.main import (
    DEFAULT_DAY_SEC,
    MarketSim,
    SavedState,
    initial_values,
    load_state,
    save_state,
)
from edumatcher.market_sim.model import TRADING_DAYS_PER_YEAR, SymbolParams
from edumatcher.market_sim.news import NewsConfig
from edumatcher.models.generated import sim as G
from edumatcher.models.message import decode

NO_NEWS = NewsConfig(rate_symbol=0.0, rate_sector=0.0, rate_market=0.0)

QUIET = SymbolParams(
    "X", vol=0.3, drift=0.0, jump_rate=0.0, beta_market=0.0, beta_sector=0.0
)


def _cfg(n: int = 2, step: float = 1.0, params: SymbolParams = QUIET) -> SimConfig:
    return SimConfig(
        seed=3,
        step_sec=step,
        overnight_fraction=0.2,
        params={f"S{i}": params for i in range(n)},
        initial={},
        news=NO_NEWS,
    )


def _sim(**kw: object) -> MarketSim:
    cfg = _cfg()
    return MarketSim(cfg, {s: 100.0 for s in cfg.params}, **kw)  # type: ignore[arg-type]


def test_steps_only_in_continuous_trading() -> None:
    sim = _sim()
    sim.on_session("CLOSED", None, 0.0)
    assert not sim.due(10.0)
    sim.on_session("PRE_OPEN", None, 10.0)
    sim.on_session("OPENING_AUCTION", None, 11.0)
    assert not sim.due(12.0)
    sim.on_session("CONTINUOUS", 1000.0, 12.0)
    assert not sim.due(12.5) and sim.due(13.0)
    frames = sim.step(13.0)[-1]
    msg = G.parse_sim_value(frames)
    assert msg.seq == 1 and [v.symbol for v in msg.values] == ["S0", "S1"]
    assert decode(sim.state_frames(13.0))[1]["state"] == "RUNNING"
    sim.on_session("CLOSING_AUCTION", None, 900.0)
    assert not sim.due(1000.0)
    assert decode(sim.state_frames(1000.0))[1]["state"] == "PAUSED"


def test_overnight_move_only_after_a_seen_close() -> None:
    sim = _sim()
    before = dict(sim.model.log_values)
    sim.on_session("PRE_OPEN", None, 0.0)  # first sight: no overnight
    assert sim.model.log_values == before
    sim.on_session("CLOSED", None, 1.0)
    sim.on_session("PRE_OPEN", None, 2.0)
    assert sim.model.log_values != before


def test_a_day_accrues_a_days_variance_whatever_its_length() -> None:
    """A continuous session of 60 s (compressed) or 6.5 h moves as much."""
    cfg = _cfg(n=1, step=1.0)
    sim = MarketSim(cfg, {"S0": 100.0})
    t, rets = 0.0, []
    for _ in range(3000):
        sim.on_session("CONTINUOUS", t + 60.0, t)
        start = sim.model.log_values["S0"]
        for _ in range(60):
            t += 1.0
            sim.step(t)
        rets.append(sim.model.log_values["S0"] - start)
        sim.on_session("CLOSING_AUCTION", None, t)
    day_var = QUIET.vol**2 / TRADING_DAYS_PER_YEAR
    assert statistics.variance(rets) / day_var == pytest.approx(1.0, abs=0.08)


def test_without_a_countdown_a_default_day_is_assumed() -> None:
    sim = _sim()
    sim.on_session("CONTINUOUS", None, 0.0)
    assert sim._day(10.0) == (DEFAULT_DAY_SEC, None)
    sim.on_session("CLOSING_AUCTION", None, 1.0)
    sim.on_session("CONTINUOUS", 101.0, 1.0)
    assert sim._day(51.0) == (100.0, 0.5)


def test_a_stall_is_not_one_huge_move() -> None:
    sim = _sim()
    sim.on_session("CONTINUOUS", None, 0.0)
    calls: list[float] = []
    sim.model.step = lambda dt, fraction=None: calls.append(dt)
    sim.step(1000.0)
    assert calls == [pytest.approx(5.0 / DEFAULT_DAY_SEC)]


def test_commands_need_an_admin() -> None:
    sim = _sim(admins=frozenset({"OPS01"}))
    refused = decode(
        sim.command({"gateway_id": "trader01", "command_id": "c"}, 0.0)[-1]
    )
    assert refused[0] == "sim.command_ack.TRADER01" and refused[1]["accepted"] is False
    ok = decode(
        sim.command(
            {"gateway_id": "OPS01", "command_id": "c2", "action": "STATUS"}, 0.0
        )[-1]
    )[1]
    assert ok["accepted"] is True and "seq=0" in ok["reason"]


def test_state_round_trip_and_restart_continuity(tmp_path: Path) -> None:
    sim = _sim()
    sim.on_session("CONTINUOUS", None, 0.0)
    for t in range(1, 6):
        sim.step(float(t))
    path = tmp_path / "state.json"
    save_state(path, sim.saved())
    saved = load_state(path)
    assert saved is not None and saved.seq == 5
    again = MarketSim(sim.cfg, saved.values, seq=saved.seq, epoch=saved.epoch + 1)
    assert again.model.values() == pytest.approx(sim.model.values())
    again.on_session("CONTINUOUS", None, 10.0)
    assert G.parse_sim_value(again.step(11.0)[-1]).seq == 6


def test_unreadable_state_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    assert load_state(path) is None
    path.write_text("{not json")
    assert load_state(path) is None


def test_initial_value_precedence() -> None:
    cfg = SimConfig(1, 1.0, 0.2, {s: QUIET for s in "ABCD"}, {"B": 2.0}, NO_NEWS)
    saved = SavedState(1, 0, {"A": 1.0, "B": 9.0})
    vals = initial_values(
        cfg, None, {"C": 3.0}, {"A": 7.0, "B": 7.0, "C": 7.0, "D": 4.0}
    )
    assert vals == {"A": 7.0, "B": 2.0, "C": 3.0, "D": 4.0}
    assert initial_values(cfg, saved, {}, {"C": 5.0, "D": 4.0})["A"] == 1.0
    with pytest.raises(SimConfigError, match="D"):
        initial_values(cfg, None, {}, {"A": 1.0, "C": 1.0})


def test_values_are_published_rounded() -> None:
    sim = _sim()
    sim.on_session("CONTINUOUS", None, 0.0)
    v = G.parse_sim_value(sim.step(1.0)[-1]).values[0].value
    assert v == round(v, 4) and math.isfinite(v)


def test_deviations_widest_first() -> None:
    from edumatcher.market_sim.main import deviations

    out = deviations({"A": 100.0, "B": 50.0, "C": 10.0}, {"A": 101.0, "B": 45.0})
    assert [s for s, _ in out] == ["B", "A"]
    assert out[0][1] == pytest.approx(math.log(0.9))
