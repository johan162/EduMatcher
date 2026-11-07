"""tools/sim_forensics check C13 (S31): a kill switch or a disconnect
cancels exactly the live orders it names, for its reason, and its ack says
so.

A real engine (s3-complex, tests/sim_forensics_features.Run) is driven
through every sweep the engine has -- a gateway's own switch on one symbol,
an administrator's on one gateway's quotes, one refused, a disconnect, the
global switch with a hit quote's remainder resting (X40) -- and its audit
must pass; a planted edit must be found.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from edumatcher.models.order import OrderType, Side
from tests.sim_forensics_features import Run
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, run_checks  # noqa: E402


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def sweeps(data: Path) -> Path:
    r = Run(data)
    ab, aa = r.seed["AAPL"]
    mb, _ = r.seed["MSFT"]
    tb, _ = r.seed["TSLA"]
    r.order(Side.BUY, 10, ab - 5, "TRADER01")
    r.order(Side.BUY, 10, mb - 5, "TRADER01", sym="MSFT")
    r.order(Side.SELL, 5, 0, "TRADER01", kind=OrderType.STOP, stop_price=(ab - 50) / 100)  # fmt: skip
    r.cmd(
        "order.oco",
        {"oco_id": "K1", "gateway_id": "TRADER01", "symbol": "AAPL", "quantity": 5, "tif": "DAY", "tick_decimals": 2,  # fmt: skip
         "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": aa + 50},
         "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": ab - 60}},  # fmt: skip
    )
    r.order(Side.SELL, 10, aa + 5, "TRADER02")
    r.order(
        Side.SELL, 1, tb, "TRADER02", sym="TSLA"
    )  # hits MM01's TSLA bid: its remainder rests
    r.cmd("risk.kill_switch", {"gateway_id": "TRADER01", "symbol": "AAPL", "command_id": "KS1"})  # fmt: skip
    r.cmd("risk.kill_switch_gateway", {"gateway_id": "OPS01", "target_gateway_id": "MM01", "symbol": "MSFT", "quotes_only": True, "command_id": "KS2"})  # fmt: skip
    r.cmd("risk.kill_switch_gateway", {"gateway_id": "TRADER02", "target_gateway_id": "MM01", "command_id": "KS3"})  # fmt: skip
    r.cmd("system.gateway_disconnect", {"gateway_id": "TRADER02", "reason": "test"})
    r.cmd("risk.kill_switch_global", {"gateway_id": "OPS01", "command_id": "KS4"})
    return r.finish()


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> str:
    return (sweeps(tmp_path_factory.mktemp("rec") / "data") / "audit.log").read_text()


def write(tmp_path: Path, audit: str) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "audit.log").write_text(audit)
    return data


def test_every_sweep_of_the_engine_passes(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    ds = open_ds(write(tmp_path, recorded))
    results = run_checks(ds, [REGISTRY["C12"], REGISTRY["C13"]], 10)
    assert {r.check.id: (r.status, r.samples) for r in results} == {"C12": ("PASS", []), "C13": ("PASS", [])}  # fmt: skip
    note = REGISTRY["C13"].fn(ds).note
    for sweep in ("disconnect CANCEL_ALL 1", "kill_switch 1", "kill_switch_gateway 1", "kill_switch_gateway refused 1", "kill_switch_global 1"):  # fmt: skip
        assert sweep in note


def _global_ack(lines: list[str]) -> int:
    return next(
        i for i, ln in enumerate(lines) if "[risk.kill_switch_global_ack." in ln
    )


def _drop_a_global_cancel(lines: list[str]) -> list[str]:
    """The global switch leaves one order live (the ack still lists it)."""
    chain = re.search(r"chain=(\S+)\]", lines[_global_ack(lines)])
    assert chain is not None
    i = next(i for i, ln in enumerate(lines) if f"chain={chain.group(1)}]" in ln and "[order.cancelled." in ln)  # fmt: skip
    return lines[:i] + lines[i + 1 :]


def _miscount_the_global_ack(lines: list[str]) -> list[str]:
    i = _global_ack(lines)
    head, body = lines[i].split("] {", 1)
    ack = json.loads("{" + body)
    ack["cancelled_orders"] += 1
    lines[i] = f"{head}] {json.dumps(ack)}\n"
    return lines


def _accept_the_refused_switch(lines: list[str]) -> list[str]:
    i = next(i for i, ln in enumerate(lines) if "[risk.kill_switch_gateway_ack." in ln and '"accepted": false' in ln)  # fmt: skip
    lines[i] = lines[i].replace('"accepted": false', '"accepted": true')
    return lines


@pytest.mark.parametrize(
    "plant, error",
    [
        (_drop_a_global_cancel, "kill_switch_global left orders live"),
        (_miscount_the_global_ack, "kill_switch_global ack's counts are not its lists"),
        (_accept_the_refused_switch, "kill_switch_gateway accepted from TRADER02, not an ADMIN"),  # fmt: skip
    ],
)
def test_c13_names_a_planted_fault(
    recorded: str,
    tmp_path: Path,
    open_ds: OpenDataset,
    plant: Callable[[list[str]], list[str]],
    error: str,
) -> None:
    lines = plant(recorded.splitlines(keepends=True))
    out = REGISTRY["C13"].fn(open_ds(write(tmp_path, "".join(lines))))
    assert error in [s["error"] for s in out.samples]
