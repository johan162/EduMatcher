"""tools/sim_forensics: reading the audit (seq, archives), A5 (the audit is
complete) and H5 (what the run exercised)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from compression import zstd
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
from edumatcher.models.order import OrderType, Side, SmpAction
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import order_payload
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.audit import audit_files, lines  # noqa: E402
from sim_forensics.registry import REGISTRY, Outcome  # noqa: E402

TS = "2026-10-28T07:30:00.000+00:00"


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def line(topic: str, seq: int, payload: dict[str, Any] | None = None, chain: str = "C") -> str:  # fmt: skip
    return f"[{TS}] [{topic}] [seq={seq} msg=M chain={chain}] {json.dumps(payload or {})}\n"  # fmt: skip


def write(tmp_path: Path, text: str) -> Path:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "audit.log").write_text(text)
    return data


def a5(open_ds: OpenDataset, data: Path) -> Outcome:
    return REGISTRY["A5"].fn(open_ds(data))


# --- reading ----------------------------------------------------------------


def test_lines_carry_the_seq(tmp_path: Path) -> None:
    data = write(
        tmp_path,
        line("order.new", 7)
        + f"[{TS}] [trade.executed] [seq=12] {{}}\n"
        + f"[{TS}] [order.cancel] [msg=M chain=C] {{}}\n"
        + f"[{TS}] [order.ack.G1] [seq=3 eseq=40 msg=M chain=C] {{}}\n",
    )
    got = [(ln.topic, ln.seq, ln.eseq) for ln in lines(audit_files(data))]
    assert got == [("order.new", 7, None), ("trade.executed", 12, None), ("order.cancel", None, None), ("order.ack.G1", 3, 40)]  # fmt: skip


def test_audit_files_start_with_the_daily_archives(tmp_path: Path) -> None:
    """A run that crossed midnight starts in an archive, which
    ``discover_log_files`` leaves out of the live trail."""
    data = write(tmp_path, line("order.new", 3))
    parts = data / "audit"
    parts.mkdir()
    for day, seq in (("2026-10-27", 2), ("2026-10-26", 1)):
        with zstd.open(parts / f"audit-{day}.log.zst", "wt") as fh:
            fh.write(line("order.new", seq))
    files = audit_files(data)
    assert [f.name for f in files] == ["audit-2026-10-26.log.zst", "audit-2026-10-27.log.zst", "audit.log"]  # fmt: skip
    assert [ln.seq for ln in lines(files)] == [1, 2, 3]


# --- A5 ---------------------------------------------------------------------


def start() -> str:
    return line("system.startup", 1)


def test_a5_passes_contiguous_topics(open_ds: OpenDataset, tmp_path: Path) -> None:
    tape = start() + line("order.new", 1) + line("order.ack.G1", 1) + line("order.new", 2)  # fmt: skip
    out = a5(open_ds, write(tmp_path, tape))
    assert out.violations == 0, out.samples
    assert "1 engine start(s)" in out.note and "0 messages missing" in out.note


def test_a5_counts_a_gap(open_ds: OpenDataset, tmp_path: Path) -> None:
    tape = start() + line("order.new", 1) + line("order.new", 4)
    out = a5(open_ds, write(tmp_path, tape))
    assert out.violations == 1
    assert out.samples[0] == {"error": "gap", "topic": "order.new", "after": 1, "got": 4, "missing": 2, "ts": TS}  # fmt: skip
    assert "2 messages missing" in out.note


def test_a5_a_topic_starts_at_one_after_the_engine_start(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    out = a5(open_ds, write(tmp_path, start() + line("order.new", 2)))
    assert [s["error"] for s in out.samples] == ["gap"]


def test_a5_flags_a_repeat(open_ds: OpenDataset, tmp_path: Path) -> None:
    tape = start() + line("order.new", 1) + line("order.new", 2) + line("order.new", 2)  # fmt: skip
    out = a5(open_ds, write(tmp_path, tape))
    assert [s["error"] for s in out.samples] == ["repeat or out of order"]


def test_a5_an_engine_restart_starts_every_topic_again(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    tape = start() + line("order.new", 1) + line("order.new", 2) + start() + line("order.new", 1)  # fmt: skip
    out = a5(open_ds, write(tmp_path, tape))
    assert out.violations == 0, out.samples
    assert "2 engine start(s)" in out.note


def test_a5_an_audit_without_the_start_only_sets_baselines(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    tape = line("order.new", 40) + line("order.ack.G1", 9) + line("order.new", 41)
    out = a5(open_ds, write(tmp_path, tape))
    assert out.violations == 0, out.samples
    assert "first seq per topic not checked" in out.note


def test_a5_flags_a_line_without_seq(open_ds: OpenDataset, tmp_path: Path) -> None:
    tape = start() + f"[{TS}] [order.new] [msg=M chain=C] {{}}\n"
    out = a5(open_ds, write(tmp_path, tape))
    assert [s["error"] for s in out.samples] == ["line without seq"]


class _AuditSock:
    """What pm-audit's SUB receives, written as pm-audit writes it."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> None:
        topic, payload = decode(frames)
        self.lines.append(f"[{TS}] [{topic}] [{_meta_section(frames)}] {json.dumps(payload)}\n")  # fmt: skip


def _record_engine(state: Path) -> list[str]:
    """A real Engine on s1-basic behind the real sequenced, causal PUB
    socket, started as ``Engine.run`` starts it (announce, restore, seed);
    commands go in as the engine's receive loop takes them (echo, then
    dispatch)."""
    artifact = state / "engine_config.json"
    compiled = deploy(resolve_example("s1-basic"), artifact)
    sock = _AuditSock()
    pub = CausalPublisher(SequencedPublisher(sock))
    reset_trade_ids_for_tests()
    set_run_seq(1)
    with (
        mock.patch.object(engine_main, "_deployed_config", lambda: (compiled.engine, artifact.read_text(encoding="utf-8"))),  # fmt: skip
        mock.patch.object(engine_main, "make_puller", lambda _: mock.Mock()),
        mock.patch.object(engine_main, "make_publisher", lambda _: pub),
        mock.patch.multiple(engine_main, GTC_ORDERS_FILE=state / "gtc_orders.json", GTC_COMBOS_FILE=state / "gtc_combos.json", BOOK_STATS_FILE=state / "book_stats.json"),  # fmt: skip
    ):
        engine = engine_main.Engine(config_path=None)
        engine._announce_startup(1)
        engine._restore_gtc()
        engine._load_config()
    ask = compiled.engine.symbols["AAPL"].market_maker_quotes[0].ask_price_ticks / 100

    def command(topic: str, payload: dict[str, Any]) -> None:
        env = Envelope.root()
        assert engine._echo_command(topic, encode_with_envelope(topic, payload, env))
        pub.set_cause(env)
        try:
            engine._dispatch_pull_message(topic, payload)
        finally:
            pub.clear_cause()

    command("system.gateway_connect", {"gateway_id": "TRADER01"})
    command("order.new", order_payload(Side.BUY, OrderType.LIMIT, 10, "TRADER01", price=ask))  # fmt: skip
    command("order.new", order_payload(Side.BUY, OrderType.IOC, 5, "TRADER01", price=ask, smp_action=SmpAction.CANCEL_BOTH))  # fmt: skip
    return sock.lines


def test_a5_passes_a_real_engine_recording_and_finds_a_dropped_line(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    tape = _record_engine(tmp_path / "state")
    assert tape[0].split("] [")[1] == "system.startup"
    out = a5(open_ds, write(tmp_path, "".join(tape)))
    assert out.violations == 0, out.samples

    acks = [i for i, ln in enumerate(tape) if "[order.ack.TRADER01]" in ln]
    del tape[acks[0]]
    out = a5(open_ds, write(tmp_path, "".join(tape)))
    assert [s["error"] for s in out.samples] == ["eseq gap", "gap"]
    assert out.samples[1]["topic"] == "order.ack.TRADER01"


def test_a5_eseq_finds_the_loss_of_a_topics_last_message(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    """A topic's own seq cannot show its last message missing; eseq can."""
    tape = _record_engine(tmp_path / "state")
    assert "eseq=1 " in tape[0]  # system.startup is the engine's first message
    topics = [ln.split("] [")[1] for ln in tape]
    # A topic published once, not at the very end (a lost final line has no
    # later line to show the hole).
    lone = next(i for i, t in enumerate(topics[:-1]) if i and topics.count(t) == 1)
    del tape[lone]
    out = a5(open_ds, write(tmp_path, "".join(tape)))
    assert [s["error"] for s in out.samples] == ["eseq gap"]


# --- H5 ---------------------------------------------------------------------


def h5(open_ds: OpenDataset, tmp_path: Path, *msgs: tuple[str, dict[str, Any]]) -> Outcome:  # fmt: skip
    tape = "".join(line(topic, i + 1, p) for i, (topic, p) in enumerate(msgs))
    return REGISTRY["H5"].fn(open_ds(write(tmp_path, tape)))


def new(oid: str, otype: str = "LIMIT", tif: str = "DAY", smp: str | None = None) -> tuple[str, dict[str, Any]]:  # fmt: skip
    return ("order.new", {"id": oid, "order_type": otype, "tif": tif, "smp_action": smp})  # fmt: skip


def ack(oid: str, accepted: bool = True, **extra: Any) -> tuple[str, dict[str, Any]]:
    p = {"order_id": oid, "accepted": accepted, "smp_action": "NONE", **extra}
    return ("order.ack.G1", p)


def by_key(out: Outcome) -> dict[tuple[object, ...], object]:
    return {
        (s["entry"], s["order_type"], s["tif"], s["smp_action"], s["phase"]): s["outcomes"]  # fmt: skip
        for s in out.samples
        if "entry" in s
    }


def never(out: Outcome) -> dict[str, list[str]]:
    return {
        str(s["dimension"]): list(s["never"]) for s in out.samples if "dimension" in s
    }


def test_h5_counts_orders_by_entry_type_phase_and_outcome(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    out = h5(
        open_ds,
        tmp_path,
        ("session.state", {"state": "CONTINUOUS"}),
        new("O1"), ack("O1", order_type="LIMIT", tif="DAY"),
        ("order.fill.G1", {"order_id": "O1", "remaining_qty": 5}),
        ("order.cancelled.G1", {"order_id": "O1"}),
        new("O2", "FOK", smp="CANCEL_BOTH"), ack("O2", False, reject_code="INSUFFICIENT_LIQUIDITY"),  # fmt: skip
        ("quote.new", {"quote_id": "QQ", "tif": "DAY"}),
        ("quote.ack.G1", {"quote_id": "QQ", "accepted": True, "bid_order_id": "QB", "ask_order_id": "QA"}),
        ("order.fill.G1", {"order_id": "QB", "remaining_qty": 0}),
        ("order.cancelled.G1", {"order_id": "QA"}),
        ("quote.ack.G1", {"quote_id": "QQ", "accepted": True}),  # a quote cancel's answer
        ("order.cancel", {"order_id": "O1"}),
        ack("O1", False, reject_code="ORDER_NOT_FOUND"),  # O1 had ended
        ack("S1", is_seed=True, order_type="LIMIT", tif="GTC"),
        ("order.amend", {"order_id": "S1"}),
        ack("S1", False, reject_code="ORDER_NOT_FOUND"),  # the amend's answer
        ("book.AAPL", {}),
    )  # fmt: skip
    assert by_key(out) == {
        ("ORDER", "LIMIT", "DAY", "NONE", "CONTINUOUS"): {"PARTIAL+CANCELLED": 1},
        ("ORDER", "FOK", "DAY", "?", "CONTINUOUS"): {"REJECTED": 1},
        ("QUOTE", "LIMIT", "DAY", "?", "CONTINUOUS"): {"FILLED": 1, "CANCELLED": 1},
        ("SEED", "LIMIT", "GTC", "NONE", "CONTINUOUS"): {"LIVE": 1},
    }
    assert "order.amend 1" in out.note and "quote.new 1" in out.note
    assert "explicit SMP asked: CANCEL_BOTH 1" in out.note
    assert "reject codes: INSUFFICIENT_LIQUIDITY 1;" in out.note
    assert "refused cancels/amends: ORDER_NOT_FOUND 2" in out.note


def test_h5_lists_what_the_run_never_did(open_ds: OpenDataset, tmp_path: Path) -> None:
    out = h5(open_ds, tmp_path, new("O1"), ack("O1", order_type="LIMIT", tif="DAY"))
    gaps = never(out)
    assert "MARKET" in gaps["order_type"] and "LIMIT" not in gaps["order_type"]
    assert gaps["entry"] == ["QUOTE", "OCO", "COMBO", "SEED"]
    assert "order.combo" in gaps["feature message"]
    assert gaps["smp_action (asked in order.new)"] == [s.value for s in SmpAction]
    assert out.violations == sum(len(v) for v in gaps.values())


def test_h5_is_info_in_a_run(tmp_path: Path) -> None:
    from sim_forensics.dataset import Dataset
    from sim_forensics.registry import run_checks

    data = write(tmp_path, line("order.new", 1, {"id": "O1"}))
    with Dataset.open(data) as ds:
        (result,) = run_checks(ds, [REGISTRY["H5"]], 10)
    assert result.status == "INFO"
