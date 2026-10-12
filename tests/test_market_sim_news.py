"""market_sim.news: lifecycle, rates, impacts, instructor commands."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from pathlib import Path

import pytest

from edumatcher.market_sim.config import SimConfig
from edumatcher.market_sim.main import MarketSim, load_state, save_state
from edumatcher.market_sim.model import SymbolParams
from edumatcher.market_sim.news import KINDS, NewsConfig, NewsDesk
from edumatcher.models.generated import news as N
from edumatcher.models.message import decode

TECH = SymbolParams("TECH", beta_market=0.5, beta_sector=0.4)
ENERGY = SymbolParams("ENERGY", beta_market=0.3, beta_sector=0.6)
PARAMS = {"AAPL": TECH, "MSFT": TECH, "XOM": ENERGY}
QUIET = NewsConfig(rate_symbol=0.0, rate_sector=0.0, rate_market=0.0)


def _desk(cfg: NewsConfig = QUIET, seed: int = 1) -> NewsDesk:
    return NewsDesk(PARAMS, cfg, seed)


def _publish(desk: NewsDesk, **kw: object) -> tuple[dict, dict]:
    args = dict(
        scope="SYMBOL",
        targets=["AAPL"],
        kind="EARNINGS",
        sentiment=0.8,
        impact=0.10,
        headline="",
        rumour=False,
        credibility=None,
        now=1.0,
    )
    args.update(kw)
    return desk.publish(**args)  # type: ignore[arg-type]


def test_confirmed_news_moves_at_once_and_goes_on_the_wire() -> None:
    event, moves = _publish(_desk())
    assert moves == {"AAPL": 0.10}
    assert (event["status"], event["id"], event["credibility"]) == (
        "CONFIRMED",
        "N1",
        None,
    )
    assert event["headline"] == "AAPL beats earnings expectations"
    N.make_news_event(**event)  # valid on the wire
    assert "impact" not in event  # the secret stays here


def test_rumour_then_confirm_or_retract() -> None:
    desk = _desk()
    rumour, moves = _publish(desk, rumour=True, credibility=0.7)
    assert moves == {} and rumour["status"] == "RUMOUR" and rumour["credibility"] == 0.7
    assert rumour["headline"].startswith("Rumour: ")
    confirmed = desk.resolve(rumour["id"], True, 2.0)
    assert confirmed is not None
    event, moves = confirmed
    assert (event["status"], event["related_id"], moves) == (
        "CONFIRMED",
        "N1",
        {"AAPL": 0.10},
    )
    assert not event["headline"].startswith("Rumour")
    other, _ = _publish(desk, rumour=True)
    retracted = desk.resolve(other["id"], False, 3.0)
    assert retracted is not None and retracted[1] == {}
    assert retracted[0]["status"] == "RETRACTED"
    assert retracted[0]["headline"].startswith("Retracted: ")
    assert desk.resolve("N99", True, 4.0) is None


def test_sector_and_market_news_are_beta_weighted() -> None:
    desk = _desk()
    assert desk.moves("SECTOR", ["TECH"], 0.05) == {
        "AAPL": pytest.approx(0.02),
        "MSFT": pytest.approx(0.02),
    }
    market = desk.moves("MARKET", [], -0.02)
    assert market["XOM"] == pytest.approx(-0.006) and market["AAPL"] == pytest.approx(
        -0.01
    )
    assert (
        _publish(
            desk, scope="SECTOR", targets=["TECH"], kind="REGULATORY", sentiment=-0.5
        )[0]["headline"]
        == "Regulator opens an investigation into Tech stocks"
    )


def test_generated_rates_kinds_and_resolution() -> None:
    cfg = NewsConfig(
        rate_symbol=6.0, rate_sector=0.5, rate_market=0.3, rumour_share=0.3
    )
    desk = _desk(cfg, seed=7)
    days, dt = 400, 1 / 390  # 400 trading days of one-minute steps
    events = []
    for i in range(int(days / dt)):
        events += [e for e, _ in desk.tick(dt, float(i))]
    first = [e for e in events if not e["related_id"]]
    by_scope = Counter(e["scope"] for e in first)
    for scope, rate in (("SYMBOL", 6.0), ("SECTOR", 0.5), ("MARKET", 0.3)):
        expected = rate * days
        assert abs(by_scope[scope] - expected) < 3 * math.sqrt(expected), scope
    assert {e["kind"] for e in first if e["scope"] == "MARKET"} == {"MACRO"}
    sym_kinds = Counter(e["kind"] for e in first if e["scope"] == "SYMBOL")
    assert sym_kinds["EARNINGS"] > sym_kinds["MNA"]  # weights 4 vs 0.5
    rumours = [e for e in first if e["status"] == "RUMOUR"]
    assert 0.25 < len(rumours) / len(first) < 0.35
    resolved = {e["related_id"] for e in events if e["related_id"]}
    assert len({r["id"] for r in rumours} - resolved) == len(desk.rumours) <= 2


def test_generated_impacts_follow_their_kind() -> None:
    desk = _desk(seed=3)
    moves = [desk._generate("SYMBOL", 0.0)[1] for _ in range(4000)]
    impacts = [m for mv in moves for m in mv.values()]  # rumours move nothing yet
    sd = statistics.pstdev(impacts)
    assert 0.02 < sd < 0.06  # a mixture of the symbol kinds' spreads
    assert {k for k, p in KINDS.items() if "SYMBOL" in p.scopes} >= {"EARNINGS", "MNA"}


def test_sentiment_has_the_sign_of_the_impact_mostly() -> None:
    desk = _desk(NewsConfig(rumour_share=0.0), seed=5)
    agree = 0
    for _ in range(2000):
        event, moves = desk._generate("SYMBOL", 0.0)
        (impact,) = moves.values()
        agree += (event["sentiment"] > 0) == (impact > 0)
    assert agree / 2000 > 0.85


def _sim() -> MarketSim:
    cfg = SimConfig(1, 1.0, 0.2, dict(PARAMS), {}, QUIET)
    return MarketSim(cfg, {s: 100.0 for s in PARAMS}, admins=frozenset({"OPS01"}))


def _cmd(sim: MarketSim, **payload: object) -> list[tuple[str, dict]]:
    payload = {"gateway_id": "OPS01", "command_id": "c", **payload}
    return [decode(f) for f in sim.command(payload, 5.0)]


def test_inject_confirm_retract_commands() -> None:
    sim = _sim()
    news = {
        "scope": "SYMBOL",
        "targets": ["aapl"],
        "kind": "EARNINGS",
        "sentiment": 0.9,
        "impact": math.log(1.1),
        "headline": "Apple smashes estimates",
    }
    (topic, event), (_, ack) = _cmd(sim, action="NEWS_INJECT", news=news)
    assert topic == "news.event" and event["headline"] == "Apple smashes estimates"
    assert ack["accepted"] and ack["news_id"] == event["id"]
    assert sim.model.value("AAPL") == pytest.approx(110.0)
    (_, rumour), _ = _cmd(
        sim, action="NEWS_INJECT", news={**news, "rumour": True, "credibility": 0.4}
    )
    assert rumour["status"] == "RUMOUR" and sim.model.value("AAPL") == pytest.approx(
        110.0
    )
    assert sim.news.rumours[rumour["id"]].remaining is None  # waits for the instructor
    (_, confirmed), (_, ack) = _cmd(sim, action="NEWS_CONFIRM", news_id=rumour["id"])
    assert confirmed["related_id"] == rumour["id"] and sim.model.value(
        "AAPL"
    ) == pytest.approx(121.0)
    ((_, refused),) = _cmd(sim, action="NEWS_RETRACT", news_id=rumour["id"])
    assert not refused["accepted"] and "no open rumour" in refused["reason"]


@pytest.mark.parametrize(
    ("news", "reason"),
    [
        ({"scope": "SYMBOL", "targets": ["NOPE"]}, "unknown symbol(s): NOPE"),
        ({"scope": "SECTOR", "targets": []}, "needs targets"),
        ({"scope": "MARKET", "targets": ["AAPL"]}, "names no targets"),
        ({"scope": "SECTOR", "targets": ["CANDY"]}, "unknown sector(s): CANDY"),
    ],
)
def test_bad_injections_are_refused(news: dict, reason: str) -> None:
    payload = {"kind": "MACRO", "sentiment": 0.0, "impact": 0.0, **news}
    ((_, ack),) = _cmd(_sim(), action="NEWS_INJECT", news=payload)
    assert not ack["accepted"] and reason in ack["reason"]


def test_open_rumours_survive_a_restart(tmp_path: Path) -> None:
    sim = _sim()
    news = {
        "scope": "SYMBOL",
        "targets": ["XOM"],
        "kind": "MNA",
        "sentiment": 0.5,
        "impact": 0.2,
        "rumour": True,
    }
    (_, rumour), _ = _cmd(sim, action="NEWS_INJECT", news=news)
    path = tmp_path / "state.json"
    save_state(path, sim.saved())
    saved = load_state(path)
    assert saved is not None
    again = MarketSim(
        sim.cfg,
        saved.values,
        seq=saved.seq,
        epoch=1,
        admins=frozenset({"OPS01"}),
        news_seq=saved.news_seq,
        rumours=saved.rumours,
    )
    before = again.model.value("XOM")
    (_, confirmed), _ = [
        decode(f)
        for f in again.command(
            {
                "gateway_id": "OPS01",
                "command_id": "x",
                "action": "NEWS_CONFIRM",
                "news_id": rumour["id"],
            },
            9.0,
        )
    ]
    assert confirmed["id"] == "N2"  # numbering continues
    assert again.model.value("XOM") == pytest.approx(before * math.exp(0.2))
