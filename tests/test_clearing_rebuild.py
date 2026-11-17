"""``clearing.db`` can be rebuilt from the audit trail (For-Later L023, WP-FL05).

A trade pm-clearing never received is reported as a GAP, but positions and
P&L stay without it, and applying it late is not the same: average cost and
realised P&L depend on order. pm-audit holds every ``trade.executed``, so
``pm-clearing-cli rebuild --from-audit`` replays them in order into a fresh
database and reports how it differs from the live one.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from edumatcher.clearing import cli
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.rebuild import RebuildError, rebuild_from_audit
from edumatcher.clearing.store import write_close_snapshot
from edumatcher.models.message import make_trade_msg
from tests.conftest import opened

_NOW = time.time_ns()
DAY = 86_400 * 10**9

#: (seq, buyer, seller, price ticks, qty): GW01 buys, sells at a profit,
#: buys again; the order matters for average cost and realised P&L.
TRADES = [
    (1, "GW01", "GW02", 10_000, 10),
    (2, "GW01", "GW02", 10_200, 10),
    (3, "GW02", "GW01", 10_500, 15),
    (4, "GW01", "GW02", 9_900, 20),
    (5, "GW02", "GW01", 10_100, 5),
    (6, "GW01", "GW02", 10_050, 5),
]


def _payload(seq: int, buyer: str, seller: str, price: int, qty: int, ts_ns: int) -> dict[str, Any]:  # fmt: skip
    return {
        "id": f"000003-{seq:09d}",
        "run_seq": 3,
        "symbol": "AAPL",
        "buy_order_id": f"b{seq}",
        "sell_order_id": f"s{seq}",
        "buy_gateway_id": buyer,
        "sell_gateway_id": seller,
        "price": price / 100,
        "quantity": qty,
        "aggressor_side": "BUY",
        "ts_ns": ts_ns,
        "tick_decimals": 2,
        "price_ticks": price,
        "match_type": "CONTINUOUS",
    }


def _payloads(ts0: int = _NOW) -> list[dict[str, Any]]:
    return [_payload(*t, ts_ns=ts0 + t[0]) for t in TRADES]


def _write_audit(data_dir: Path, payloads: list[dict[str, Any]]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "audit.log").open("w") as f:
        f.write('[2026-11-16T09:00:00.000+00:00] [system.startup] [seq=1 eseq=1 msg=M0 cause= chain=C0] {"run_seq": 3}\n')  # fmt: skip
        for i, p in enumerate(payloads, start=2):
            f.write(
                f"[2026-11-16T09:00:01.000+00:00] [trade.executed] "
                f"[seq={i} eseq={i} msg=M{i} cause= chain=C{i}] {json.dumps(p)}\n"
            )
    return data_dir


def _ledger(db: Path, payloads: list[dict[str, Any]]) -> Path:
    proc = ClearingProcess(pub_addr="inproc://unused", db_path=db, print_every=0)
    opened(proc._conn)
    for p in payloads:
        proc._handle_message(make_trade_msg(p))
    proc.flush_now()
    proc._conn.close()
    return db


def _positions(db: Path) -> dict[tuple[str, str], tuple[int, float, float]]:
    conn = sqlite3.connect(db)
    try:
        return {
            (gw, sym): (q, round(c, 9), round(r, 9))
            for gw, sym, q, c, r in conn.execute(
                "SELECT gateway_id, symbol, net_qty, avg_cost, realized_pnl"
                " FROM gateway_symbol_positions"
            )
        }
    finally:
        conn.close()


@pytest.fixture
def scene(tmp_path: Path) -> tuple[Path, Path, Path]:
    """An audit with all six trades; a live ledger that missed trade 4; the
    ledger an uninterrupted pm-clearing would hold."""
    payloads = _payloads()
    audit = _write_audit(tmp_path / "data", payloads)
    live = _ledger(tmp_path / "live.db", [p for p in payloads if p["id"] != "000003-000000004"])  # fmt: skip
    truth = _ledger(tmp_path / "truth.db", payloads)
    return audit, live, truth


def test_the_rebuild_equals_a_ledger_that_received_every_trade(
    scene: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    audit, live, truth = scene
    out = tmp_path / "rebuilt.db"
    rebuild_from_audit(audit, live, out)
    assert _positions(out) == _positions(truth)
    assert _positions(out) != _positions(live)


def test_the_report_names_each_position_that_differs(
    scene: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    audit, live, truth = scene
    report = rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")
    assert report.trades == 6
    assert {(d["gateway_id"], d["symbol"]) for d in report.differences} == {
        ("GW01", "AAPL"),
        ("GW02", "AAPL"),
    }
    (gw01,) = [d for d in report.differences if d["gateway_id"] == "GW01"]
    assert gw01["rebuilt_net_qty"] == _positions(truth)[("GW01", "AAPL")][0]
    assert gw01["live_net_qty"] == _positions(live)[("GW01", "AAPL")][0]


def test_a_complete_live_ledger_has_no_differences(tmp_path: Path) -> None:
    payloads = _payloads()
    audit = _write_audit(tmp_path / "data", payloads)
    live = _ledger(tmp_path / "live.db", payloads)
    report = rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")
    assert report.differences == []


def test_close_snapshots_are_carried_over_unchanged(
    scene: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    audit, live, _ = scene
    conn = sqlite3.connect(live)
    write_close_snapshot(conn, "2026-11-15")
    before = conn.execute("SELECT * FROM position_close_snapshot ORDER BY 1, 2, 3").fetchall()  # fmt: skip
    conn.close()
    out = tmp_path / "rebuilt.db"

    rebuild_from_audit(audit, live, out)

    conn = sqlite3.connect(out)
    after = conn.execute("SELECT * FROM position_close_snapshot ORDER BY 1, 2, 3").fetchall()  # fmt: skip
    conn.close()
    assert before and after == before


def test_a_trade_recorded_twice_is_applied_once(tmp_path: Path) -> None:
    payloads = _payloads()
    audit = _write_audit(tmp_path / "data", payloads + payloads[2:3])
    live = _ledger(tmp_path / "live.db", payloads)
    report = rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")
    assert report.differences == []


def test_it_refuses_to_write_over_the_live_database(
    scene: tuple[Path, Path, Path],
) -> None:
    audit, live, _ = scene
    with pytest.raises(RebuildError, match="live"):
        rebuild_from_audit(audit, live, live)


def test_it_refuses_an_existing_output(
    scene: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    audit, live, _ = scene
    out = tmp_path / "rebuilt.db"
    out.write_bytes(b"")
    with pytest.raises(RebuildError, match="exists"):
        rebuild_from_audit(audit, live, out)


def test_it_refuses_an_audit_that_does_not_reach_the_ledgers_first_day(
    tmp_path: Path,
) -> None:
    """The rebuild starts flat, so it needs every trade since the live
    ledger's first one; gateway_daily_summary is never pruned."""
    early = _payloads(_NOW - 3 * DAY)[:2]
    later = _payloads()[2:]
    live = _ledger(tmp_path / "live.db", early + later)
    audit = _write_audit(tmp_path / "data", later)
    with pytest.raises(RebuildError, match="reaches back to"):
        rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")
    assert not (tmp_path / "rebuilt.db").exists()


def test_it_refuses_an_audit_without_trades(tmp_path: Path) -> None:
    audit = _write_audit(tmp_path / "data", [])
    live = _ledger(tmp_path / "live.db", _payloads())
    with pytest.raises(RebuildError, match="no trade"):
        rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")


# -- the CLI ---------------------------------------------------------------------


def _cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["pm-clearing-cli", *argv])
    try:
        cli.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_the_cli_reports_differences_and_exits_3(
    scene: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit, live, _ = scene
    out = tmp_path / "rebuilt.db"
    status = _cli(monkeypatch, "--datapath", str(live), "--format", "json", "rebuild", "--from-audit", str(audit), "--output", str(out))  # fmt: skip
    assert status == 3
    rows = json.loads(capsys.readouterr().out)
    assert {r["gateway_id"] for r in rows} == {"GW01", "GW02"}
    assert out.exists()


def test_the_cli_exits_0_without_differences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = _payloads()
    audit = _write_audit(tmp_path / "data", payloads)
    live = _ledger(tmp_path / "live.db", payloads)
    status = _cli(monkeypatch, "--datapath", str(live), "rebuild", "--from-audit", str(audit), "--output", str(tmp_path / "r.db"))  # fmt: skip
    assert status == 0


def test_the_cli_exits_1_on_a_refusal(
    scene: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit, live, _ = scene
    status = _cli(monkeypatch, "--datapath", str(live), "rebuild", "--from-audit", str(audit), "--output", str(live))  # fmt: skip
    assert status == 1
    assert "[ERROR]" in capsys.readouterr().err


def test_a_hole_in_the_audit_trail_is_reported(tmp_path: Path) -> None:
    payloads = _payloads()
    audit = _write_audit(tmp_path / "data", payloads[:2] + payloads[3:])
    live = _ledger(tmp_path / "live.db", payloads)
    report = rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")
    assert report.gaps == 1
    assert report.differences  # the rebuild lacks the trade too


def test_large_trails_are_written_in_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edumatcher.clearing.rebuild as rebuild_mod

    monkeypatch.setattr(rebuild_mod, "_FLUSH_EVERY", 2)
    flushes: list[int] = []
    real = ClearingProcess.flush_now

    def counting(self: ClearingProcess) -> int:
        flushes.append(len(self._buffer))
        return real(self)

    monkeypatch.setattr(ClearingProcess, "flush_now", counting)
    payloads = _payloads()
    audit = _write_audit(tmp_path / "data", payloads)
    live = _ledger(tmp_path / "live.db", payloads)
    flushes.clear()
    rebuild_from_audit(audit, live, tmp_path / "rebuilt.db")
    assert max(flushes) <= 2
