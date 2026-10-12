"""pm-news: argument checks, scenarios, display."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.market_sim.news_cli import (
    NewsError,
    build_parser,
    format_event,
    load_scenario,
    news_request,
)


def test_request_shapes() -> None:
    req = news_request(symbol=["aapl"], kind="earnings", sentiment=0.5, impact=0.04)
    assert (req["scope"], req["targets"], req["kind"]) == (
        "SYMBOL",
        ["AAPL"],
        "EARNINGS",
    )
    assert "credibility" not in req
    rumour = news_request(
        sector=["TECH"],
        kind="REGULATORY",
        sentiment=-1,
        impact=-0.1,
        rumour=True,
        credibility=0.3,
    )
    assert rumour["credibility"] == 0.3 and rumour["rumour"] is True
    assert (
        news_request(market=True, kind="MACRO", sentiment=0, impact=0)["targets"] == []
    )


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({}, "exactly one"),
        ({"symbol": ["A"], "market": True}, "exactly one"),
        ({"symbol": ["A"], "credibility": 0.5}, "for rumours"),
    ],
)
def test_request_refusals(kw: dict, message: str) -> None:
    with pytest.raises(NewsError, match=message):
        news_request(kind="MACRO", sentiment=0.0, impact=0.0, **kw)


SCENARIO = """\
version: 1
steps:
  - at: {phase: CONTINUOUS, after_sec: 30}
    name: takeover
    inject: {symbol: AAPL, kind: MNA, sentiment: 0.7, impact: 0.12, rumour: true,
             credibility: 0.5}
  - at: {phase: CONTINUOUS, after_sec: 150}
    confirm: takeover
  - at: {after_sec: 5}
    inject: {market: true, kind: MACRO, sentiment: -0.4, impact: -0.02}
"""


def test_scenario_loads(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(SCENARIO)
    steps = load_scenario(path)
    assert [s.action for s in steps] == ["NEWS_INJECT", "NEWS_CONFIRM", "NEWS_INJECT"]
    assert steps[0].news is not None and steps[0].news["credibility"] == 0.5
    assert (steps[1].phase, steps[1].after_sec, steps[1].ref) == (
        "CONTINUOUS",
        150.0,
        "takeover",
    )
    assert steps[2].phase is None and steps[2].news["scope"] == "MARKET"  # type: ignore[index]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("steps: []\n", "version: 1"),
        ("version: 1\nsteps: []\n", "non-empty list"),
        ("version: 1\nsteps: [{at: {phase: LUNCH}, confirm: x}]\n", "phase must be"),
        ("version: 1\nsteps: [{confirm: x}]\n", "no earlier step 'x'"),
        ("version: 1\nsteps: [{inject: {symbol: A, kind: GOSSIP}}]\n", "kind must be"),
        (
            "version: 1\nsteps: [{inject: {symbol: A, kind: MACRO}, retract: a}]\n",
            "exactly one",
        ),
        (
            "version: 1\nsteps: [{at: {after_sec: -1}, inject: {market: true, kind: MACRO}}]\n",
            "after_sec",
        ),
        (
            "version: 1\nsteps: [{inject: {symbol: A, kind: MACRO, size: 3}}]\n",
            "inject takes",
        ),
    ],
)
def test_scenario_refusals(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(text)
    with pytest.raises(NewsError, match=message):
        load_scenario(path)


def test_parser() -> None:
    args = build_parser().parse_args(
        [
            "--id",
            "OPS01",
            "inject",
            "--symbol",
            "AAPL",
            "--symbol",
            "MSFT",
            "--kind",
            "EARNINGS",
            "--sentiment",
            "0.4",
            "--impact",
            "0.03",
            "--rumour",
        ]
    )
    assert (args.symbol, args.rumour, args.credibility) == (
        ["AAPL", "MSFT"],
        True,
        None,
    )
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "inject",
                "--symbol",
                "A",
                "--market",
                "--kind",
                "MACRO",
                "--sentiment",
                "0",
                "--impact",
                "0",
            ]
        )


def test_format_event() -> None:
    line = format_event(
        {
            "id": "N3",
            "status": "RUMOUR",
            "kind": "MNA",
            "targets": ["AAPL"],
            "sentiment": 0.7,
            "headline": "Rumour: AAPL ...",
            "credibility": 0.45,
            "related_id": "",
        }
    )
    assert "N3 RUMOUR" in line and "(credibility 45%)" in line
    assert "MARKET" in format_event(
        {
            "id": "N4",
            "status": "CONFIRMED",
            "kind": "MACRO",
            "targets": [],
            "sentiment": -0.2,
            "headline": "x",
            "related_id": "N1",
        }
    )
