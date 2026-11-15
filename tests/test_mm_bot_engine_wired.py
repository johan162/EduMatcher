"""pm-mm-bot against a real engine, in one process.

The bot's PUSH frames go straight to ``Engine._dispatch_pull_message``; the
engine's PUB frames are queued for the bot when it subscribes to their topic.
These tests exist because the engine publishes in an order unit tests do not
choose for themselves (a quote's ``quote.status`` can precede the
``order.fill`` that caused it), see
docs-design/reviews/EduMatcher-MM-Bot-Review-2026-11.md.
"""

from __future__ import annotations

import logging
import types
from typing import Any

import pytest
import zmq

import edumatcher.mm_bot.bot as bot_mod
import edumatcher.mm_bot.pricer as pricer_mod
from edumatcher.engine.config_loader import (
    EngineConfig,
    ParticipantConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.mm_bot.bot import BotState, MMBot
from edumatcher.mm_bot.pricer import InventorySkewPricer
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.models.price import clear_tick_registry, to_ticks

GW = "MM01"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _EnginePub:
    """The engine's PUB socket: frames are queued for the bot's SUB socket."""

    def __init__(self, sub: "_BotSub") -> None:
        self._sub = sub

    def send_multipart(self, frames: list[bytes]) -> None:
        self._sub.offer(frames)

    def begin_unit(self) -> None:
        pass

    def end_unit(self) -> None:
        pass

    def close(self) -> None:
        pass


class _BotSub:
    """The bot's SUB socket, with ZMQ prefix filtering."""

    def __init__(self) -> None:
        self.topics: list[str] = []
        self.queue: list[list[bytes]] = []

    def offer(self, frames: list[bytes]) -> None:
        topic = frames[0].decode()
        if any(topic.startswith(t) for t in self.topics):
            self.queue.append(frames)

    def recv_multipart(self) -> list[bytes]:
        return self.queue.pop(0)

    def setsockopt(self, opt: int, value: bytes) -> None:
        if opt == zmq.SUBSCRIBE:
            self.topics.append(value.decode())

    def connect(self, addr: str) -> None:
        pass

    def close(self) -> None:
        pass


class _BotPush:
    """The bot's PUSH socket: every frame is handled by the engine at once."""

    def __init__(self, wire: "Wire") -> None:
        self._wire = wire
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        topic, payload = decode(frames)
        self.sent.append((topic, payload))
        hook = self._wire.before_send.get(topic)
        if hook is not None:
            hook()
        if self._wire.engine_up and topic not in self._wire.lost_requests:
            self._wire.engine._dispatch_pull_message(topic, payload)

    def close(self) -> None:
        pass


class _Poller:
    """Ready when the bot's SUB queue holds a frame; otherwise the poll
    timeout passes on the fake clock."""

    def __init__(self, wire: "Wire") -> None:
        self._wire = wire

    def register(self, _sock: object, _event: object) -> None:
        pass

    def poll(self, timeout: int = 0) -> list[tuple[object, int]]:
        if self._wire.sub.queue:
            return [(self._wire.sub, zmq.POLLIN)]
        self._wire.clock.now += timeout / 1000.0
        return []


class Wire:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
        symbols: list[str],
        participant: dict[str, Any] | None = None,
        tick_decimals: dict[str, int] | None = None,
    ) -> None:
        self.clock = _Clock()
        self.sub = _BotSub()
        self.push = _BotPush(self)
        self.engine_up = True
        # Requests the engine never sees, and actions run just before a
        # request of that topic reaches the engine.
        self.lost_requests: set[str] = set()
        self.before_send: dict[str, Any] = {}
        fake_time = types.SimpleNamespace(
            monotonic=self.clock.monotonic, sleep=self.clock.sleep
        )
        monkeypatch.setattr(bot_mod, "time", fake_time)
        monkeypatch.setattr(pricer_mod, "time", fake_time)
        monkeypatch.setattr(bot_mod, "make_pusher", lambda _addr: self.push)

        def _make_subscriber(_addr: str, *topics: str) -> _BotSub:
            self.sub.topics.extend(topics)
            return self.sub

        monkeypatch.setattr(bot_mod, "make_subscriber", _make_subscriber)
        monkeypatch.setattr(zmq, "Poller", lambda: _Poller(self))

        pub = _EnginePub(self.sub)
        decimals = tick_decimals or {}
        cfg = EngineConfig(
            symbols={
                s: SymbolConfig(name=s, tick_decimals=decimals.get(s, 2))
                for s in symbols
            },
            participants={
                GW: ParticipantConfig(
                    id=GW,
                    description="MM",
                    role=ParticipantRole.MARKET_MAKER,
                    **{
                        "disconnect_behaviour": DisconnectBehaviour.CANCEL_QUOTES_ONLY,
                        **(participant or {}),
                    },
                ),
                "T1": ParticipantConfig(
                    id="T1", description="taker", role=ParticipantRole.TRADER
                ),
                "ADM": ParticipantConfig(
                    id="ADM", description="admin", role=ParticipantRole.ADMIN
                ),
            },
            sessions_enabled=False,
        )
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pub)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub)
        monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: ({}, 0))
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
        cfg_path = tmp_path / "engine_config.yaml"
        cfg_path.write_text("dummy: true\n")
        self.engine = Engine(config_path=str(cfg_path))
        for symbol in symbols:
            self.engine._book(symbol)
        for gateway in ("T1", "ADM"):
            self.engine._handle_gateway_connect({"gateway_id": gateway})
        self.symbols = symbols
        self.bot: MMBot | None = None

    def make_bot(self, **overrides: Any) -> MMBot:
        params: dict[str, Any] = dict(
            gateway_id=GW,
            symbols=self.symbols,
            strategy="symmetric",
            gap=0.10,
            gap_was_explicit=True,
            qty=500,
            drift_ticks=3,
            reissue_delay_ms=200,
            tif="DAY",
            heartbeat_interval_sec=5.0,
            startup_session_timeout_sec=1.0,
            bootstrap_timeout_sec=0.5,
            cancel_timeout_sec=1.0,
            shutdown_timeout_sec=0.5,
            qlegs_reconcile_interval_sec=15.0,
            initial_min=99.0,
            initial_max=101.0,
            engine_pull="tcp://engine:5555",
            engine_pub="tcp://engine:5556",
            verbose=False,
        )
        params.update(overrides)
        self.bot = MMBot(**params)
        return self.bot

    def start(self, **overrides: Any) -> MMBot:
        """Run the bot's real start-up and leave it quoting every symbol
        around a mid of 100.00."""
        overrides.setdefault("initial_min", 99.999)
        overrides.setdefault("initial_max", 100.001)
        bot = self.make_bot(**overrides)
        bot._setup_sockets()
        bot._running = True
        assert bot._start_up() is None
        self.pump()
        return bot

    def pump(self, seconds: float = 0.0) -> None:
        """Deliver every queued frame to the bot, ticking after each one,
        then let *seconds* pass in 50 ms ticks."""
        bot = self.bot
        assert bot is not None
        bot._tick()
        while self.sub.queue:
            topic, payload = decode(self.sub.recv_multipart())
            bot._dispatch(topic, payload)
            bot._tick()
        steps = int(round(seconds / 0.05))
        for _ in range(steps):
            self.clock.now += 0.05
            bot._tick()
            while self.sub.queue:
                topic, payload = decode(self.sub.recv_multipart())
                bot._dispatch(topic, payload)
                bot._tick()

    def deliver_only(self) -> None:
        """Deliver queued frames without running the bot's timers."""
        bot = self.bot
        assert bot is not None
        while self.sub.queue:
            topic, payload = decode(self.sub.recv_multipart())
            bot._dispatch(topic, payload)

    def take(self, symbol: str, side: Side, qty: int, price: float) -> None:
        self.engine._dispatch_pull_message(
            "order.new",
            Order.create(
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=qty,
                gateway_id="T1",
                tif=TIF.DAY,
                price_ticks=to_ticks(price, symbol),
            ).to_dict(),
        )

    def resting(self, symbol: str) -> list[tuple[str, int | None, int]]:
        return sorted(
            (o.side.value, o.price_ticks, o.remaining_qty)
            for o in self.engine.books[symbol].resting_orders()
            if o.gateway_id == GW
        )

    def engine_position(self, symbol: str) -> int:
        return self.engine._gateway_positions.get(GW, {}).get(symbol, 0)

    def halt(self, symbol: str) -> None:
        self.engine._dispatch_pull_message(
            "risk.symbol_halt", {"gateway_id": "ADM", "symbol": symbol}
        )

    def resume(self, symbol: str) -> None:
        self.engine._dispatch_pull_message(
            "risk.symbol_resume", {"gateway_id": "ADM", "symbol": symbol}
        )

    def sent(self, topic: str) -> list[dict[str, Any]]:
        return [p for t, p in self.push.sent if t == topic]


@pytest.fixture
def wire_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    def _make(symbols: list[str], **kwargs: Any) -> Wire:
        return Wire(monkeypatch, tmp_path, symbols, **kwargs)

    yield _make
    clear_tick_registry()


# ========================================================================
# WP-MMB01 — every fill of the bot's own legs is counted (H2)
# ========================================================================


class TestOwnFillsAreCounted:
    def test_a_fill_on_the_bid_is_counted(self, wire_factory: Any) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start(strategy="inventory_skew", max_position=1000)
        assert wire.resting("AAPL") == [("BUY", 9995, 500), ("SELL", 10005, 500)]

        wire.take("AAPL", Side.SELL, 100, 99.95)
        wire.deliver_only()

        assert wire.engine_position("AAPL") == 100
        assert bot._symbols_state["AAPL"].net_position == 100

    def test_a_fill_on_the_remainder_before_the_reissue_is_counted(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start(strategy="inventory_skew", max_position=1000)

        wire.take("AAPL", Side.SELL, 100, 99.95)
        wire.deliver_only()
        wire.take("AAPL", Side.SELL, 300, 99.95)
        wire.deliver_only()

        assert wire.engine_position("AAPL") == 400
        assert bot._symbols_state["AAPL"].net_position == 400
        assert bot._symbols_state["AAPL"].avg_cost == pytest.approx(99.95)

    def test_the_reissued_quote_is_skewed_by_the_fills(self, wire_factory: Any) -> None:
        wire = wire_factory(["AAPL"])
        wire.start(strategy="inventory_skew", max_position=1000)

        wire.take("AAPL", Side.SELL, 100, 99.95)
        wire.deliver_only()
        wire.take("AAPL", Side.SELL, 300, 99.95)
        wire.pump(seconds=1.0)

        expected = InventorySkewPricer(0.01, 0.10, 3, max_position=1000)
        expected.set_mid(100.0)
        expected.update_position(400)
        bid, ask = expected.compute_prices()
        assert (bid, ask) != (99.95, 100.05)
        assert wire.resting("AAPL") == [
            ("BUY", to_ticks(bid, "AAPL"), 500),
            ("SELL", to_ticks(ask, "AAPL"), 500),
        ]

    def test_a_filled_side_is_faded_by_the_passive_strategy(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        wire.start(
            strategy="passive",
            overrides={"AAPL": {"fade_ticks": 3, "fade_sec": 20.0}},
        )

        wire.take("AAPL", Side.SELL, 500, 99.95)
        wire.pump(seconds=1.0)

        assert wire.resting("AAPL") == [("BUY", 9992, 500), ("SELL", 10005, 500)]

    def test_a_fill_of_an_order_this_bot_never_quoted_is_not_counted(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start()

        bot._dispatch(
            f"order.fill.{GW}",
            {
                "order_id": "not-a-leg-of-this-bot",
                "symbol": "AAPL",
                "fill_qty": 100,
                "fill_price": 99.0,
            },
        )

        assert bot._symbols_state["AAPL"].net_position == 0

    def test_the_leg_index_stays_bounded(self, wire_factory: Any) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start()
        st = bot._symbols_state["AAPL"]

        for _ in range(1000):
            bot._clear_quote_state("AAPL")
            st.state = BotState.WAITING_FOR_SESSION
            bot._send_quote("AAPL")
            wire.deliver_only()

        assert len(bot._leg_to_symbol) <= bot._leg_index_cap
        assert wire.resting("AAPL") == [("BUY", 9995, 500), ("SELL", 10005, 500)]


# ========================================================================
# WP-MMB02 — a halted or paused symbol always comes back (H1, C2)
# ========================================================================


class TestHaltAndPhaseChanges:
    def test_a_resume_while_the_market_is_open_requotes(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start()
        wire.halt("AAPL")
        wire.pump()
        assert wire.resting("AAPL") == []
        assert bot._symbols_state["AAPL"].state == BotState.PAUSED

        wire.resume("AAPL")
        wire.pump()

        assert wire.resting("AAPL") == [("BUY", 9995, 500), ("SELL", 10005, 500)]
        assert bot._symbols_state["AAPL"].state == BotState.QUOTING

    def test_a_resume_during_an_auction_waits_for_continuous(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start()
        wire.halt("AAPL")
        wire.pump()
        bot._dispatch("session.state", {"state": "CLOSING_AUCTION"})
        quotes_before = len(wire.sent("quote.new"))

        wire.resume("AAPL")
        wire.pump(seconds=10.0)

        assert len(wire.sent("quote.new")) == quotes_before
        assert wire.resting("AAPL") == []

    def test_a_symbol_waiting_for_the_session_quotes_when_it_opens(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start()
        wire.halt("AAPL")
        wire.pump()
        bot._dispatch("session.state", {"state": "CLOSING_AUCTION"})
        wire.resume("AAPL")
        wire.pump()
        assert bot._symbols_state["AAPL"].state == BotState.WAITING_FOR_SESSION

        bot._dispatch("session.state", {"state": "CONTINUOUS"})
        wire.pump()

        assert wire.resting("AAPL") == [("BUY", 9995, 500), ("SELL", 10005, 500)]

    def test_a_quote_in_flight_at_a_phase_change_is_pulled(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.start(reissue_delay_ms=0)
        st = bot._symbols_state["AAPL"]
        assert st.pricer is not None
        st.pricer.set_mid(101.0)
        bot._reprice_if_drifted("AAPL")  # cancel goes out
        wire.deliver_only()  # CANCELLED arrives, reissue due now
        bot._tick()  # the new quote.new goes out; its ack is queued
        assert st.state == BotState.REISSUING

        bot._dispatch("session.state", {"state": "CLOSING_AUCTION"})
        wire.pump(seconds=5.0)

        assert st.state == BotState.PAUSED
        assert wire.resting("AAPL") == []


# ========================================================================
# WP-MMB03 — every reply is applied to the symbol it belongs to (C1, C9)
# ========================================================================


class TestRepliesReachTheirSymbol:
    def test_one_symbols_reissue_leaves_another_symbols_quote_alone(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL", "MSFT"])
        bot = wire.start()
        aapl, msft = bot._symbols_state["AAPL"], bot._symbols_state["MSFT"]
        aapl_quote = aapl.quote_id
        aapl_sends = [q for q in wire.sent("quote.new") if q["symbol"] == "AAPL"]

        # MSFT's QLEGS-divergence path: forget the quote, reissue now. The
        # engine's replace publishes CANCELLED for MSFT's old quote id.
        bot._clear_quote_state("MSFT")
        msft.reissue_at = wire.clock.now
        wire.pump(seconds=1.0)

        assert aapl.quote_id == aapl_quote
        assert [
            q for q in wire.sent("quote.new") if q["symbol"] == "AAPL"
        ] == aapl_sends
        assert msft.state == BotState.QUOTING

    def test_a_status_for_a_quote_this_bot_never_sent_changes_nothing(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL", "MSFT"])
        bot = wire.start()
        before = {s: bot._symbols_state[s].quote_id for s in ("AAPL", "MSFT")}
        sends = len(wire.sent("quote.new"))

        bot._dispatch(
            f"quote.status.{GW}", {"quote_id": "never-sent", "status": "CANCELLED"}
        )
        wire.pump(seconds=1.0)

        assert {s: bot._symbols_state[s].quote_id for s in before} == before
        assert len(wire.sent("quote.new")) == sends

    def test_an_ack_with_an_unknown_id_is_routed_by_its_symbol(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL", "MSFT"])
        bot = wire.start()

        bot._handle_quote_ack(
            {
                "quote_id": "engine-minted",
                "symbol": "MSFT",
                "accepted": True,
                "bid_order_id": "B",
                "ask_order_id": "A",
            }
        )

        assert bot._symbols_state["MSFT"].quote_id == "engine-minted"
        assert bot._symbols_state["AAPL"].quote_id != "engine-minted"

    def test_start_up_asks_once_for_the_whole_gateway_and_adopts_every_quote(
        self, wire_factory: Any
    ) -> None:
        symbols = ["AAPL", "MSFT", "TSLA"]
        wire = wire_factory(
            symbols, participant={"disconnect_behaviour": DisconnectBehaviour.LEAVE_ALL}
        )
        first = wire.start()
        live = {s: first._symbols_state[s].quote_id for s in symbols}
        wire.engine._dispatch_pull_message(
            "system.gateway_disconnect", {"gateway_id": GW}
        )
        wire.push.sent.clear()

        second = wire.make_bot(initial_min=99.999, initial_max=100.001)
        second._setup_sockets()
        second._running = True
        assert second._start_up() is None

        assert [p["symbol"] for p in wire.sent("system.quote_bootstrap_request")] == [
            ""
        ]
        assert [p["symbol"] for p in wire.sent("system.quote_legs_request")] == [""]
        assert {s: second._symbols_state[s].quote_id for s in symbols} == live
        assert wire.sent("quote.new") == []

    def test_the_periodic_qlegs_check_restores_only_the_symbol_that_lost_its_quote(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL", "MSFT"])
        bot = wire.start()
        aapl_quote = bot._symbols_state["AAPL"].quote_id
        # MSFT's quote leaves the book and the bot never hears of it (the
        # CANCELLED status is lost on the way).
        wire.engine._dispatch_pull_message(
            "quote.cancel", {"gateway_id": GW, "symbol": "MSFT"}
        )
        wire.sub.queue.clear()
        assert wire.resting("MSFT") == []

        wire.pump(seconds=16.0)

        assert wire.sent("system.quote_legs_request")[-1]["symbol"] == ""
        assert wire.resting("MSFT") == [("BUY", 9995, 500), ("SELL", 10005, 500)]
        assert bot._symbols_state["AAPL"].quote_id == aapl_quote


# ========================================================================
# WP-MMB04 — obligations only when enforced; refusals visible (C3, C4)
# ========================================================================

_BOT_LOGGER = "edumatcher.mm_bot.bot"


class TestObligationsAndRefusals:
    def test_an_unenforced_spread_obligation_does_not_refuse_a_wide_gap(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"], participant={"mm_max_spread_ticks": 20})
        bot = wire.start(gap=0.30)

        assert bot._symbols_state["AAPL"].startup_failed_reason is None
        assert wire.resting("AAPL") == [("BUY", 9985, 500), ("SELL", 10015, 500)]

    def test_an_unenforced_obligation_neither_sets_the_gap_nor_narrows_passive(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"], participant={"mm_max_spread_ticks": 1000})
        bot = wire.start(
            gap_was_explicit=False,
            strategy="passive",
            overrides={"AAPL": {"retreat_ticks": 5}},
        )
        st = bot._symbols_state["AAPL"]

        assert st.gap == pytest.approx(0.10)
        assert st.mm_max_spread_ticks is None

    def test_a_qty_below_an_enforced_minimum_is_refused_at_start_up(
        self, wire_factory: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        wire = wire_factory(
            ["AAPL"],
            participant={"enforce_mm_obligation": True, "mm_min_qty": 1000},
        )
        bot = wire.make_bot(qty=500)
        bot._setup_sockets()
        bot._running = True
        caplog.set_level(logging.WARNING, logger=_BOT_LOGGER)

        assert bot._start_up() == 1

        assert "mm_min_qty" in (bot._symbols_state["AAPL"].startup_failed_reason or "")
        assert any(
            r.levelno == logging.WARNING and "1000" in r.getMessage()
            for r in caplog.records
        )
        assert wire.sent("quote.new") == []

    def test_an_enforced_spread_obligation_still_refuses_a_wide_gap(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(
            ["AAPL"],
            participant={"enforce_mm_obligation": True, "mm_max_spread_ticks": 20},
        )
        bot = wire.make_bot(gap=0.30)
        bot._setup_sockets()
        bot._running = True

        assert bot._start_up() == 1
        assert "mm_max_spread_ticks" in (
            bot._symbols_state["AAPL"].startup_failed_reason or ""
        )

    def _refusing(self, wire: Wire) -> None:
        engine_config = wire.engine._engine_config
        assert engine_config is not None
        cfg = engine_config.participants[GW]
        cfg.enforce_mm_obligation = True
        cfg.mm_min_qty = 1000

    def test_a_refused_quote_is_reported_once_and_retried_less_often(
        self, wire_factory: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        wire = wire_factory(["AAPL"])
        wire.start()
        caplog.set_level(logging.DEBUG, logger=_BOT_LOGGER)
        self._refusing(wire)
        sends = len(wire.sent("quote.new"))

        wire.take("AAPL", Side.SELL, 500, 99.95)  # the reissue will be refused
        wire.pump(seconds=10.0)

        attempts = len(wire.sent("quote.new")) - sends
        refusals = [r for r in caplog.records if "REJECTED" in r.getMessage()]
        assert [r.levelno for r in refusals].count(logging.WARNING) == 1
        assert len(refusals) == attempts
        assert 1 <= attempts <= 8

    def test_a_refusal_after_an_accepted_quote_is_reported_again(
        self, wire_factory: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        wire = wire_factory(["AAPL"])
        wire.start()
        caplog.set_level(logging.DEBUG, logger=_BOT_LOGGER)
        self._refusing(wire)
        wire.take("AAPL", Side.SELL, 500, 99.95)
        wire.pump(seconds=2.0)
        engine_config = wire.engine._engine_config
        assert engine_config is not None
        engine_config.participants[GW].mm_min_qty = 0
        wire.pump(seconds=10.0)
        assert wire.resting("AAPL") != []

        self._refusing(wire)
        wire.take("AAPL", Side.SELL, 500, 99.95)
        wire.pump(seconds=2.0)

        warnings = [
            r
            for r in caplog.records
            if "REJECTED" in r.getMessage() and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 2


# ========================================================================
# WP-MMB05 — start-up uses the engine's facts (C5, C6)
# ========================================================================


def _quote_as(wire: Wire, symbol: str) -> None:
    """MM01 posts a 500 x 500 quote at 99.95/100.05 itself."""
    wire.engine._dispatch_pull_message(
        "quote.new",
        {
            "gateway_id": GW,
            "symbol": symbol,
            "tick_decimals": 2,
            "bid_price_ticks": 9995,
            "ask_price_ticks": 10005,
            "bid_qty": 500,
            "ask_qty": 500,
            "tif": "DAY",
            "quote_id": f"manual-{symbol}",
        },
    )


class TestStartUpFacts:
    def test_no_symbol_list_ends_start_up(
        self, wire_factory: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        wire = wire_factory(["AAPL"])
        wire.lost_requests.add("system.symbols_request")
        bot = wire.make_bot()
        bot._setup_sockets()
        bot._running = True
        caplog.set_level(logging.WARNING, logger=_BOT_LOGGER)

        assert bot._start_up() == 1

        assert wire.sent("quote.new") == []
        assert any("symbol list" in r.getMessage() for r in caplog.records)

    def test_the_position_is_taken_from_the_engine(self, wire_factory: Any) -> None:
        wire = wire_factory(["AAPL"])
        wire.engine._handle_gateway_connect({"gateway_id": GW})
        _quote_as(wire, "AAPL")
        wire.take("AAPL", Side.SELL, 300, 99.95)
        wire.engine._dispatch_pull_message(
            "system.gateway_disconnect", {"gateway_id": GW}
        )
        assert wire.engine_position("AAPL") == 300

        bot = wire.start(strategy="inventory_skew", max_position=1000)
        st = bot._symbols_state["AAPL"]

        assert st.net_position == 300
        assert st.avg_cost == pytest.approx(wire.engine._gateway_avg_cost[GW]["AAPL"])
        expected = InventorySkewPricer(0.01, 0.10, 3, max_position=1000)
        expected.set_mid(100.0)
        expected.update_position(300)
        bid, ask = expected.compute_prices()
        assert wire.resting("AAPL") == [
            ("BUY", to_ticks(bid, "AAPL"), 500),
            ("SELL", to_ticks(ask, "AAPL"), 500),
        ]

    def test_a_fill_on_an_adopted_quote_during_start_up_is_counted(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(
            ["AAPL"],
            participant={"disconnect_behaviour": DisconnectBehaviour.LEAVE_ALL},
        )
        wire.engine._handle_gateway_connect({"gateway_id": GW})
        _quote_as(wire, "AAPL")
        wire.engine._dispatch_pull_message(
            "system.gateway_disconnect", {"gateway_id": GW}
        )
        # While the restarted bot waits for its QLEGS reply, a taker hits the
        # quote it has just adopted.
        wire.before_send["system.quote_legs_request"] = lambda: wire.take(
            "AAPL", Side.SELL, 200, 99.95
        )

        bot = wire.start()

        assert wire.engine_position("AAPL") == 200
        assert bot._symbols_state["AAPL"].net_position == 200

    def test_a_missing_position_snapshot_starts_flat_with_a_warning(
        self, wire_factory: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        wire = wire_factory(["AAPL"])
        wire.lost_requests.add("system.position_request")
        caplog.set_level(logging.WARNING, logger=_BOT_LOGGER)

        bot = wire.start()

        assert bot._symbols_state["AAPL"].net_position == 0
        assert any("position" in r.getMessage() for r in caplog.records)
        assert wire.resting("AAPL") != []


# ========================================================================
# WP-MMB06 — a stop during start-up is honoured (C10)
# ========================================================================


class TestStopDuringStartUp:
    def test_a_stop_during_the_qboot_wait_ends_start_up_without_quoting(
        self, wire_factory: Any
    ) -> None:
        wire = wire_factory(["AAPL"])
        bot = wire.make_bot()
        bot._setup_sockets()
        bot._running = True
        wire.before_send["system.quote_bootstrap_request"] = bot.shutdown

        assert bot._start_up() == 0
        assert wire.sent("quote.new") == []
