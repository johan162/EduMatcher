"""tools/sim_forensics check C14 (S33): orders expire as their time in
force ends, never a GTC one, and none outlives it.

A real engine (s3-complex) rests DAY and GTC orders, a DAY stop and a DAY
OCO pair, an ATC order in the closing auction, closes, opens the next day
with an ATO order in the opening auction and moves on to continuous
trading. Its audit must pass C14; a planted edit must be found.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from edumatcher.models.order import OrderType, Side, TIF
from tests.sim_forensics_features import Run
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome  # noqa: E402


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def two_days(data: Path) -> Path:
    r = Run(data)
    bid, _ = r.seed["AAPL"]
    r.order(Side.BUY, 10, bid - 20, "TRADER01")
    r.order(Side.BUY, 10, bid - 30, "TRADER02", tif=TIF.GTC)
    r.order(Side.SELL, 5, 0, "TRADER03", kind=OrderType.STOP, stop_price=(bid - 200) / 100)  # fmt: skip
    r.cmd(
        "order.oco",
        {"oco_id": "K1", "gateway_id": "TRADER01", "symbol": "AAPL", "quantity": 5, "tif": "DAY", "tick_decimals": 2,  # fmt: skip
         "leg1": {"side": "BUY", "order_type": "LIMIT", "price_ticks": bid - 40},
         "leg2": {"side": "BUY", "order_type": "STOP", "stop_price_ticks": bid + 300}},  # fmt: skip
    )
    r.cmd("session.transition", {"to_state": "CLOSING_AUCTION"})
    r.order(Side.BUY, 10, bid - 50, "TRADER03", tif=TIF.ATC)
    r.cmd("session.transition", {"to_state": "CLOSED"})
    r.cmd("session.transition", {"to_state": "PRE_OPEN"})
    r.cmd("session.transition", {"to_state": "OPENING_AUCTION"})
    r.order(Side.BUY, 10, bid - 60, "TRADER03", tif=TIF.ATO)
    r.cmd("session.transition", {"to_state": "CONTINUOUS"})
    return r.finish()


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> str:
    return (two_days(tmp_path_factory.mktemp("rec") / "data") / "audit.log").read_text()  # fmt: skip


def c14(open_ds: OpenDataset, tmp_path: Path, audit: str) -> Outcome:
    data = tmp_path / "data"
    data.mkdir()
    (data / "audit.log").write_text(audit)
    return REGISTRY["C14"].fn(open_ds(data))


def test_a_close_and_an_open_pass(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    out = c14(open_ds, tmp_path, recorded)
    assert (out.violations, out.samples) == (0, [])
    for seen in ("ATC windows closed 1", "ATO windows closed 2", "DAY windows closed 1", "ATC expired 1", "ATO expired 1"):  # fmt: skip
        assert seen in out.note


def _drop_one(topic_part: str) -> Callable[[list[str]], list[str]]:
    def edit(lines: list[str]) -> list[str]:
        i = next(k for k, ln in enumerate(lines) if topic_part in ln)
        return lines[:i] + lines[i + 1 :]

    return edit


def _keep_in_the_book(lines: list[str]) -> list[str]:
    """The close's checkpoint still holds a DAY order."""
    close = next(
        ln for ln in lines if "[session.transition]" in ln and '"CLOSED"' in ln
    )
    chain = close.split("chain=", 1)[1].split("]", 1)[0]
    i = next(k for k, ln in enumerate(lines) if "[system.book_checkpoint.AAPL]" in ln and f"chain={chain}]" in ln)  # fmt: skip
    lines[i] = lines[i].replace('"tif": "GTC"', '"tif": "DAY"', 1)
    return lines


def _expire_the_gtc(lines: list[str]) -> list[str]:
    """The GTC order expires with the DAY ones."""
    ack = next(ln for ln in lines if "[order.ack.TRADER02]" in ln and '"tif": "GTC"' in ln)  # fmt: skip
    oid = ack.split('"order_id": "', 1)[1].split('"', 1)[0]
    i = next(k for k, ln in enumerate(lines) if "[order.expired." in ln)
    head = lines[i].split("] [order.expired.", 1)[0]
    meta = lines[i].split("] [", 2)[2].split("] ", 1)[0]
    return lines[: i + 1] + [f'{head}] [order.expired.TRADER02] [{meta}] {{"order_id": "{oid}", "symbol": "AAPL"}}\n'] + lines[i + 1 :]  # fmt: skip


@pytest.mark.parametrize(
    "plant, error",
    [
        (_drop_one("[order.expired.TRADER03]"), "orders outlived their window"),
        (_keep_in_the_book, "orders outlived their window in the book"),
        (_expire_the_gtc, "a GTC order expired outside its window"),
    ],
)
def test_c14_names_a_planted_fault(
    recorded: str,
    tmp_path: Path,
    open_ds: OpenDataset,
    plant: Callable[[list[str]], list[str]],
    error: str,
) -> None:
    out = c14(open_ds, tmp_path, "".join(plant(recorded.splitlines(keepends=True))))
    assert any(error in str(s["error"]) for s in out.samples)
