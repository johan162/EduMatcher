"""
Shared test harness for engine-level tests.

Consolidates the _FakeSock / make_engine / payload / message-decoding
helpers that were previously copy-pasted into every engine test module.
New engine tests should import from here instead of redefining them.

Not a test module (no test_ prefix) — pytest will not collect it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.participant import ParticipantRole

SYMBOL = "AAPL"  # 2 tick decimals by default → 100.00 == 10000 ticks


@dataclass
class FakeSock:
    """In-memory stand-in for a ZMQ socket; records every published frame."""

    sent: list[list[bytes]] = field(default_factory=list)
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeDropCopy:
    """Records every drop-copy publication for assertion."""

    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def publish(self, gateway_id: str, event_type: str, payload: dict) -> None:
        self.events.append((gateway_id, event_type, payload))

    def close(self) -> None:  # pragma: no cover - interface parity
        pass


def make_engine(
    monkeypatch,
    tmp_path,
    symbols: tuple[str, ...] = (SYMBOL,),
    gateways: tuple[str, ...] = ("GW01", "GW02", "GW03"),
    mm_gateways: tuple[str, ...] = (),
    admin_gateways: tuple[str, ...] = (),
    sessions_enabled: bool = False,
    symbol_configs: dict[str, SymbolConfig] | None = None,
    gtc_orders: list[Order] | None = None,
    book_stats: dict[str, Any] | None = None,
) -> tuple[Engine, FakeSock]:
    """Build an Engine wired to fake sockets and a synthetic config."""
    pull_sock = FakeSock()
    pub_sock = FakeSock()

    def _role(gw: str) -> ParticipantRole:
        if gw in admin_gateways:
            return ParticipantRole.ADMIN
        if gw in mm_gateways:
            return ParticipantRole.MARKET_MAKER
        return ParticipantRole.TRADER

    cfg = EngineConfig(
        symbols=(
            symbol_configs
            if symbol_configs is not None
            else {sym: SymbolConfig(name=sym) for sym in symbols}
        ),
        fix_gateways={
            gw: FixGatewayConfig(id=gw, description=gw, role=_role(gw))
            for gw in gateways
        },
        sessions_enabled=sessions_enabled,
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_orders", lambda _: list(gtc_orders or [])
    )
    monkeypatch.setattr(
        "edumatcher.engine.main.load_book_stats", lambda _: dict(book_stats or {})
    )
    # Neutralize the engine's PUB-bind settle sleep WITHOUT touching the
    # global time module: patching "edumatcher.engine.main.time.sleep" would
    # no-op time.sleep process-wide (the module attribute IS the shared time
    # module), silently breaking any test that spins threads with real
    # sleeps (e.g. the clearing harness).  A scoped shim keeps the no-op
    # local to the engine module.
    import time as _time
    import types as _types

    _engine_time = _types.SimpleNamespace(
        sleep=lambda *_: None,
        monotonic=_time.monotonic,
        time=_time.time,
        time_ns=_time.time_ns,
    )
    monkeypatch.setattr("edumatcher.engine.main.time", _engine_time)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    engine = Engine(config_path=str(cfg_path))
    return engine, pub_sock


def connect(engine: Engine, *gws: str) -> None:
    for gw in gws or ("GW01", "GW02", "GW03"):
        engine._handle_gateway_connect({"gateway_id": gw})


def order_payload(
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    price: float | None = None,
    symbol: str = SYMBOL,
    tif: TIF = TIF.DAY,
    stop_price: float | None = None,
    visible_qty: int | None = None,
    smp_action: SmpAction = SmpAction.NONE,
    trail_offset: float | None = None,
) -> dict[str, Any]:
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        stop_price=stop_price,
        visible_qty=visible_qty,
        smp_action=smp_action,
        trail_offset=trail_offset,
    )
    return o.to_dict()


def msgs(pub_sock: FakeSock, topic: str) -> list[dict[str, Any]]:
    """Decode all published messages exactly matching *topic*."""
    out: list[dict[str, Any]] = []
    for frames in pub_sock.sent:
        t, payload = decode(frames)
        if t == topic:
            out.append(payload)
    return out


def all_msgs(pub_sock: FakeSock) -> list[tuple[str, dict[str, Any]]]:
    """Decode every published message as (topic, payload)."""
    return [decode(frames) for frames in pub_sock.sent]


def resting_ids(book: OrderBook) -> set[str]:
    return {o.id for o in book.resting_orders()}


def submit_quote(
    engine: Engine,
    gateway_id: str,
    bid_price: float,
    ask_price: float,
    bid_qty: int = 100,
    ask_qty: int = 100,
    quote_id: str = "Q1",
    symbol: str = SYMBOL,
) -> None:
    engine._handle_quote_new(
        {
            "gateway_id": gateway_id,
            "symbol": symbol,
            "quote_id": quote_id,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "tif": "DAY",
        }
    )


def terminal_notifications_for(
    pub_sock: FakeSock, gateway_id: str, order_id: str
) -> list[tuple[str, dict[str, Any]]]:
    """
    Every published message that tells *gateway_id* its order reached a
    terminal or actionable state: reject ack, cancelled, expired, or a fill.
    """
    interesting = {
        f"order.ack.{gateway_id}": lambda p: p.get("accepted") is False,
        f"order.cancelled.{gateway_id}": lambda p: True,
        f"order.expired.{gateway_id}": lambda p: True,
        f"order.fill.{gateway_id}": lambda p: True,
    }
    out: list[tuple[str, dict[str, Any]]] = []
    for topic, payload in all_msgs(pub_sock):
        pred = interesting.get(topic)
        if pred and payload.get("order_id") == order_id and pred(payload):
            out.append((topic, payload))
    return out
