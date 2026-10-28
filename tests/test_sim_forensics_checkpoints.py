"""Book checkpoints (S25): the engine publishes every book after startup,
after each session transition and at shutdown; the matching replay compares
itself with them (D9, order by order) and can start from one -- an audit
that begins mid-day, or continues across an engine restart.

The audits here are recorded from real engines on s3-basic behind the real
sequenced, causal PUB socket, written as pm-audit writes lines.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.audit.main import _meta_section
from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.messaging.bus import CausalPublisher, SequencedPublisher
from edumatcher.models.envelope import Envelope
from edumatcher.models.message import decode, encode_with_envelope
from edumatcher.models.order import OrderType, Side
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import order_payload
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402

TS = "2026-10-28T07:30:00.000+00:00"
D = ["C7", "D1", "D10", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
CHECKPOINT = "[system.book_checkpoint."


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


class _AuditSock:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> None:
        topic, payload = decode(frames)
        self.lines.append(f"[{TS}] [{topic}] [{_meta_section(frames)}] {json.dumps(payload)}\n")  # fmt: skip


class Run:
    """Real engines recorded into one audit; *state* holds their files."""

    def __init__(self, root: Path) -> None:
        self.state = root / "state"
        self.state.mkdir(parents=True)
        artifact = root / "deployed" / "engine_config.json"
        self.compiled = deploy(resolve_example("s3-basic"), artifact)
        self.text = artifact.read_text(encoding="utf-8")
        self.lines: list[str] = []
        reset_trade_ids_for_tests()
        set_run_seq(1)

    def start(self, run_seq: int) -> engine_main.Engine:
        pub = CausalPublisher(SequencedPublisher(_AuditSock(self.lines)))
        with (
            mock.patch.object(engine_main, "_deployed_config", lambda: (self.compiled.engine, self.text)),  # fmt: skip
            mock.patch.object(engine_main, "make_puller", lambda _: mock.Mock()),
            mock.patch.object(engine_main, "make_publisher", lambda _: pub),
            mock.patch.multiple(engine_main, GTC_ORDERS_FILE=self.state / "gtc_orders.json", GTC_COMBOS_FILE=self.state / "gtc_combos.json", BOOK_STATS_FILE=self.state / "book_stats.json"),  # fmt: skip
        ):
            e = engine_main.Engine(config_path=None)
            e._startup(run_seq)
        self.engine, self.pub = e, pub
        for gw in ("TRADER01", "TRADER02"):
            self.command("system.gateway_connect", {"gateway_id": gw})
        return e

    def command(self, topic: str, payload: dict[str, Any]) -> None:
        env = Envelope.root()
        self.engine._echo_command(topic, encode_with_envelope(topic, payload, env))
        self.pub.set_cause(env)
        try:
            self.engine._dispatch_pull_message(topic, payload)
        finally:
            self.pub.clear_cause()

    def trade_a_while(self, base: float) -> None:
        """Resting orders, an iceberg that refills, stops that arm and fire,
        a trailing stop that ratchets, crossing orders on both symbols."""
        for sym in ("AAPL", "MSFT"):
            def new(side: Side, kind: OrderType, qty: int, gw: str, **kw: Any) -> None:  # fmt: skip
                self.command("order.new", order_payload(side, kind, qty, gw, symbol=sym, **kw))  # fmt: skip

            new(Side.SELL, OrderType.ICEBERG, 60, "TRADER02", price=base + 1, visible_qty=10)  # fmt: skip
            new(Side.SELL, OrderType.LIMIT, 20, "TRADER02", price=base + 1.5)
            new(Side.BUY, OrderType.STOP, 5, "TRADER01", stop_price=base + 1)
            new(Side.SELL, OrderType.TRAILING_STOP, 5, "TRADER01", stop_price=base - 5, trail_offset=2.0)  # fmt: skip
            new(Side.BUY, OrderType.LIMIT, 15, "TRADER01", price=base + 1)
            new(Side.BUY, OrderType.LIMIT, 8, "TRADER01", price=base - 3)

    def restart(self, run_seq: int) -> engine_main.Engine:
        """Checkpoint as the engine does, and start a new one on the files."""
        with mock.patch.multiple(engine_main, GTC_ORDERS_FILE=self.state / "gtc_orders.json", GTC_COMBOS_FILE=self.state / "gtc_combos.json", BOOK_STATS_FILE=self.state / "book_stats.json"):  # fmt: skip
            self.engine._flush_persistence(force=True)
        return self.start(run_seq)

    def write(self, data: Path, lines: list[str] | None = None) -> Path:
        data.mkdir(parents=True, exist_ok=True)
        (data / "audit.log").write_text("".join(self.lines if lines is None else lines))
        return data


def d_checks(open_ds: OpenDataset, data: Path) -> dict[str, Outcome]:
    ds = open_ds(data)
    return {i: REGISTRY[i].fn(ds) for i in D}


def a_day(tmp_path: Path) -> Run:
    run = Run(tmp_path)
    run.start(1)
    run.trade_a_while(260.0)
    run.engine._publish_checkpoints("PHASE")  # a checkpoint mid-day
    run.trade_a_while(262.0)
    run.engine._publish_checkpoints("EOD")
    return run


def test_the_engine_checkpoints_every_book_and_the_replay_agrees(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    run = a_day(tmp_path)
    assert sum(CHECKPOINT in ln for ln in run.lines) == 3 * 3  # 3 symbols, 3 rounds
    out = d_checks(open_ds, run.write(tmp_path / "data"))
    assert {i: o.violations for i, o in out.items() if o.violations} == {}
    payloads = [json.loads("{" + ln.split("] {", 1)[1]) for ln in run.lines if CHECKPOINT in ln]  # fmt: skip
    assert any(p["trailing_stops"] for p in payloads)
    assert any(r.get("visible_qty") for p in payloads for r in p["asks"])


def test_a_replay_from_a_mid_day_checkpoint_finds_what_the_full_one_finds(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    run = a_day(tmp_path)
    first = next(i for i, ln in enumerate(run.lines) if '"reason": "PHASE"' in ln)
    cut = run.write(tmp_path / "cut", run.lines[first:])
    out = d_checks(open_ds, cut)
    assert {i: o.violations for i, o in out.items() if o.violations} == {}
    assert out["D2"].violations == 0 and "0 trades replayed" not in out["D2"].note


def test_d9_finds_a_book_the_checkpoint_does_not_hold(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    run = a_day(tmp_path)
    i = next(k for k, ln in enumerate(run.lines) if '"reason": "PHASE"' in ln and '"asks": [{' in ln)  # fmt: skip
    head, body = run.lines[i].split("] {", 1)
    p = json.loads("{" + body)
    p["asks"][0]["remaining_qty"] += 1
    run.lines[i] = f"{head}] {json.dumps(p)}\n"
    samples = d_checks(open_ds, run.write(tmp_path / "data"))["D9"].samples
    # First the checkpoint; the books built on it then differ too.
    assert samples[0]["error"] == "replayed asks differ from the engine's checkpoint"


def test_the_replay_continues_across_an_engine_restart(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """Before S25 the replay SKIPPED at a restart."""
    run = Run(tmp_path)
    run.start(1)
    run.trade_a_while(260.0)
    run.restart(2)
    run.trade_a_while(262.0)
    data = run.write(tmp_path / "data")
    results = run_checks(open_ds(data), [REGISTRY[i] for i in D], 10)
    assert {r.check.id: r.status for r in results} == {i: "PASS" for i in D}
