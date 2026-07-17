from __future__ import annotations

import argparse
from collections.abc import Generator
from pathlib import Path
import time
from typing import Any

import pytest

import edumatcher.index.main as index_main
from edumatcher.index.config_loader import IndexRuntimeConfig
from edumatcher.models.message import decode


class _FakeSocket:
    def __init__(self) -> None:
        self.inbound: list[list[bytes]] = []
        self.sent: list[list[bytes]] = []
        self.closed = False

    def poll(self, timeout: int = 0) -> bool:
        _ = timeout
        return bool(self.inbound)

    def recv_multipart(self) -> list[bytes]:
        return self.inbound.pop(0)

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def proc_with_fakes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[index_main.IndexProcess, _FakeSocket], None, None]:
    fake_sub = _FakeSocket()
    fake_pull = _FakeSocket()
    fake_pub = _FakeSocket()

    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: fake_sub)
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: fake_pull)
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: fake_pub)

    cfg = IndexRuntimeConfig(
        id="EDU100",
        description="Education 100",
        base_value=1000.0,
        publish_interval_sec=0.0,
        history_file=str(tmp_path / "index_history.jsonl"),
        state_file=str(tmp_path / "index_state.json"),
        constituents=["AAPL", "MSFT"],
        outstanding_shares={"AAPL": 10_000, "MSFT": 20_000},
        reference_prices={"AAPL": 100.0, "MSFT": 50.0},
    )
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])

    proc = index_main.IndexProcess(config_path=tmp_path / "engine.yaml", reset=False)
    proc._initialise()
    yield proc, fake_pub
    proc.close()


def test_initialise_bootstraps_state_and_history(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, _ = proc_with_fakes
    managed = proc._indices["EDU100"]
    assert Path(managed.cfg.state_file).exists()
    managed.history.flush()
    rows, warnings = managed.history.query(0.0, 9999999999.0, {"INIT"})
    assert warnings == []
    assert rows


def test_handle_trade_publishes_index_update(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    proc._handle_trade({"symbol": "AAPL", "price": 120.0})
    assert fake_pub.sent
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.update"
    assert payload["index_id"] == "EDU100"


def test_handle_trade_ignores_invalid_payload(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    fake_pub.sent.clear()
    proc._handle_trade({"symbol": 123, "price": 100.0})
    proc._handle_trade({"symbol": "AAPL", "price": object()})
    assert fake_pub.sent == []


def test_history_request_unknown_index_emits_error(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    proc._handle_history_request({"gateway_id": "GW1", "index_id": "UNKNOWN"})
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.error.GW1"
    assert "Unknown index_id" in payload["reason"]


def test_history_request_valid_response(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    proc._handle_history_request(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "from_ts": 0.0,
            "to_ts": 9999999999.0,
            "types": ["INIT", "CORP_ACTION"],
        }
    )
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.history.GW1"
    assert isinstance(payload.get("records"), list)


def test_history_request_default_types_are_structural_only(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    """Omitting 'types' must default to the structural/audit record types
    (INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST) — never LEVEL/EOD, since
    pm-index no longer writes those to its JSONL file at all.
    """
    proc, fake_pub = proc_with_fakes
    proc._handle_history_request(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "from_ts": 0.0,
            "to_ts": 9999999999.0,
        }
    )
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.history.GW1"
    # The bootstrap INIT record from _initialise() should come back by default.
    records = payload.get("records")
    assert records
    assert all(r["type"] != "LEVEL" and r["type"] != "EOD" for r in records)


def test_trade_updates_are_not_written_to_structural_history(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    """Design intent: per-tick level updates must never reach the JSONL
    audit log — only the live index.update broadcast (picked up by
    pm-stats) and the in-memory publish throttle are touched.
    """
    proc, fake_pub = proc_with_fakes
    idx = proc._indices["EDU100"]
    idx.history.flush()
    before_rows, _ = idx.history.query(
        0.0, 9999999999.0, {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}
    )

    proc._handle_trade({"symbol": "AAPL", "price": 120.0})
    proc._handle_trade({"symbol": "MSFT", "price": 60.0})
    idx.history.flush()

    after_rows, _ = idx.history.query(
        0.0, 9999999999.0, {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}
    )
    assert len(after_rows) == len(before_rows)
    assert fake_pub.sent  # the live broadcast still happened


def test_finalize_eod_is_not_written_to_structural_history(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    idx = proc._indices["EDU100"]
    idx.history.flush()
    before_rows, _ = idx.history.query(
        0.0, 9999999999.0, {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}
    )

    proc._finalize_eod()
    idx.history.flush()

    after_rows, _ = idx.history.query(
        0.0, 9999999999.0, {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}
    )
    assert len(after_rows) == len(before_rows)
    # But the EOD close is still published live.
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.update"
    assert payload["session_state"] == "CLOSED"


def test_history_request_invalid_window_emits_error(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    proc._handle_history_request(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "from_ts": 10.0,
            "to_ts": 5.0,
        }
    )
    topic, _payload = decode(fake_pub.sent[-1])
    assert topic == "index.error.GW1"


def test_corp_action_ack_paths(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes

    proc._handle_corp_action(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "action": "SPLIT",
            "symbol": "AAPL",
            "ratio_numerator": 2,
            "ratio_denominator": 1,
        }
    )
    topic_ok, payload_ok = decode(fake_pub.sent[-1])
    assert topic_ok == "index.corp_action_ack.GW1"
    assert payload_ok["accepted"] is True

    proc._handle_corp_action(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "action": "BAD",
            "symbol": "AAPL",
        }
    )
    topic_bad, payload_bad = decode(fake_pub.sent[-1])
    assert topic_bad == "index.corp_action_ack.GW1"
    assert payload_bad["accepted"] is False


def test_constituent_change_add_and_delist(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes

    proc._handle_constituent_change(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "change_type": "ADD",
            "symbol": "AMZN",
            "shares_outstanding": 100,
            "initial_price": 200.0,
        }
    )
    topic_add, payload_add = decode(fake_pub.sent[-1])
    assert topic_add == "index.constituent_change_ack.GW1"
    assert payload_add["accepted"] is True

    proc._handle_constituent_change(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "change_type": "DELIST",
            "symbol": "AMZN",
        }
    )
    topic_delist, payload_delist = decode(fake_pub.sent[-1])
    assert topic_delist == "index.constituent_change_ack.GW1"
    assert payload_delist["accepted"] is True


def test_session_state_closed_finalizes_eod(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    proc._handle_session_state({"state": "CLOSED"})
    assert fake_pub.sent
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.update"
    assert payload["session_state"] == "CLOSED"


def test_close_closes_sockets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sub = _FakeSocket()
    fake_pull = _FakeSocket()
    fake_pub = _FakeSocket()

    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: fake_sub)
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: fake_pull)
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: fake_pub)
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [])

    proc = index_main.IndexProcess(config_path=tmp_path / "x.yaml", reset=False)
    proc.close()

    assert fake_sub.closed is True
    assert fake_pull.closed is True
    assert fake_pub.closed is True


def test_load_state_reset_deletes_file(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = proc_with_fakes
    cfg = IndexRuntimeConfig(
        id="EDU100",
        description="Education 100",
        base_value=1000.0,
        publish_interval_sec=0.0,
        history_file=str(tmp_path / "h.jsonl"),
        state_file=str(tmp_path / "state.json"),
        constituents=["AAPL"],
        outstanding_shares={"AAPL": 1},
        reference_prices={"AAPL": 1.0},
    )
    Path(cfg.state_file).write_text('{"index_id":"EDU100"}', encoding="utf-8")

    fake_sub = _FakeSocket()
    fake_pull = _FakeSocket()
    fake_pub = _FakeSocket()
    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: fake_sub)
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: fake_pull)
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: fake_pub)

    proc = index_main.IndexProcess(config_path=tmp_path / "x.yaml", reset=True)
    divisor, last_prices = proc._load_state(cfg)
    assert divisor is None
    assert last_prices == {}
    assert Path(cfg.state_file).exists() is False
    proc.close()


def test_load_state_mismatch_validations(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket], tmp_path: Path
) -> None:
    proc, _ = proc_with_fakes
    cfg = IndexRuntimeConfig(
        id="EDU100",
        description="Education 100",
        base_value=1000.0,
        publish_interval_sec=0.0,
        history_file=str(tmp_path / "h.jsonl"),
        state_file=str(tmp_path / "state.json"),
        constituents=["AAPL"],
        outstanding_shares={"AAPL": 1},
        reference_prices={"AAPL": 1.0},
    )

    Path(cfg.state_file).write_text('{"index_id":"OTHER"}', encoding="utf-8")
    with pytest.raises(ValueError):
        proc._load_state(cfg)

    Path(cfg.state_file).write_text(
        '{"index_id":"EDU100","constituents":["MSFT"]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        proc._load_state(cfg)


def test_publish_level_respects_interval(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    idx = proc._indices["EDU100"]
    object.__setattr__(idx.cfg, "publish_interval_sec", 999.0)
    idx.last_publish_time = time.monotonic()
    fake_pub.sent.clear()
    proc._publish_level(idx, idx.calc.recalculate(), force=False)
    assert fake_pub.sent == []


def test_finalize_eod_idempotent(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, _ = proc_with_fakes
    idx = proc._indices["EDU100"]
    idx.eod_finalized_for_session = True
    before = idx.calc.recalculate()
    proc._finalize_eod()
    assert idx.calc.recalculate() == pytest.approx(before)


def test_session_state_resets_intraday_fields(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, _ = proc_with_fakes
    idx = proc._indices["EDU100"]
    idx.day_open = 1.0
    idx.day_high = 2.0
    idx.day_low = 0.5
    idx.day_close = 1.5
    proc._handle_session_state({"state": "CONTINUOUS"})
    assert idx.day_open is None
    assert idx.day_high is None
    assert idx.day_low is None
    assert idx.day_close is None


def test_history_request_missing_gateway_id_noop(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    fake_pub.sent.clear()
    proc._handle_history_request({"index_id": "EDU100"})
    assert fake_pub.sent == []


def test_history_request_invalid_types_and_max_records(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes
    proc._handle_history_request(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "types": "LEVEL",
            "max_records": 0,
        }
    )
    topic, payload = decode(fake_pub.sent[-1])
    assert topic == "index.error.GW1"
    assert "max_records" in payload["reason"]


def test_corp_action_other_paths(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes

    proc._handle_corp_action(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "action": "CASH_DIVIDEND",
            "symbol": "AAPL",
            "dividend_per_share": 1.0,
        }
    )
    topic1, payload1 = decode(fake_pub.sent[-1])
    assert topic1 == "index.corp_action_ack.GW1"
    assert payload1["accepted"] is True

    proc._handle_corp_action(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "action": "SHARES_ISSUANCE",
            "symbol": "AAPL",
            "new_shares_outstanding": 11_000,
        }
    )
    topic2, payload2 = decode(fake_pub.sent[-1])
    assert topic2 == "index.corp_action_ack.GW1"
    assert payload2["accepted"] is True


def test_constituent_change_error_paths(
    proc_with_fakes: tuple[index_main.IndexProcess, _FakeSocket],
) -> None:
    proc, fake_pub = proc_with_fakes

    proc._handle_constituent_change(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "change_type": "BAD",
            "symbol": "AAPL",
        }
    )
    topic1, payload1 = decode(fake_pub.sent[-1])
    assert topic1 == "index.constituent_change_ack.GW1"
    assert payload1["accepted"] is False

    fake_pub.sent.clear()
    proc._handle_constituent_change(
        {
            "gateway_id": "GW1",
            "index_id": "UNKNOWN",
            "change_type": "DELIST",
            "symbol": "AAPL",
        }
    )
    topic2, payload2 = decode(fake_pub.sent[-1])
    assert topic2 == "index.error.GW1"
    assert "Unknown index_id" in payload2["reason"]


def test_build_parser_and_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    parser = index_main._build_parser()
    args = parser.parse_args(["--config", str(tmp_path / "cfg.yaml"), "--reset"])
    assert args.reset is True
    assert args.log_level is None
    assert args.verbose == 0
    assert args.quiet is False

    called: dict[str, Any] = {"run": 0, "close": 0}

    class _DummyProc:
        def __init__(self, config_path: Path, reset: bool = False) -> None:
            _ = (config_path, reset)

        def run(self) -> None:
            called["run"] += 1

        def close(self) -> None:
            called["close"] += 1

    monkeypatch.setattr(index_main, "IndexProcess", _DummyProc)
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda _self: argparse.Namespace(
            config=str(tmp_path / "cfg.yaml"),
            reset=False,
            log_level=None,
            verbose=0,
            quiet=False,
        ),
    )

    index_main.main()
    assert called["run"] == 1
    assert called["close"] == 1


def test_build_parser_logging_flags() -> None:
    parser = index_main._build_parser()
    args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
    assert args.verbose == 2
    assert args.quiet is True
    assert args.log_level == "ERROR"


def test_configure_logging_prefers_explicit_level() -> None:
    args = argparse.Namespace(log_level="INFO", verbose=2, quiet=True)
    assert index_main._configure_logging(args) == 20
