from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edumatcher.engine.main import Engine
from edumatcher.models.message import decode


@dataclass
class _FakeSock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch, tmp_path: Path, yaml_text: str
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text(yaml_text)
    engine = Engine(config_path=str(cfg_path))
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    pub_sock.sent.clear()
    return engine, pub_sock


def _last_quote_ack(pub_sock: _FakeSock) -> dict:
    quote_acks = [
        decode(frames)
        for frames in pub_sock.sent
        if decode(frames)[0] == "quote.ack.GW01"
    ]
    assert quote_acks
    return quote_acks[-1][1]


def test_mm_obligation_enforcement_toggle_from_config(
    monkeypatch, tmp_path: Path
) -> None:
    enabled_yaml = """
symbols:
  AAPL:
    market_maker_quotes:
      - gateway_id: GW01
        bid_price: 100.00
        ask_price: 100.03
        bid_qty: 10
        ask_qty: 10
gateways:
  fix:
    - id: GW01
      role: MARKET_MAKER
      enforce_mm_obligation: true
      mm_max_spread_ticks: 5
      mm_min_qty: 10
"""
    engine_enabled, pub_enabled = _make_engine(monkeypatch, tmp_path, enabled_yaml)
    engine_enabled._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-CFG-ON",
            "bid_price": 100.00,
            "ask_price": 100.10,
            "bid_qty": 10,
            "ask_qty": 10,
        }
    )
    ack_enabled = _last_quote_ack(pub_enabled)
    assert ack_enabled["accepted"] is False
    assert "Spread" in ack_enabled["reason"]

    disabled_yaml = """
symbols:
  AAPL:
    market_maker_quotes:
      - gateway_id: GW01
        bid_price: 100.00
        ask_price: 100.10
        bid_qty: 10
        ask_qty: 10
gateways:
  fix:
    - id: GW01
      role: MARKET_MAKER
      enforce_mm_obligation: false
      mm_max_spread_ticks: 5
      mm_min_qty: 10
"""
    engine_disabled, pub_disabled = _make_engine(monkeypatch, tmp_path, disabled_yaml)
    engine_disabled._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-CFG-OFF",
            "bid_price": 100.00,
            "ask_price": 100.10,
            "bid_qty": 10,
            "ask_qty": 10,
        }
    )
    ack_disabled = _last_quote_ack(pub_disabled)
    assert ack_disabled["accepted"] is True
