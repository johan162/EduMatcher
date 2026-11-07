"""tools/sim_forensics checks E5-E7: the audit's commands re-run beside the
reference re-run under changes that must make no difference.

The checks read only the commands an audit holds, so each test writes a
startup line and commands: a small day on the s3-basic example (three
symbols, seeded quotes) with crossing and resting orders, an iceberg, stops,
a trailing stop, an OCO, a quote replacement, IOC, FOK and cancels. A test
then plants an engine fault of the kind each check exists to find.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.engine.circuit_breaker import CircuitBreakerState
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import order_payload
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.checks import differential  # noqa: E402
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402

import edumatcher.engine.main as engine_main

E = ["E5", "E6", "E7"]


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def _day(config: EngineConfig) -> list[tuple[str, dict[str, Any]]]:
    """Each symbol's commands, interleaved round-robin."""
    per_symbol = [_symbol_day(sym, cfg) for sym, cfg in config.symbols.items()]
    cmds: list[tuple[str, dict[str, Any]]] = [
        ("system.gateway_connect", {"gateway_id": gw})
        for gw in ("TRADER01", "TRADER02", "MM01")
    ]
    for i in range(max(len(c) for c in per_symbol)):
        cmds += [c[i] for c in per_symbol if i < len(c)]
    return cmds


def _symbol_day(sym: str, cfg: Any) -> list[tuple[str, dict[str, Any]]]:
    """Crossing and resting orders, an iceberg, stops, an OCO, a quote
    replacement, IOC, FOK, a cancel and a MARKET order on *sym*."""
    cmds: list[tuple[str, dict[str, Any]]] = []
    seed = cfg.market_maker_quotes[0]
    bid, ask = seed.bid_price_ticks / 100, seed.ask_price_ticks / 100

    def new(side: Side, kind: OrderType, qty: int, gw: str, **kw: Any) -> dict[str, Any]:  # fmt: skip
        p = order_payload(side, kind, qty, gw, symbol=sym, **kw)
        cmds.append(("order.new", p))
        return p

    new(Side.SELL, OrderType.ICEBERG, 300, "TRADER02", price=ask - 0.05, visible_qty=50)  # fmt: skip
    rest = new(Side.SELL, OrderType.LIMIT, 40, "TRADER02", price=ask - 0.05)
    new(Side.BUY, OrderType.STOP, 30, "TRADER02", stop_price=ask + 0.05)
    new(Side.SELL, OrderType.TRAILING_STOP, 20, "TRADER01", stop_price=bid - 0.5, trail_offset=0.3)  # fmt: skip
    new(Side.BUY, OrderType.LIMIT, 120, "TRADER01", price=ask - 0.05)
    new(Side.BUY, OrderType.IOC, 500, "TRADER01", price=ask)
    new(Side.BUY, OrderType.FOK, 5000, "TRADER01", price=ask)
    new(Side.BUY, OrderType.LIMIT, 50, "TRADER01", price=ask + 0.10)
    cmds.append(("order.cancel", {"order_id": rest["id"], "gateway_id": "TRADER02"}))  # fmt: skip
    cmds.append(
        ("order.oco", {"oco_id": f"K-{sym}", "gateway_id": "TRADER01", "symbol": sym, "quantity": 5, "tif": "DAY", "tick_decimals": 2,  # fmt: skip
                       "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": seed.ask_price_ticks + 200},  # fmt: skip
                       "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": seed.bid_price_ticks - 200}})  # fmt: skip
    )
    for n, shift in ((1, 0), (2, 3)):
        cmds.append(
            ("quote.new", {"gateway_id": "MM01", "symbol": sym, "tick_decimals": 2, "quote_id": f"Q{n}-{sym}", "tif": "DAY",  # fmt: skip
                           "bid_price_ticks": seed.bid_price_ticks - 30 + shift, "bid_qty": 100,  # fmt: skip
                           "ask_price_ticks": seed.ask_price_ticks + 30 + shift, "ask_qty": 100})  # fmt: skip
        )
    new(Side.SELL, OrderType.MARKET, 60, "TRADER02")
    return cmds


def write_day(data: Path, example: str = "s3-basic") -> Path:
    data.mkdir()
    artifact = data.parent / "deployed" / "engine_config.json"
    compiled = deploy(resolve_example(example), artifact)
    startup = {"run_seq": 1, "config": artifact.read_text(encoding="utf-8")}
    lines = [f"[2026-10-28T07:00:00.000+00:00] [system.startup] [seq=1 msg=M0 chain=M0] {json.dumps(startup)}\n"]  # fmt: skip
    for i, (topic, p) in enumerate(_day(compiled.engine), 1):
        lines.append(f"[2026-10-28T07:00:{i % 60:02d}.000+00:00] [{topic}] [seq={i} msg=M{i} chain=M{i}] {json.dumps(p)}\n")  # fmt: skip
    (data / "audit.log").write_text("".join(lines))
    return data


def outcomes(open_ds: OpenDataset, data: Path) -> dict[str, Outcome]:
    ds = open_ds(data)
    return {i: REGISTRY[i].fn(ds) for i in E}


def run_e(open_ds: OpenDataset, data: Path, every: int = 7, span: int = 5) -> dict[str, Outcome]:  # fmt: skip
    with mock.patch.multiple(differential, _E6_EVERY=every, _E6_SPAN=span):
        return outcomes(open_ds, data)


def errors(out: Outcome) -> set[object]:
    return {s.get("error") for s in out.samples}


def test_e5_and_e7_pass_on_a_day(tmp_path: Path, open_ds: OpenDataset) -> None:
    out = run_e(open_ds, write_day(tmp_path / "data"))
    assert {i: (out[i].violations, out[i].samples) for i in ("E5", "E7")} == {"E5": (0, []), "E7": (0, [])}  # fmt: skip
    assert out["E5"].note == "42 commands, 3 symbols"
    assert out["E7"].note == "42 commands; transforms: rename, price shift"


def test_e6_passes_on_a_day_and_skips_a_designed_reseed(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """Restarts with live OCO pairs, after trades, with a refilled iceberg
    (X23-X26, fixed in S20b). Where the MM's quote is gone at a restart the
    restored engine seeds it again (seed_once, by design): not a finding."""
    out = run_e(open_ds, write_day(tmp_path / "data"), every=10)["E6"]
    assert out.samples == []
    assert out.note == "4 restarts, every 10 commands, each compared for 5; 8 books re-seeded at a restart (by design) not compared"  # fmt: skip


def _dropping(condition: Any) -> Any:
    """Engine._handle_new_order that ignores the orders *condition* picks."""
    handle = engine_main.Engine._handle_new_order

    def wrapper(self: engine_main.Engine, payload: dict[str, Any]) -> None:
        if not condition(self, payload):
            handle(self, payload)

    return mock.patch.object(engine_main.Engine, "_handle_new_order", wrapper)


def test_e5_finds_state_shared_between_symbols(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """Every third order the engine takes in, whatever its symbol, is lost."""

    def third(self: Any, payload: dict[str, Any]) -> bool:
        self._planted = getattr(self, "_planted", 0) + 1
        return bool(self._planted % 3 == 0)

    data = write_day(tmp_path / "data")
    with _dropping(third):
        out = run_e(open_ds, data)["E5"]
    assert out.violations == 3  # one per symbol
    assert {s["symbol"] for s in out.samples} == {"AAPL", "MSFT", "TSLA"}


def test_e6_finds_a_field_the_checkpoint_drops(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    resting = engine_main.Engine._resting_gtc_orders

    def no_trailing(self: engine_main.Engine) -> list[Any]:
        return [o for o in resting(self) if o.order_type != OrderType.TRAILING_STOP]

    data = write_day(tmp_path / "data")
    with mock.patch.object(engine_main.Engine, "_resting_gtc_orders", no_trailing):
        out = run_e(open_ds, data)["E6"]
    assert "restored trailing stops differ" in errors(out)


@pytest.mark.parametrize(
    "transform, condition",
    [
        ("rename", lambda self, p: p["id"][0] < "8"),
        ("price shift", lambda self, p: (p.get("price_ticks") or 1) % 2 == 0),
    ],
)
def test_e7_finds_a_dependence_on_ids_or_price_level(
    tmp_path: Path, open_ds: OpenDataset, transform: str, condition: Any
) -> None:
    data = write_day(tmp_path / "data")
    with _dropping(condition):
        out = run_e(open_ds, data)["E7"]
    assert out.violations
    assert {s["transform"] for s in out.samples} == {transform}


def test_e5_to_e7_are_slow(tmp_path: Path, open_ds: OpenDataset) -> None:
    data = write_day(tmp_path / "data")
    results = run_checks(open_ds(data), [REGISTRY[i] for i in E], 10)
    assert {r.status for r in results} == {"SKIPPED"}
    assert results[0].note.startswith("slow:")


def test_e6_finds_a_breaker_window_the_checkpoint_drops(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """A restarted breaker seeded afresh averages other trades than the
    uninterrupted one's window (2026-11-07 run: EA, NET); s3-complex has
    breakers."""
    data = write_day(tmp_path / "data", "s3-complex")
    assert run_e(open_ds, data, every=10)["E6"].samples == []
    with mock.patch.object(CircuitBreakerState, "restore_window", lambda self, trades, ref: None):  # fmt: skip
        out = run_e(open_ds, data, every=10)["E6"]
    assert "restored breaker window differ" in errors(out)


def test_e6_leaves_out_a_combo_on_a_reseeded_book(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """An all-or-none combo decides on all its legs at once: one leg on a
    book re-seeded at the restart makes every leg's book differ (the
    2026-11-07 run's E6 findings)."""
    data = write_day(tmp_path / "data")
    combo = {"combo_id": "CB1", "gateway_id": "TRADER01", "combo_type": "AON", "tif": "DAY",  # fmt: skip
             "legs": [{"symbol": s, "side": "BUY", "order_type": "LIMIT", "quantity": 10, "tick_decimals": 2, "price_ticks": 100}  # fmt: skip
                      for s in ("AAPL", "MSFT", "TSLA")]}  # fmt: skip
    log = data / "audit.log"
    log.write_text(log.read_text() + f"[2026-10-28T07:01:00.000+00:00] [order.combo] [seq=99 msg=M99 chain=M99] {json.dumps(combo)}\n")  # fmt: skip
    out = run_e(open_ds, data, every=40)["E6"]
    assert out.samples == []
    assert "combos with a leg on a differing book not compared: 1" in out.note


def test_e7_rename_maps_each_quoted_prefix_back_to_its_own_id() -> None:
    """Two ids whose first renames share 8 characters, and an engine-made id
    sharing a renamed id's 8 characters, each map back to themselves."""
    r = differential._Rename(mock.Mock(participants={}))
    a, b = "b63a9cb5d9cd025826d518de83521e51", "5376df1d80677712ca839e0a8d6f360f"
    ra, rb = r._id(a), r._id(b)
    assert ra[:8] != rb[:8] and r._id(b) == rb
    assert r.output("t", {"reason": f"{ra[:8]} {rb[:8]}"})[1] == {"reason": f"{a[:8]} {b[:8]}"}  # fmt: skip
    made = ra[:8] + "0" * 24  # an OCO leg the renamed engine numbered
    r.output("oco.ack.X", {"order_id_1": made})
    assert r.output("t", {"reason": f"OCO sibling {made[:8]}"})[1] == {"reason": f"OCO sibling {made[:8]}"}  # fmt: skip


def test_snapped_equates_floats_a_decimal_apart_only() -> None:
    """E7: a VWAP on a 9-decimal rounding boundary rounds either way."""
    ref = {"fill_price": 79.380351563, "price": 1.0, "qty": 5}
    near = {"fill_price": 79.380351562, "price": 1.0, "qty": 5}
    far = {"fill_price": 79.38035156, "price": 1.0, "qty": 5}
    assert differential._snapped(near, ref) == ref
    assert differential._snapped(far, ref) == far
