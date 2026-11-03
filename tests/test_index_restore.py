"""K7 (I1): the index state file is enough to restore the live calculator.

The file kept only the divisor, the constituent list and last prices, and
``_load_state`` rejected a constituent list that differed from the static
config. So after a runtime ADD/DELIST the process could not restart at all
(until ``--reset``, which also forgot the divisor), and a share-count change
persisted its divisor but not the shares: the restored level was wrong.

Contract (K7): the state file is the authority for the *live* constituent set,
its share counts and its last prices; static config only supplies a fresh
start. Prices that move with trades are written at checkpoints -- every phase
change, at most every ``CHECKPOINT_INTERVAL_SEC`` while trading, and on
shutdown -- not on every trade. ``--reset`` stays the explicit override.
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K7.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

import edumatcher.index.main as index_main
from edumatcher.index.config_loader import IndexRuntimeConfig

from tests.support.restart import restart_equivalence


class _Sock:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def poll(self, timeout: int = 0) -> bool:
        return False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass


@pytest.fixture()
def make_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Any, None, None]:
    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(index_main, "make_replier", lambda *_a, **_k: _Sock())
    cfg = IndexRuntimeConfig(
        id="EDU100",
        description="Education 100",
        base_value=1000.0,
        publish_interval_sec=0.0,
        history_file=str(tmp_path / "history.jsonl"),
        state_file=str(tmp_path / "state.json"),
        constituents=["AAPL", "MSFT"],
        outstanding_shares={"AAPL": 10_000, "MSFT": 20_000},
        reference_prices={"AAPL": 100.0, "MSFT": 50.0},
    )
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])
    made: list[index_main.IndexProcess] = []

    def build() -> index_main.IndexProcess:
        proc = index_main.IndexProcess(config_path=tmp_path / "engine.yaml")
        proc._initialise()
        made.append(proc)
        return proc

    build.made = made  # type: ignore[attr-defined]
    yield build
    for proc in made:
        proc.close()


def _observed(proc: index_main.IndexProcess) -> dict[str, Any]:
    calc = proc._indices["EDU100"].calc
    symbols = calc.constituent_symbols()
    return {
        "level": calc.recalculate(),
        "divisor": calc.divisor,
        "cap": calc.aggregate_cap(),
        "symbols": symbols,
        "shares": {s: calc.shares_outstanding(s) for s in symbols},
        "prices": {s: calc.last_price(s) for s in symbols},
        "routing": sorted(
            s for s, ids in proc._constituent_to_indices.items() if "EDU100" in ids
        ),
    }


def _corp(proc: index_main.IndexProcess, action: str, symbol: str, **kw: Any) -> None:
    proc._handle_corp_action(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "command_id": "c",
            "action": action,
            "symbol": symbol,
            **kw,
        }
    )


def _change(proc: index_main.IndexProcess, change: str, symbol: str, **kw: Any) -> None:
    proc._handle_constituent_change(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "command_id": "c",
            "change_type": change,
            "symbol": symbol,
            **kw,
        }
    )


def test_trade_and_issuance_survive_a_restart(make_process: Any) -> None:
    first = make_process()
    first._handle_trade({"symbol": "AAPL", "price": 120.0})
    _corp(first, "SHARES_ISSUANCE", "MSFT", new_shares_outstanding=40_000)
    before = _observed(first)

    second = make_process()

    assert _observed(second) == before
    assert second._indices["EDU100"].calc.shares_outstanding("MSFT") == 40_000
    assert second._indices["EDU100"].calc.last_price("AAPL") == 120.0


def test_runtime_add_and_delist_survive_a_restart(make_process: Any) -> None:
    first = make_process()
    _change(first, "ADD", "GOOG", shares_outstanding=5_000, initial_price=200.0)
    _change(first, "DELIST", "MSFT")
    before = _observed(first)
    assert before["symbols"] == ["AAPL", "GOOG"]

    second = make_process()  # used to raise "State/config constituent mismatch"

    assert _observed(second) == before
    assert second._constituent_to_indices.get("MSFT", set()) == set()
    assert second._constituent_to_indices["GOOG"] == {"EDU100"}


def test_reset_still_returns_to_the_static_config(
    make_process: Any, tmp_path: Path
) -> None:
    first = make_process()
    _change(first, "DELIST", "MSFT")
    first._reset = True
    first._indices.clear()
    first._constituent_to_indices.clear()
    first._initialise()

    assert first._indices["EDU100"].calc.constituent_symbols() == ["AAPL", "MSFT"]


def test_trade_prices_are_checkpointed_on_shutdown(
    make_process: Any, tmp_path: Path
) -> None:
    proc = make_process()
    proc._handle_trade({"symbol": "AAPL", "price": 130.0})
    proc.close()
    make_process.made.remove(proc)  # closed here; the fixture must not again

    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["last_prices"]["AAPL"] == 130.0


def test_trade_prices_are_checkpointed_on_a_phase_change(
    make_process: Any, tmp_path: Path
) -> None:
    proc = make_process()
    proc._handle_trade({"symbol": "AAPL", "price": 131.0})
    proc._handle_session_state({"state": "CONTINUOUS"})

    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["last_prices"]["AAPL"] == 131.0


def test_trade_prices_are_checkpointed_on_the_interval_only_when_dirty(
    make_process: Any, tmp_path: Path
) -> None:
    proc = make_process()
    state = tmp_path / "state.json"
    idx = proc._indices["EDU100"]
    idx.last_checkpoint = 1_000.0

    proc._checkpoint(now=5_000.0)  # nothing moved since the write: no new write
    state.unlink()
    proc._checkpoint(now=5_000.0)
    assert not state.exists()

    proc._handle_trade({"symbol": "AAPL", "price": 132.0})
    proc._checkpoint(now=1_000.0 + index_main.CHECKPOINT_INTERVAL_SEC / 2)
    assert not state.exists()  # moved, but too soon

    proc._checkpoint(now=1_000.0 + index_main.CHECKPOINT_INTERVAL_SEC + 1)
    assert json.loads(state.read_text())["last_prices"]["AAPL"] == 132.0


def test_restart_equivalence_over_a_full_scenario(make_process: Any) -> None:
    proc = make_process()
    state = Path(proc._indices["EDU100"].cfg.state_file)
    proc._handle_trade({"symbol": "AAPL", "price": 111.0})
    _corp(proc, "SPLIT", "AAPL", ratio_numerator=2, ratio_denominator=1)
    _corp(proc, "SHARES_ISSUANCE", "MSFT", new_shares_outstanding=25_000)
    _change(proc, "ADD", "GOOG", shares_outstanding=5_000, initial_price=200.0)
    _change(proc, "DELIST", "MSFT")
    proc._handle_trade({"symbol": "GOOG", "price": 205.0})
    proc._handle_session_state({"state": "CLOSED"})

    def durable() -> dict[str, Any]:
        saved = json.loads(state.read_text())
        # Timestamp and the day_* diagnostics (the session's OHLC starts afresh
        # in a new process and nothing reads those keys back) are not state.
        for key in ("last_updated", "day_open", "day_high", "day_low"):
            saved.pop(key)
        return saved

    restart_equivalence(
        proc,
        restart=make_process,
        snapshot=_observed,
        durable=durable,
    )


@pytest.mark.parametrize("crash_in", ["write", "rename"])
def test_a_crash_while_writing_leaves_the_previous_state_loadable(
    make_process: Any, monkeypatch: pytest.MonkeyPatch, crash_in: str
) -> None:
    """The state file is now the restore authority and is written every
    checkpoint. A process killed mid-write must leave the previous file whole,
    not a truncated one that ``json.loads`` -- and so startup -- rejects
    (K1-K10 review #4)."""
    import os

    first = make_process()
    _corp(first, "SHARES_ISSUANCE", "MSFT", new_shares_outstanding=40_000)
    before = _observed(first)

    def killed_mid_write(self: Path, data: str, *_a: Any, **_k: Any) -> int:
        with open(self, "w", encoding="utf-8") as handle:
            handle.write(data[: len(data) // 2])
        raise KeyboardInterrupt("killed")

    def killed(*_a: Any, **_k: Any) -> None:
        raise KeyboardInterrupt("killed")

    with monkeypatch.context() as patch:
        # An in-place write dies half-way; a staged one dies before its data
        # is durable, or before the rename.
        patch.setattr(Path, "write_text", killed_mid_write)
        patch.setattr(os, "fsync" if crash_in == "write" else "replace", killed)
        first._handle_trade({"symbol": "AAPL", "price": 120.0})
        with pytest.raises(KeyboardInterrupt):
            first._checkpoint(force=True)

    second = make_process()

    assert _observed(second)["shares"] == before["shares"]
    assert _observed(second)["divisor"] == before["divisor"]
    state_dir = Path(first._indices["EDU100"].cfg.state_file).parent
    assert not list(state_dir.glob(".state.json.*.tmp"))
