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
from edumatcher.config_artifact import decode as decode_artifact
from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.models.message import decode
from edumatcher.models.order import OrderType, Side
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import order_payload
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.audit import audit_files, run_config_text  # noqa: E402
from sim_forensics.checks.rerun import (  # noqa: E402
    BREAKER_TIMER,
    _Sink,
    apply,
    fresh_engine,
    inputs,
    live_clock,
)
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
        self.unit_chain: str | None = None

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
        if self.unit_chain == "":
            self.unit_chain = msg
        self._line(topic, msg, self.chain or self.unit_chain or msg, payload)

    def send_with_envelope(self, frames: list[bytes], envelope: bytes) -> None:
        pass

    def set_cause(self, envelope: object | None) -> None:
        pass

    def clear_cause(self) -> None:
        pass

    def begin_unit(self) -> None:
        """Messages until end_unit share the first one's chain, as the
        real CausalPublisher's do."""
        self.unit_chain = ""

    def end_unit(self) -> None:
        self.unit_chain = None

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
    against the seed ask, a resting sell, a cancel, an MM quote, an OCO.

    The config is deployed outside *data*: the checks take it from the
    audit's system.startup, as a run's own ref_data/ may be gone."""
    data.mkdir(parents=True)
    artifact = data.parent / "deployed" / "engine_config.json"
    compiled = deploy(resolve_example("s1-basic"), artifact)
    seed = compiled.engine.symbols["AAPL"].market_maker_quotes[0]
    ask = seed.ask_price_ticks / 100
    reset_trade_ids_for_tests()
    set_run_seq(1)
    rec = Recorder()
    with (
        mock.patch.object(
            engine_main,
            "_deployed_config",
            lambda: (compiled.engine, artifact.read_text(encoding="utf-8")),
        ),
        mock.patch.object(engine_main, "make_puller", lambda _: Recorder()),
        mock.patch.object(engine_main, "make_publisher", lambda _: rec),
        mock.patch.multiple(
            engine_main,
            GTC_ORDERS_FILE=data / "gtc_orders.json",
            GTC_COMBOS_FILE=data / "gtc_combos.json",
            BOOK_STATS_FILE=data / "book_stats.json",
        ),
    ):
        engine = engine_main.Engine(config_path=None)
        engine._startup(1)
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
    assert not (data / "ref_data").exists()  # the config comes from the audit
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


def test_the_rerun_engine_trades_on_the_live_clock(tmp_path: Path) -> None:
    """The breaker's reference window counts trades by their ts_ns: a re-run
    on its own clock (hours in minutes) halted where the live run did not
    (2026-10-29 run: 24 halts)."""
    data = record(tmp_path / "data")
    files = audit_files(data)
    config = decode_artifact(run_config_text(files)).engine
    live_ts: list[int] = []
    rerun_ts: list[int] = []
    reset_trade_ids_for_tests()
    set_run_seq(1)
    sink = _Sink()
    with live_clock(files) as clock:
        engine = fresh_engine(config, sink, tmp_path / "empty")
        sink.take()
        for topic, _chain, payload, live, _ts in inputs(files):
            if topic is None or topic == "startup" or topic.startswith("book."):
                continue
            clock.follow(live)
            apply(engine, topic, payload)
            live_ts += [p["ts_ns"] for t, p in live if t == "trade.executed"]
            rerun_ts += [p["ts_ns"] for t, p in sink.take() if t == "trade.executed"]
    assert live_ts and rerun_ts == live_ts


def test_a_breaker_timer_fires_only_its_own_symbol() -> None:
    """On the live clock another halted symbol may be due too (2026-10-29
    run: 6); the live engine reopened each by its own timer input."""
    from edumatcher.engine.circuit_breaker import (
        CircuitBreakerConfig,
        CircuitBreakerState,
    )

    class _Engine:
        def __init__(self) -> None:
            self._circuit_breakers = {
                s: CircuitBreakerState(s, CircuitBreakerConfig(s), halted=True, resume_at_ns=5)  # fmt: skip
                for s in ("AAPL", "MSFT")
            }
            self.fired: list[str] = []

        def _flush_circuit_breakers(self) -> None:
            self.fired = [s for s, cb in self._circuit_breakers.items() if cb.should_resume(10)]  # fmt: skip

    engine = _Engine()
    apply(engine, BREAKER_TIMER, {"symbol": "AAPL"})  # type: ignore[arg-type]
    assert engine.fired == ["AAPL"]
    assert engine._circuit_breakers["MSFT"].resume_at_ns == 5


def test_the_e_checks_skip_without_the_engine_start(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[system.startup]", lambda ln: [])
    results = run_checks(open_ds(data), [REGISTRY[i] for i in E], 10)
    assert {r.status for r in results} == {"SKIPPED"}
