"""The sim family: pm-market-sim's values, heartbeat and commands."""

from __future__ import annotations

import pytest

from edumatcher.models.generated import sim as G
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.message import decode

TICKERS = [f"S{i:03d}XYZW" for i in range(300)]  # 8-character symbols, worst case


def _values(n: int) -> list[dict[str, object]]:
    return [{"symbol": TICKERS[i], "value": 1234.5678 + i} for i in range(n)]


def test_value_round_trip() -> None:
    frames = G.make_sim_value(seq=7, ts_ns=2, values=_values(3))
    topic, payload = decode(frames)
    assert topic == G.TOPIC_SIM_VALUE
    msg = G.parse_sim_value(frames)
    assert msg.seq == 7 and [v.symbol for v in msg.values] == TICKERS[:3]
    assert payload["values"][0] == {"symbol": TICKERS[0], "value": 1234.5678}


def test_three_hundred_symbols_fit_one_frame() -> None:
    frames = G.make_sim_value(seq=1, ts_ns=2, values=_values(300))
    assert len(frames[1]) < 16 * 1024


@pytest.mark.parametrize(
    "values",
    [[], [{"symbol": "AAPL", "value": 0.0}], [{"symbol": "X" * 17, "value": 1.0}]],
)
def test_value_validation(values: list[dict[str, object]]) -> None:
    with pytest.raises(MessageValidationError):
        G.make_sim_value(seq=1, ts_ns=2, values=values)


def test_state_round_trip() -> None:
    frames = G.make_sim_state(
        state="PAUSED",
        session="CLOSED",
        seq=0,
        ts_ns=6,
        step_ns=1_000_000_000,
        symbols=150,
        seed=42,
    )
    msg = G.parse_sim_state(frames)
    assert (msg.state, msg.step_ns, msg.symbols) == ("PAUSED", 1_000_000_000, 150)
    with pytest.raises(MessageValidationError):
        G.make_sim_state(
            state="ASLEEP",
            session="",
            seq=0,
            ts_ns=0,
            step_ns=1,
            symbols=0,
            seed=0,
        )


def test_command_and_ack() -> None:
    cmd = G.parse_sim_command(
        G.make_sim_command(command_id="c1", gateway_id="OPS01", action="STATUS")
    )
    assert (cmd.command_id, cmd.action) == ("c1", "STATUS")
    frames = G.make_sim_command_ack(gateway_id="OPS01", command_id="c1", accepted=True)
    assert decode(frames)[0] == "sim.command_ack.OPS01"
    assert G.match_sim_command_ack("sim.command_ack.OPS01") == "OPS01"
    assert G.parse_sim_command_ack(frames).reason == ""


def test_news_event_round_trip() -> None:
    from edumatcher.models.generated import news as N

    frames = N.make_news_event(
        id="N1",
        ts_ns=5,
        scope="SYMBOL",
        targets=["AAPL"],
        kind="EARNINGS",
        status="RUMOUR",
        headline="Apple said to beat",
        sentiment=0.6,
        credibility=0.5,
    )
    topic, payload = decode(frames)
    assert topic == "news.event" and payload["credibility"] == 0.5
    confirmed = decode(
        N.make_news_event(
            id="N2",
            ts_ns=6,
            scope="SYMBOL",
            targets=["AAPL"],
            kind="EARNINGS",
            status="CONFIRMED",
            headline="Apple beats",
            sentiment=0.6,
            related_id="N1",
        )
    )[1]
    assert "credibility" not in confirmed and confirmed["related_id"] == "N1"
    with pytest.raises(MessageValidationError):
        N.make_news_event(
            id="N3",
            ts_ns=1,
            scope="MARKET",
            targets=[],
            kind="MACRO",
            status="CONFIRMED",
            headline="x",
            sentiment=1.5,
        )


def test_news_command_round_trip() -> None:
    frames = G.make_sim_command(
        command_id="c",
        gateway_id="OPS01",
        action="NEWS_INJECT",
        news={
            "scope": "SECTOR",
            "targets": ["TECH"],
            "kind": "REGULATORY",
            "sentiment": -0.7,
            "impact": -0.05,
            "rumour": True,
            "credibility": 0.4,
        },
    )
    cmd = G.parse_sim_command(frames)
    assert cmd.news is not None and cmd.news.impact == -0.05 and cmd.news.headline == ""
    with pytest.raises(MessageValidationError):
        G.make_sim_command(command_id="c", gateway_id="OPS01", action="DANCE")
