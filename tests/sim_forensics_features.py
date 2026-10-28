"""A recorded run of the engine features S28's replay models (amend, combo,
halt, circuit-breaker reopen, collar), for the D-check tests.

A real Engine on the s3-complex example (collars, circuit breakers,
sessions), driven command by command; its every published message is
written to audit.log as pm-audit writes it (tests/test_sim_forensics_rerun's
Recorder). A test then plants one fault by editing a line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import edumatcher.engine.main as engine_main
from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.models.order import OrderType, Side
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import order_payload
from tests.test_sim_forensics_rerun import Recorder


class Run:
    """The engine under recording, and the seed quotes' prices (ticks)."""

    def __init__(self, data: Path) -> None:
        data.mkdir(parents=True)
        self.data = data
        artifact = data.parent / "deployed" / "engine_config.json"
        compiled = deploy(resolve_example("s3-complex"), artifact)
        self.seed = {
            s: (c.market_maker_quotes[0].bid_price_ticks, c.market_maker_quotes[0].ask_price_ticks)  # fmt: skip
            for s, c in compiled.engine.symbols.items()
        }
        reset_trade_ids_for_tests()
        set_run_seq(1)
        self.rec = Recorder()
        self._patches: list[Any] = [
            mock.patch.object(engine_main, "_deployed_config", lambda: (compiled.engine, artifact.read_text(encoding="utf-8"))),  # fmt: skip
            mock.patch.object(engine_main, "make_puller", lambda _: Recorder()),
            mock.patch.object(engine_main, "make_publisher", lambda _: self.rec),
            mock.patch.multiple(
                engine_main,
                GTC_ORDERS_FILE=data / "gtc_orders.json",
                GTC_COMBOS_FILE=data / "gtc_combos.json",
                BOOK_STATS_FILE=data / "book_stats.json",
            ),
        ]
        for p in self._patches:
            p.start()
        self.engine = engine_main.Engine(config_path=None)
        self.engine._startup(1)
        for gw in ("TRADER01", "TRADER02", "TRADER03", "MM01", "OPS01"):
            self.cmd("system.gateway_connect", {"gateway_id": gw})
        for state in ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS"):
            self.cmd("session.transition", {"to_state": state})

    def cmd(self, topic: str, payload: dict[str, Any]) -> None:
        self.rec.command(self.engine, topic, payload)

    def order(self, side: Side, qty: int, ticks: int, gw: str, sym: str = "AAPL", kind: OrderType = OrderType.LIMIT, **kw: Any) -> str:  # fmt: skip
        p = order_payload(side, kind, qty, gw, price=ticks / 100 if ticks else None, symbol=sym, **kw)  # fmt: skip
        self.cmd("order.new", p)
        return str(p["id"])

    def finish(self) -> Path:
        """Checkpoint every book (D9 compares order by order) and write the audit."""
        self.engine._publish_checkpoints("PHASE")
        for p in self._patches:
            p.stop()
        (self.data / "audit.log").write_text("".join(self.rec.lines))
        return self.data


def consistent(data: Path) -> Path:
    """Every feature once, with nothing the checks should flag: amends
    (qty down, price up, marketable), an iceberg refill, a stop triggered
    by a trade, a fillable AON combo, an administrator halt and resume with
    no crossing interest, a circuit-breaker halt reopened by its uncross,
    and an order refused by the collar."""
    r = Run(data)
    bid, ask = r.seed["AAPL"]
    o = r.order(Side.BUY, 10, bid - 5, "TRADER01")
    r.cmd("order.amend", {"order_id": o, "gateway_id": "TRADER01", "qty": 6})
    r.cmd("order.amend", {"order_id": o, "gateway_id": "TRADER01", "price": (bid + 1) / 100})  # fmt: skip
    r.cmd("order.amend", {"order_id": o, "gateway_id": "TRADER01", "price": ask / 100})
    best = r.engine.books["AAPL"].best_bid_ticks()
    assert best is not None
    top = best + 1  # a seeded combo leg may lead
    r.order(Side.BUY, 50, top, "TRADER02", kind=OrderType.ICEBERG, visible_qty=10)
    r.order(Side.SELL, 5, 0, "TRADER03", kind=OrderType.STOP, stop_price=top / 100)
    r.order(Side.SELL, 15, top, "TRADER01")  # refills the iceberg; trips the stop
    mb, _ = r.seed["MSFT"]
    r.cmd(
        "order.combo",
        {"combo_id": "C1", "gateway_id": "TRADER02", "combo_type": "AON", "tif": "DAY", "legs": [
            {"symbol": "AAPL", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "tick_decimals": 2, "price_ticks": ask + 2},
            {"symbol": "MSFT", "side": "SELL", "order_type": "LIMIT", "quantity": 5, "tick_decimals": 2, "price_ticks": mb},
        ]},
    )  # fmt: skip
    tb, ta = r.seed["TSLA"]
    r.cmd("risk.symbol_halt", {"gateway_id": "OPS01", "symbol": "TSLA", "command_id": "H1"})  # fmt: skip
    r.order(Side.BUY, 7, tb - 10, "TRADER03", sym="TSLA")
    r.order(Side.BUY, 2, tb - 10, "TRADER01", sym="TSLA")  # queues behind it
    r.cmd("risk.symbol_resume", {"gateway_id": "OPS01", "symbol": "TSLA", "command_id": "H2"})  # fmt: skip
    _, ma = r.seed["MSFT"]
    r.cmd("risk.symbol_halt", {"gateway_id": "OPS01", "symbol": "MSFT", "level": "L1", "command_id": "H3"})  # fmt: skip
    r.order(Side.BUY, 9, ma + 5, "TRADER03", sym="MSFT")
    r.order(Side.SELL, 4, ma, "TRADER01", sym="MSFT")
    r.engine._circuit_breakers["MSFT"].resume_at_ns = 0
    r.engine._flush_circuit_breakers()  # the reopen uncross
    r.order(Side.BUY, 3, ask * 2, "TRADER01")  # refused by the collar
    return r.finish()
