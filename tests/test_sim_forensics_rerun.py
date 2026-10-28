"""tools/sim_forensics checks E (re-run the audit's commands through an engine).

The "live run" here is a real Engine driven by the test, whose every
published message is written to audit.log the way pm-audit writes it, with
each command echoed first, as Engine._echo_command does. The checks must find
that recording consistent; each failure test then edits one line of it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.models.message import decode
from edumatcher.models.order import OrderType, Side
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import order_payload
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, run_checks  # noqa: E402

E = ["E1", "E2", "E4"]


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


class Recorder:
    """The engine's PUB socket during the recorded run: audit lines out."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.n = 0
        self.chain: str | None = None

    def _line(self, topic: str, msg: str, chain: str, payload: Any) -> None:
        self.lines.append(
            f"[2026-10-24T07:00:00.000+00:00] [{topic}] "
            f"[seq={self.n} msg={msg} chain={chain}] {json.dumps(payload)}\n"
        )

    def _msg(self) -> str:
        self.n += 1
        return f"{self.n:026d}"

    def send_multipart(self, frames: list[bytes]) -> None:
        topic, payload = decode(frames)
        msg = self._msg()
        self._line(topic, msg, self.chain or msg, payload)

    def send_with_envelope(self, frames: list[bytes], envelope: bytes) -> None:
        pass

    def set_cause(self, envelope: object | None) -> None:
        pass

    def clear_cause(self) -> None:
        pass

    def close(self) -> None:
        pass

    def command(self, engine: Any, topic: str, payload: dict[str, Any]) -> None:
        msg = self._msg()
        self._line(topic, msg, msg, payload)
        self.chain = msg
        engine._dispatch_pull_message(topic, payload)
        self.chain = None


def record(data: Path) -> Path:
    """A short run on the s1-basic example: seeds, connects, a crossing buy
    against the seed ask, a resting sell, a cancel, an MM quote, an OCO."""
    (data / "ref_data").mkdir(parents=True)
    compiled = deploy(
        resolve_example("s1-basic"), data / "ref_data" / "engine_config.json"
    )
    seed = compiled.engine.symbols["AAPL"].market_maker_quotes[0]
    ask = seed.ask_price_ticks / 100
    reset_trade_ids_for_tests()
    set_run_seq(1)
    rec = Recorder()
    with (
        mock.patch.object(
            engine_main, "_compiled_engine_config", lambda: compiled.engine
        ),
        mock.patch.object(engine_main, "make_puller", lambda _: Recorder()),
        mock.patch.object(engine_main, "make_publisher", lambda _: rec),
        mock.patch.object(engine_main, "load_gtc_orders", lambda _: []),
        mock.patch.object(engine_main, "load_book_stats", lambda _: {}),
    ):
        engine = engine_main.Engine(config_path=None)
        engine._restore_gtc()
        engine._load_config()
    for gw in ("TRADER01", "TRADER02", "MM01"):
        rec.command(engine, "system.gateway_connect", {"gateway_id": gw})
    buy = order_payload(Side.BUY, OrderType.LIMIT, 10, "TRADER01", price=ask)
    rec.command(engine, "order.new", buy)
    rest = order_payload(Side.SELL, OrderType.LIMIT, 5, "TRADER02", price=ask + 5)
    rec.command(engine, "order.new", rest)
    rec.command(
        engine, "order.cancel", {"order_id": rest["id"], "gateway_id": "TRADER02"}
    )
    rec.command(
        engine,
        "quote.new",
        {
            "gateway_id": "MM01",
            "symbol": "AAPL",
            "tick_decimals": 2,
            "bid_price_ticks": seed.bid_price_ticks - 10,
            "bid_qty": 100,
            "ask_price_ticks": seed.ask_price_ticks + 10,
            "ask_qty": 100,
            "tif": "DAY",
            "quote_id": "Q1",
        },
    )
    rec.command(
        engine,
        "order.oco",
        {
            "oco_id": "K1",
            "gateway_id": "TRADER01",
            "symbol": "AAPL",
            "quantity": 5,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": {
                "side": "SELL",
                "order_type": "LIMIT",
                "price_ticks": seed.ask_price_ticks + 500,
            },
            "leg2": {
                "side": "SELL",
                "order_type": "STOP",
                "stop_price_ticks": seed.bid_price_ticks - 500,
            },
        },
    )
    (data / "audit.log").write_text("".join(rec.lines))
    resting = [o.to_dict() for b in engine.books.values() for o in b.resting_orders()]
    (data / "gtc_orders.json").write_text(json.dumps(resting))
    return data


def edit(data: Path, find: str, change: Any) -> None:
    """Rewrite the first audit line containing *find* with *change*."""
    path = data / "audit.log"
    lines = path.read_text().splitlines(keepends=True)
    i = next(k for k, ln in enumerate(lines) if find in ln)
    lines[i : i + 1] = change(lines[i])
    path.write_text("".join(lines))


def statuses(open_ds: OpenDataset, data: Path) -> dict[str, tuple[str, int]]:
    results = run_checks(open_ds(data), [REGISTRY[i] for i in E], 10)
    return {r.check.id: (r.status, r.violations) for r in results}


def test_every_e_check_passes_on_a_recorded_run(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    # The slow E5-E7: tests/test_sim_forensics_differential.py.
    assert sorted(i for i in REGISTRY if i[0] == "E" and not REGISTRY[i].slow) == E
    data = record(tmp_path / "data")
    assert statuses(open_ds, data) == {i: ("PASS", 0) for i in E}
    note = REGISTRY["E1"].fn(open_ds(data)).note
    assert note.startswith("8 commands (")


def test_e2_finds_an_output_the_engine_would_not_publish(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = record(tmp_path / "data")
    edit(
        data,
        "[trade.executed]",
        lambda ln: [ln.replace('"quantity": 10', '"quantity": 9')],
    )
    out = REGISTRY["E2"].fn(open_ds(data))
    assert out.violations == 1
    assert out.samples[0]["diffs"] == ["trade.executed.quantity: 10 != 9"]


def test_e1_finds_a_state_change_no_command_caused(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """A cancel published outside any command's chain: a hidden input."""
    data = record(tmp_path / "data")
    edit(
        data,
        "[order.oco]",
        lambda ln: [
            "[2026-10-24T07:00:00.000+00:00] [order.cancelled.TRADER02] "
            '[seq=1 msg=X chain=X] {"order_id": "x", "symbol": "AAPL"}\n',
            ln,
        ],
    )
    assert statuses(open_ds, data) == {
        "E1": ("FAIL", 1),
        "E2": ("PASS", 0),
        "E4": ("PASS", 0),
    }


def test_e4_finds_a_persisted_book_the_rerun_does_not_end_with(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = record(tmp_path / "data")
    path = data / "gtc_orders.json"
    orders = json.loads(path.read_text())
    orders[0]["remaining_qty"] += 1
    path.write_text(json.dumps(orders))
    out = REGISTRY["E4"].fn(open_ds(data))
    assert [(s["persisted"], s["rerun"]) for s in out.samples] == [
        (orders[0]["remaining_qty"], orders[0]["remaining_qty"] - 1)
    ]


def test_the_e_checks_skip_without_the_engine_start(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[system.startup_recovery]", lambda ln: [])
    results = run_checks(open_ds(data), [REGISTRY[i] for i in E], 10)
    assert {r.status for r in results} == {"SKIPPED"}
