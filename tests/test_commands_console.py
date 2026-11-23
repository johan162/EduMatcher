from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass, field
import json
import sys
import time
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import zmq

from edumatcher.commands import ExchangeCommandClient
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from edumatcher.commands import CommandTimeoutError
from edumatcher.commands import console as console_mod
from edumatcher.messaging.bus import make_pusher


@dataclass
class _FakeClient:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )
    #: The engine's ``status`` on orders/position replies (L030).
    query_status: str = "OK"

    def halt_all(self) -> dict[str, Any]:
        self.calls.append(("halt_all", (), {}))
        return {"accepted": True, "halted_symbols": 2, "cancelled_quotes": 4}

    def resume_all(self) -> dict[str, Any]:
        self.calls.append(("resume_all", (), {}))
        return {"accepted": True, "resumed_symbols": 2}

    def kill_switch(self, gw: str, symbol: str = "") -> dict[str, Any]:
        self.calls.append(("kill_switch", (gw,), {"symbol": symbol}))
        return {"accepted": True, "cancelled_orders": 3, "cancelled_quotes": 1}

    @property
    def gateway_id(self) -> str:
        return "ADM01"

    def kill_switch_gateway(
        self, gw: str, note: str = "", *, symbol: str = "", quotes_only: bool = False
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "kill_switch_gateway",
                (gw,),
                {"symbol": symbol, "quotes_only": quotes_only},
            )
        )
        return {"accepted": True, "cancelled_orders": 3, "cancelled_quotes": 1}

    def gateway_kick(self, gw: str, reason: str = "") -> None:
        self.calls.append(("gateway_kick", (gw,), {"reason": reason}))

    def quote_cancel(self, gw: str, sym: str) -> dict[str, Any]:
        self.calls.append(("quote_cancel", (gw, sym), {}))
        return {"accepted": True}

    def book_depth(self, sym: str) -> dict[str, Any]:
        self.calls.append(("book_depth", (sym,), {}))
        return {
            "symbol": sym.upper(),
            "bids": [{"price": 149.9, "qty": 100}],
            "asks": [{"price": 150.1, "qty": 120}],
            "last_price": 150.0,
            "last_qty": 10,
        }

    def order_list(self, gw: str) -> list[dict[str, Any]]:
        self.calls.append(("order_list", (gw,), {}))
        return [
            {
                "id": "abc123",
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "remaining_qty": 10,
                "price": 150.0,
            }
        ]

    def orders_reply(self, gw: str) -> dict[str, Any]:
        orders = self.order_list(gw)
        return {"gateway_id": gw.upper(), "orders": orders, "status": self.query_status}

    def positions_reply(self, gw: str) -> dict[str, Any]:
        positions = self.position_snapshot(gw)
        return {
            "gateway_id": gw.upper(),
            "positions": positions,
            "status": self.query_status,
        }

    def price_level_orders(
        self, sym: str, price: float | None = None
    ) -> dict[str, Any]:
        self.calls.append(("price_level_orders", (sym,), {"price": price}))
        return {
            "symbol": sym.upper(),
            "rejected": False,
            "orders": [
                {
                    "id": "66d5940c",
                    "gateway_id": "MM01",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "remaining_qty": 200,
                    "price": 149.50,
                }
            ],
        }

    def symbol_list(self) -> list[str]:
        self.calls.append(("symbol_list", (), {}))
        return ["AAPL", "MSFT"]

    def tick_decimals(self, symbol: str) -> int | None:
        return {"AAPL": 2, "MSFT": 2, "XYZ": 3}.get(symbol.upper())

    def session_advance(self, state: str) -> dict[str, Any]:
        self.calls.append(("session_advance", (state,), {}))
        return {"prev_state": "PRE_OPEN", "state": state.upper()}

    def session_status(self) -> dict[str, Any]:
        self.calls.append(("session_status", (), {}))
        return {"state": "CONTINUOUS", "sessions_enabled": True}

    def session_schedule(self) -> dict[str, Any]:
        self.calls.append(("session_schedule", (), {}))
        return {
            "sessions_enabled": True,
            "schedule": {
                "pre_open": "09:00",
                "opening_auction_start": "09:25",
                "continuous_start": "09:30",
                "closing_auction_start": "16:00",
                "closing_auction_end": "16:05",
            },
        }

    def gateway_list(self) -> list[dict[str, Any]]:
        self.calls.append(("gateway_list", (), {}))
        return [
            {
                "id": "GW_ADMIN",
                "role": "ADMIN",
                "description": "Ops",
                "connected": True,
            },
            {"id": "TRADER01", "role": "TRADER", "description": "", "connected": True},
            {"id": "TRADER02", "role": "TRADER", "description": "", "connected": False},
        ]

    def volume(self) -> dict[str, Any]:
        self.calls.append(("volume", (), {}))
        return {
            "symbols": [{"symbol": "AAPL", "qty": 10, "value": 1500.0, "trades": 2}],
            "total_qty": 10,
            "total_value": 1500.0,
            "total_trades": 2,
        }

    def position_snapshot(self, target_gw: str) -> list[dict[str, Any]]:
        self.calls.append(("position_snapshot", (target_gw,), {}))
        return [
            {"symbol": "AAPL", "net_qty": 500, "avg_cost": 149.75},
            {"symbol": "MSFT", "net_qty": -200, "avg_cost": 310.10},
        ]

    def engine_disconnect_monitor(self) -> MagicMock:
        return MagicMock()

    def close_engine_disconnect_monitor(self, monitor: Any) -> None:
        monitor.close(linger=0)

    def quote_bootstrap(self, target_gw: str, symbol: str = "") -> list[dict[str, Any]]:
        self.calls.append(("quote_bootstrap", (target_gw,), {"symbol": symbol}))
        quotes = [
            {"symbol": "AAPL", "bid_price": 149.70, "ask_price": 149.90},
        ]
        if symbol:
            quotes = [q for q in quotes if q["symbol"] == symbol.upper()]
        return quotes

    def force_uncross(
        self,
        symbol: str,
        price: float | None = None,
        *,
        dry_run: bool = False,
        note: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "force_uncross",
                (symbol,),
                {"price": price, "dry_run": dry_run, "note": note},
            )
        )
        if dry_run:
            return {
                "accepted": True,
                "symbol": symbol.upper(),
                "dry_run": True,
                "indicative_price": 100.0,
                "indicative_qty": 50,
                "surplus": 10,
                "imbalance_side": "BUY",
            }
        return {
            "accepted": True,
            "symbol": symbol.upper(),
            "dry_run": False,
            "indicative_price": 100.0,
            "indicative_qty": 50,
            "surplus": 10,
            "imbalance_side": "BUY",
            "printed_price": price if price is not None else 100.0,
            "traded_qty": 50,
        }


def _capture_print(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def _fake_print(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(console_mod.console, "print", _fake_print)
    return calls


def test_parse_splits_pipe_fields() -> None:
    cmd, fields = console_mod._parse("kill|gw=Trader01|sym=aapl")
    assert cmd == "KILL"
    assert fields == {"GW": "Trader01", "SYM": "aapl"}


def test_completer_top_level_and_values() -> None:
    c = console_mod._AdminCompleter(["AAPL", "MSFT"])

    top = [
        x.text
        for x in c.get_completions(
            Document("SE"), CompleteEvent(completion_requested=True)
        )
    ]
    assert "SESSION" in top
    assert "SESSION_STATUS" in top

    sym = [
        x.text
        for x in c.get_completions(
            Document("BOOK|SYM=A"), CompleteEvent(completion_requested=True)
        )
    ]
    assert sym == ["AAPL"]

    st = [
        x.text
        for x in c.get_completions(
            Document("SESSION|STATE=C"), CompleteEvent(completion_requested=True)
        )
    ]
    assert "CONTINUOUS" in st


def test_display_helpers_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    console_mod._print_book({"symbol": "AAPL", "bids": [], "asks": []})
    console_mod._print_orders([], "GW1")
    console_mod._print_orders(
        [
            {
                "id": "abc",
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "remaining_qty": 1,
                "price": 123.4,
            }
        ],
        "GW1",
    )
    console_mod._print_level({"rejected": False, "orders": []}, "AAPL", "")
    console_mod._print_level(
        {
            "rejected": False,
            "orders": [
                {
                    "id": "66d5940c",
                    "gateway_id": "MM01",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "remaining_qty": 200,
                    "price": 149.5,
                }
            ],
        },
        "AAPL",
        "149.50",
    )
    console_mod._print_level({"rejected": True, "reason": "ADMIN only"}, "AAPL", "")
    console_mod._print_symbols([])
    console_mod._print_symbols(["AAPL"])
    console_mod._print_session_status({"state": "CLOSED", "sessions_enabled": False})
    console_mod._print_schedule({"sessions_enabled": False, "schedule": {}})
    console_mod._print_schedule(
        {
            "sessions_enabled": True,
            "schedule": {
                "pre_open": "09:00",
                "opening_auction_start": "09:25",
                "continuous_start": "09:30",
                "closing_auction_start": "16:00",
                "closing_auction_end": "16:05",
            },
        }
    )
    console_mod._print_gateways([])
    console_mod._print_gateways(
        [{"id": "GW_ADMIN", "role": "ADMIN", "description": "ops", "connected": True}]
    )
    console_mod._print_volume(
        {"symbols": [], "total_qty": 0, "total_value": 0.0, "total_trades": 0}
    )
    console_mod._print_volume(
        {
            "symbols": [{"symbol": "AAPL", "qty": 1, "value": 10.0, "trades": 1}],
            "total_qty": 1,
            "total_value": 10.0,
            "total_trades": 1,
        }
    )


@pytest.mark.parametrize(
    "cmd",
    [
        "HALT",
        "RESUME",
        "BOOK",
        "ORDERS",
        "LEVEL",
        "SESSION_STATUS",
        "SCHEDULE",
        "GATEWAYS",
        "VOLUME",
        "POSITION",
    ],
)
def test_execute_command_success_paths(
    monkeypatch: pytest.MonkeyPatch, cmd: str
) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())

    fields = {
        "BOOK": {"SYM": "AAPL"},
        "ORDERS": {"GW": "TRADER01"},
        "LEVEL": {"SYM": "AAPL"},
        "POSITION": {"GW": "MM_AAPL_01"},
    }.get(cmd, {})

    accepted, _result = console_mod.execute_command(client, cmd, fields)
    assert accepted is True


@pytest.mark.parametrize(
    "cmd,fields",
    [
        ("HALT", {}),
        ("BOOK", {"SYM": "AAPL"}),
        ("ORDERS", {"GW": "TRADER01"}),
        ("SYMBOLS", {}),
        ("VOLUME", {}),
        ("POSITION", {"GW": "MM_AAPL_01"}),
    ],
)
def test_execute_command_json_output_prints_json_not_rich_text(
    monkeypatch: pytest.MonkeyPatch, cmd: str, fields: dict[str, str]
) -> None:
    """json_output=True must print via plain print(), never console.print()."""
    rich_calls = _capture_print(monkeypatch)
    plain_calls: list[Any] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: plain_calls.append((a, kw)))
    client = cast(ExchangeCommandClient, _FakeClient())

    accepted, result = console_mod.execute_command(
        client, cmd, fields, json_output=True
    )

    assert accepted is True
    assert rich_calls == []
    assert len(plain_calls) == 1
    (printed_text,), _kw = plain_calls[0]
    assert isinstance(printed_text, str)
    parsed = json.loads(printed_text)
    assert parsed == result


def test_execute_command_symbols_updates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())
    cache = ["OLD"]
    ok, _result = console_mod.execute_command(
        client, "SYMBOLS", {}, symbols_cache=cache
    )
    assert ok is True
    assert cache == ["AAPL", "MSFT"]


def test_execute_command_usage_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())

    assert console_mod.execute_command(client, "KILL", {})[0] is False
    assert console_mod.execute_command(client, "KICK", {})[0] is False
    assert console_mod.execute_command(client, "QCANCEL", {"GW": "G"})[0] is False
    assert console_mod.execute_command(client, "BOOK", {})[0] is False
    assert console_mod.execute_command(client, "ORDERS", {})[0] is False
    assert console_mod.execute_command(client, "LEVEL", {})[0] is False
    assert (
        console_mod.execute_command(client, "LEVEL", {"SYM": "AAPL", "PRICE": "abc"})[0]
        is False
    )
    assert console_mod.execute_command(client, "SESSION", {})[0] is False
    assert console_mod.execute_command(client, "NOPE", {})[0] is False
    assert console_mod.execute_command(client, "POSITION", {})[0] is False


def test_execute_command_level_reports_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)

    class _RejectingLevel(_FakeClient):
        def price_level_orders(
            self, sym: str, price: float | None = None
        ) -> dict[str, Any]:
            return {"rejected": True, "reason": "ADMIN only", "orders": []}

    client = cast(ExchangeCommandClient, _RejectingLevel())
    assert console_mod.execute_command(client, "LEVEL", {"SYM": "AAPL"})[0] is False


def test_execute_command_level_passes_price_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    client = _FakeClient()
    console_mod.execute_command(
        cast(ExchangeCommandClient, client), "LEVEL", {"SYM": "AAPL", "PRICE": "149.5"}
    )
    name, args, kwargs = client.calls[-1]
    assert name == "price_level_orders"
    assert args == ("AAPL",)
    assert kwargs == {"price": 149.5}


def test_execute_command_rejections(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)

    class _Rejecting(_FakeClient):
        def halt_all(self) -> dict[str, Any]:
            return {"accepted": False, "reason": "x"}

        def resume_all(self) -> dict[str, Any]:
            return {"accepted": False, "reason": "x"}

        def kill_switch(self, gw: str, symbol: str = "") -> dict[str, Any]:
            return {"accepted": False, "reason": "x"}

        def quote_cancel(self, gw: str, sym: str) -> dict[str, Any]:
            return {"accepted": False, "reason": "x"}

        def kill_switch_gateway(
            self,
            gw: str,
            note: str = "",
            *,
            symbol: str = "",
            quotes_only: bool = False,
        ) -> dict[str, Any]:
            return {"accepted": False, "reason": "x"}

    client = cast(ExchangeCommandClient, _Rejecting())
    assert console_mod.execute_command(client, "HALT", {})[0] is False
    assert console_mod.execute_command(client, "RESUME", {})[0] is False
    assert console_mod.execute_command(client, "KILL", {"GW": "TRADER01"})[0] is False
    assert (
        console_mod.execute_command(client, "QCANCEL", {"GW": "MM01", "SYM": "AAPL"})[0]
        is False
    )


def test_kill_and_qcancel_on_another_gateway_use_the_admin_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WP-API07: acting on another participant goes through the ADMIN kill
    switch, so the audit names the operator; the caller's own gateway keeps the
    self-service messages."""
    _capture_print(monkeypatch)
    fake = _FakeClient()
    client = cast(ExchangeCommandClient, fake)
    console_mod.execute_command(client, "KILL", {"GW": "MM01", "SYM": "AAPL"})
    console_mod.execute_command(client, "QCANCEL", {"GW": "MM01", "SYM": "AAPL"})
    console_mod.execute_command(client, "KILL", {"GW": "adm01"})
    console_mod.execute_command(client, "QCANCEL", {"GW": "ADM01", "SYM": "AAPL"})
    assert fake.calls == [
        ("kill_switch_gateway", ("MM01",), {"symbol": "AAPL", "quotes_only": False}),
        ("kill_switch_gateway", ("MM01",), {"symbol": "AAPL", "quotes_only": True}),
        ("kill_switch", ("adm01",), {"symbol": ""}),
        ("quote_cancel", ("ADM01", "AAPL"), {}),
    ]


def test_cmd_reopen_requires_sym(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())
    accepted, result = console_mod.execute_command(client, "REOPEN", {})
    assert accepted is False
    assert result == {}


def test_cmd_reopen_dry_run_passes_flag_and_prints_indicative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_print(monkeypatch)
    client = _FakeClient()
    accepted, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "REOPEN", {"SYM": "aapl", "DRY_RUN": "1"}
    )
    assert accepted is True
    name, args, kwargs = client.calls[-1]
    assert name == "force_uncross"
    assert args == ("aapl",)
    assert kwargs == {"price": None, "dry_run": True, "note": ""}
    assert result["dry_run"] is True
    printed = " ".join(str(a) for a, _ in calls)
    assert "DRY-RUN" in printed


def test_cmd_reopen_live_passes_price_and_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    client = _FakeClient()
    accepted, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client),
        "REOPEN",
        {"SYM": "AAPL", "PRICE": "100.5", "NOTE": "manual open"},
    )
    assert accepted is True
    name, args, kwargs = client.calls[-1]
    assert name == "force_uncross"
    assert kwargs == {"price": 100.5, "dry_run": False, "note": "manual open"}
    assert result["printed_price"] == 100.5
    assert result["traded_qty"] == 50


def test_cmd_reopen_invalid_price(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())
    accepted, result = console_mod.execute_command(
        client, "REOPEN", {"SYM": "AAPL", "PRICE": "abc"}
    )
    assert accepted is False
    assert result == {}


def test_cmd_reopen_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)

    class _Rejecting(_FakeClient):
        def force_uncross(
            self,
            symbol: str,
            price: float | None = None,
            *,
            dry_run: bool = False,
            note: str = "",
        ) -> dict[str, Any]:
            return {"accepted": False, "reason": "Unknown symbol: ZZZ"}

    client = cast(ExchangeCommandClient, _Rejecting())
    accepted, _result = console_mod.execute_command(client, "REOPEN", {"SYM": "ZZZ"})
    assert accepted is False


def test_cmd_position_requires_gw(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())
    accepted, result = console_mod.execute_command(client, "POSITION", {})
    assert accepted is False
    assert result == {}


def test_cmd_position_merges_position_and_quote_by_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    client = _FakeClient()
    accepted, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "POSITION", {"GW": "mm_aapl_01"}
    )
    assert accepted is True
    assert (result["gateway_id"], result["status"]) == ("MM_AAPL_01", "OK")
    rows = result["positions"]

    # position_snapshot() and quote_bootstrap() were both called with the
    # gateway id as given (case handled inside the client methods).
    names = [name for name, _, _ in client.calls]
    assert "position_snapshot" in names
    assert "quote_bootstrap" in names

    by_symbol = {row["symbol"]: row for row in rows}
    assert set(by_symbol) == {"AAPL", "MSFT"}

    # AAPL has both a position and an active quote -- bid/ask/spread/mid present.
    aapl = by_symbol["AAPL"]
    assert aapl["net_qty"] == 500
    assert aapl["avg_cost"] == 149.75
    assert aapl["bid_price"] == 149.70
    assert aapl["ask_price"] == 149.90
    assert aapl["spread"] == pytest.approx(0.20)
    assert aapl["mid"] == pytest.approx(149.80)

    # MSFT has a position but no active quote in the fake -- no bid/ask/spread/mid.
    msft = by_symbol["MSFT"]
    assert msft["net_qty"] == -200
    assert msft["avg_cost"] == 310.10
    assert "bid_price" not in msft
    assert "spread" not in msft


def test_cmd_position_symbol_filter_narrows_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())
    accepted, result = console_mod.execute_command(
        client, "POSITION", {"GW": "MM_AAPL_01", "SYM": "aapl"}
    )
    assert accepted is True
    assert [row["symbol"] for row in result["positions"]] == ["AAPL"]


def test_cmd_position_quote_only_symbol_with_no_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symbol with an active quote but no recorded position still appears,
    with net_qty/avg_cost defaulted to flat."""
    _capture_print(monkeypatch)

    class _QuoteOnly(_FakeClient):
        def position_snapshot(self, target_gw: str) -> list[dict[str, Any]]:
            return []

        def quote_bootstrap(
            self, target_gw: str, symbol: str = ""
        ) -> list[dict[str, Any]]:
            return [{"symbol": "AAPL", "bid_price": 100.0, "ask_price": 100.20}]

    client = cast(ExchangeCommandClient, _QuoteOnly())
    accepted, result = console_mod.execute_command(client, "POSITION", {"GW": "MM01"})
    assert accepted is True
    rows = result["positions"]
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["net_qty"] == 0
    assert rows[0]["avg_cost"] == 0.0
    assert rows[0]["bid_price"] == 100.0


def test_cmd_position_no_position_and_no_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)

    class _Empty(_FakeClient):
        def position_snapshot(self, target_gw: str) -> list[dict[str, Any]]:
            return []

        def quote_bootstrap(
            self, target_gw: str, symbol: str = ""
        ) -> list[dict[str, Any]]:
            return []

    client = cast(ExchangeCommandClient, _Empty())
    accepted, result = console_mod.execute_command(client, "POSITION", {"GW": "MM01"})
    assert accepted is True
    assert result["positions"] == []


def test_cmd_position_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    rich_calls = _capture_print(monkeypatch)
    plain_calls: list[Any] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: plain_calls.append((a, kw)))
    client = cast(ExchangeCommandClient, _FakeClient())
    accepted, rows = console_mod.execute_command(
        client, "POSITION", {"GW": "MM_AAPL_01"}, json_output=True
    )
    assert accepted is True
    assert rich_calls == []
    assert len(plain_calls) == 1
    (printed_text,), _kw = plain_calls[0]
    assert json.loads(printed_text) == rows


def test_admin_dispatch_help_exit_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    printed = _capture_print(monkeypatch)

    fake_client = _FakeClient()

    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda gw: fake_client)
    c = console_mod.AdminConsole("gw_admin")

    c._dispatch("HELP", {})
    assert printed

    with pytest.raises(SystemExit):
        c._dispatch("EXIT", {})

    def _boom(*args: Any, **kwargs: Any) -> bool:
        raise CommandTimeoutError("timeout")

    monkeypatch.setattr(console_mod, "execute_command", _boom)
    c._dispatch("HALT", {})


def test_admin_run_timeout_and_auth_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)

    class _TimeoutClient(_FakeClient):
        def connect(self) -> dict[str, Any]:
            raise CommandTimeoutError("no ack")

        def close(self) -> None:
            self.calls.append(("close", (), {}))

    timeout_client = _TimeoutClient()
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda gw: timeout_client)
    console_mod.AdminConsole("GW_ADMIN").run()
    assert any(name == "close" for name, _, _ in timeout_client.calls)

    class _RefusedClient(_FakeClient):
        def connect(self) -> dict[str, Any]:
            return {"accepted": False, "reason": "not admin"}

        def close(self) -> None:
            self.calls.append(("close", (), {}))

    refused_client = _RefusedClient()
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda gw: refused_client)
    console_mod.AdminConsole("GW_ADMIN").run()
    assert any(name == "close" for name, _, _ in refused_client.calls)


def test_admin_run_happy_path_disconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)

    class _HappyClient(_FakeClient):
        def connect(self) -> dict[str, Any]:
            return {"accepted": True, "description": "ops"}

        def disconnect(self) -> None:
            self.calls.append(("disconnect", (), {}))

        def close(self) -> None:
            self.calls.append(("close", (), {}))

    happy_client = _HappyClient()
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda gw: happy_client)

    class _FakePromptSession:
        def __init__(self, **kwargs: Any) -> None:
            self._count = 0

        def prompt(self, prompt_str: Any, **_kwargs: Any) -> str:
            self._count += 1
            if self._count == 1:
                return "EXIT"
            raise EOFError

    monkeypatch.setattr(console_mod, "PromptSession", _FakePromptSession)
    monkeypatch.setattr(console_mod, "pt_patch_stdout", lambda raw=True: nullcontext())

    console_mod.AdminConsole("GW_ADMIN").run()

    names = [name for name, _, _ in happy_client.calls]
    assert "disconnect" in names
    assert "close" in names


def test_admin_run_logs_out_when_engine_connection_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed = _capture_print(monkeypatch)

    class _ConnectedClient(_FakeClient):
        def connect(self) -> dict[str, Any]:
            return {"accepted": True}

        def symbol_list(self) -> list[str]:
            return []

        def disconnect(self) -> None:
            self.calls.append(("disconnect", (), {}))

        def close(self) -> None:
            self.calls.append(("close", (), {}))

    client = _ConnectedClient()
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: client)

    def _lost_connection(*_args: Any, **_kwargs: Any) -> None:
        raise zmq.Again()

    monkeypatch.setattr(console_mod, "execute_command", _lost_connection)

    class _FakePromptSession:
        def __init__(self, **_kwargs: Any) -> None:
            self.prompt_count = 0

        def prompt(self, _prompt_str: Any, **_kwargs: Any) -> str:
            self.prompt_count += 1
            assert self.prompt_count == 1
            return "KILL"

    session = _FakePromptSession()
    monkeypatch.setattr(console_mod, "PromptSession", lambda **_kwargs: session)
    monkeypatch.setattr(console_mod, "pt_patch_stdout", lambda raw=True: nullcontext())

    console_mod.AdminConsole("GW_ADMIN").run()

    assert session.prompt_count == 1
    assert any("Engine connection was lost" in str(args) for args, _ in printed)
    names = [name for name, _, _ in client.calls]
    assert "disconnect" not in names
    assert "close" in names


def test_admin_disconnect_monitor_logs_out_idle_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: _FakeClient())
    monkeypatch.setattr(
        console_mod,
        "recv_monitor_message",
        lambda _monitor: {"event": zmq.EVENT_DISCONNECTED},
    )
    monitor = MagicMock()
    monitor.poll.return_value = 1
    app = MagicMock()

    admin = console_mod.AdminConsole("GW_ADMIN")
    asyncio.run(admin._watch_engine_disconnect(app, monitor))

    assert admin._connection_lost is True
    app.exit.assert_called_once_with(exception=KeyboardInterrupt)


def test_admin_engine_peer_disconnect_logs_out_idle_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    context: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    peer = context.socket(zmq.PULL)
    port = peer.bind_to_random_port("tcp://127.0.0.1")
    push = make_pusher(f"tcp://127.0.0.1:{port}")
    client = ExchangeCommandClient("GW_ADMIN", _push_sock=push, _sub_sock=None)
    monitor = client.engine_disconnect_monitor()
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: client)
    admin = console_mod.AdminConsole("GW_ADMIN")
    app = MagicMock()

    try:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                client._send([b"probe", b"{}"])
                break
            except zmq.Again:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        assert peer.poll(5000, zmq.POLLIN)
        peer.recv_multipart()
        peer.close(linger=0)

        asyncio.run(
            asyncio.wait_for(admin._watch_engine_disconnect(app, monitor), timeout=5.0)
        )

        assert admin._connection_lost is True
        app.exit.assert_called_once_with(exception=KeyboardInterrupt)
    finally:
        client.close_engine_disconnect_monitor(monitor)
        client.close()
        push.close(linger=0)
        peer.close(linger=0)


def test_main_parses_id_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}

    class _FakeAdmin:
        def __init__(self, gw_id: str) -> None:
            observed["gw_id"] = gw_id

        def run(self) -> int:
            observed["ran"] = True
            return 0

    monkeypatch.setattr(console_mod, "AdminConsole", _FakeAdmin)
    monkeypatch.setattr(sys, "argv", ["pm-admin", "--id", "GW_ADMIN"])

    with pytest.raises(SystemExit) as exc:
        console_mod.main()
    assert exc.value.code == 0
    assert observed == {"gw_id": "GW_ADMIN", "ran": True}


# ---------------------------------------------------------------------------
# WP-FL02 (L029): the console tells the engine it is alive
# ---------------------------------------------------------------------------


class _RecordingPusher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        from edumatcher.models.message import decode

        self.sent.append(decode(frames))

    def close(self, linger: int | None = None) -> None:
        self.closed = True


def test_admin_run_heartbeats_while_logged_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Since the engine times out a session that never beats, an idle
    console must beat, on a socket of its own (ZMQ sockets are not shared
    across threads), from logon until it logs off."""
    _capture_print(monkeypatch)

    class _HappyClient(_FakeClient):
        def connect(self) -> dict[str, Any]:
            return {"accepted": True}

        def symbol_list(self) -> list[str]:
            return []

        def disconnect(self) -> None:
            self.calls.append(("disconnect", (), {}))

        def close(self) -> None:
            self.calls.append(("close", (), {}))

    monkeypatch.setattr(
        console_mod, "ExchangeCommandClient", lambda _gw: _HappyClient()
    )
    pusher = _RecordingPusher()
    monkeypatch.setattr(console_mod, "make_pusher", lambda _addr: pusher)

    class _FakePromptSession:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prompt(self, _prompt_str: Any, **_kwargs: Any) -> str:
            return "EXIT"

    monkeypatch.setattr(console_mod, "PromptSession", _FakePromptSession)
    monkeypatch.setattr(console_mod, "pt_patch_stdout", lambda raw=True: nullcontext())

    console_mod.AdminConsole("GW_ADMIN").run()

    assert pusher.sent and pusher.sent[0][0] == "system.gateway_heartbeat"
    assert pusher.sent[0][1]["gateway_id"] == "GW_ADMIN"
    assert pusher.closed


def test_admin_heartbeat_loop_beats_until_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: _FakeClient())
    pusher = _RecordingPusher()
    monkeypatch.setattr(console_mod, "make_pusher", lambda _addr: pusher)
    c = console_mod.AdminConsole("GW_ADMIN")
    c._heartbeat_stop.set()

    c._heartbeat_loop()

    assert [t for t, _ in pusher.sent] == ["system.gateway_heartbeat"]
    assert pusher.closed


def test_admin_heartbeat_loop_survives_an_unreachable_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: _FakeClient())

    class _Unreachable(_RecordingPusher):
        def send_multipart(self, frames: list[bytes]) -> None:
            raise zmq.Again()

    pusher = _Unreachable()
    monkeypatch.setattr(console_mod, "make_pusher", lambda _addr: pusher)
    c = console_mod.AdminConsole("GW_ADMIN")
    c._heartbeat_stop.set()

    c._heartbeat_loop()

    assert pusher.closed


# -- BOOK prints prices readably (For-Later L006, L008; WP-FL17) ----------------


def _book_text(monkeypatch: pytest.MonkeyPatch, book: dict[str, Any]) -> str:
    from rich.console import Console

    recorder = Console(record=True, width=120)
    monkeypatch.setattr(console_mod, "console", recorder)
    console_mod._print_book(book)
    return recorder.export_text()


@pytest.mark.parametrize(
    ("tick_decimals", "bid", "ask", "shown_bid", "shown_ask"),
    [(2, 149.8, 150.1, "149.80", "150.10"), (3, 12.5, 12.505, "12.500", "12.505")],
)
def test_book_prices_are_printed_at_the_symbols_scale(
    monkeypatch: pytest.MonkeyPatch,
    tick_decimals: int,
    bid: float,
    ask: float,
    shown_bid: str,
    shown_ask: str,
) -> None:
    text = _book_text(
        monkeypatch,
        {
            "symbol": "AAPL",
            "tick_decimals": tick_decimals,
            "bids": [{"price": bid, "qty": 100}],
            "asks": [{"price": ask, "qty": 50}],
            "last_price": bid,
            "last_qty": 10,
        },
    )
    assert shown_bid in text and shown_ask in text
    assert f"Last trade: {shown_bid} × 10" in text


def test_a_restored_last_price_without_its_quantity_prints_the_price_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After an engine restart book_stats.json gives the price, not the
    quantity: "150.0 × None" was printed."""
    text = _book_text(
        monkeypatch,
        {
            "symbol": "AAPL",
            "tick_decimals": 2,
            "bids": [{"price": 149.0, "qty": 100}],
            "asks": [],
            "last_price": 150.0,
            "last_qty": None,
        },
    )
    assert "Last trade: 150.00" in text
    assert "None" not in text


# ---------------------------------------------------------------------------
# WP-ADM03 — a mistyped gateway id fails every targeted command
# ---------------------------------------------------------------------------


def _text(calls: list[Any]) -> str:
    return " ".join(str(a) for args, _ in calls for a in args)


def test_orders_of_an_unknown_gateway_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    printed = _capture_print(monkeypatch)
    client = _FakeClient(query_status="UNKNOWN_GATEWAY")
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "ORDERS", {"GW": "nosuch01"}
    )
    assert ok is False
    assert result["status"] == "UNKNOWN_GATEWAY"
    assert "Gateway not configured: NOSUCH01" in _text(printed)


def test_orders_json_carries_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    plain: list[Any] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: plain.append(a))
    client = _FakeClient(query_status="UNKNOWN_GATEWAY")
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client),
        "ORDERS",
        {"GW": "NOSUCH01"},
        json_output=True,
    )
    assert ok is False
    assert json.loads(plain[0][0]) == result
    assert result["status"] == "UNKNOWN_GATEWAY"


def test_orders_of_a_disconnected_gateway_say_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed = _capture_print(monkeypatch)
    client = _FakeClient(query_status="NOT_CONNECTED")
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "ORDERS", {"GW": "TRADER02"}
    )
    assert ok is True
    assert len(result["orders"]) == 1
    assert "not connected" in _text(printed)


def test_position_of_an_unknown_gateway_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    printed = _capture_print(monkeypatch)
    client = _FakeClient(query_status="UNKNOWN_GATEWAY")
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "POSITION", {"GW": "NOSUCH01"}
    )
    assert ok is False
    assert result["status"] == "UNKNOWN_GATEWAY"
    assert "Gateway not configured: NOSUCH01" in _text(printed)


def test_position_of_a_disconnected_gateway_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed = _capture_print(monkeypatch)
    client = _FakeClient(query_status="NOT_CONNECTED")
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "POSITION", {"GW": "MM_AAPL_01"}
    )
    assert ok is True and result["status"] == "NOT_CONNECTED"
    assert "not connected" in _text(printed)


@pytest.mark.parametrize(
    "gw,reason",
    [
        ("NOSUCH01", "Gateway not configured: NOSUCH01"),
        ("trader02", "Gateway not connected: TRADER02"),
    ],
)
def test_kick_refuses_an_unknown_or_disconnected_gateway(
    monkeypatch: pytest.MonkeyPatch, gw: str, reason: str
) -> None:
    printed = _capture_print(monkeypatch)
    client = _FakeClient()
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "KICK", {"GW": gw}
    )
    assert ok is False
    assert result["reason"] == reason and reason in _text(printed)
    assert "gateway_kick" not in [c[0] for c in client.calls]


def test_kick_of_a_connected_gateway_sends_the_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    client = _FakeClient()
    ok, result = console_mod.execute_command(
        cast(ExchangeCommandClient, client),
        "KICK",
        {"GW": "trader01", "REASON": "hold"},
    )
    assert ok is True and result == {"gateway_id": "TRADER01"}
    assert ("gateway_kick", ("trader01",), {"reason": "hold"}) in client.calls


# ---------------------------------------------------------------------------
# WP-ADM04 — no typed line or lost engine ends with a traceback; exit codes
# ---------------------------------------------------------------------------


class _ScriptedSession:
    """A PromptSession that answers with *lines*, then EOF."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self.app = MagicMock()

    def prompt(self, _prompt_str: Any, **_kwargs: Any) -> str:
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


class _LoggedOnClient(_FakeClient):
    def connect(self) -> dict[str, Any]:
        return {"accepted": True}

    def disconnect(self) -> None:
        self.calls.append(("disconnect", (), {}))

    def close(self) -> None:
        self.calls.append(("close", (), {}))


def _run_console(
    monkeypatch: pytest.MonkeyPatch, client: _FakeClient, lines: list[str]
) -> int:
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: client)
    monkeypatch.setattr(
        console_mod, "PromptSession", lambda **_kw: _ScriptedSession(lines)
    )
    monkeypatch.setattr(console_mod, "pt_patch_stdout", lambda raw=True: nullcontext())
    return console_mod.AdminConsole("GW_ADMIN").run()


def test_run_returns_one_when_it_never_got_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)

    class _Timeout(_LoggedOnClient):
        def connect(self) -> dict[str, Any]:
            raise CommandTimeoutError("no ack")

    class _Refused(_LoggedOnClient):
        def connect(self) -> dict[str, Any]:
            return {"accepted": False, "reason": "Gateway already connected"}

    assert _run_console(monkeypatch, _Timeout(), []) == 1
    assert _run_console(monkeypatch, _Refused(), []) == 1


def test_run_returns_zero_on_exit_and_one_on_a_lost_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    assert _run_console(monkeypatch, _LoggedOnClient(), ["EXIT"]) == 0

    def _lost(*_a: Any, **_k: Any) -> None:
        raise zmq.Again()

    monkeypatch.setattr(console_mod, "execute_command", _lost)
    assert _run_console(monkeypatch, _LoggedOnClient(), ["HALT"]) == 1


def test_main_exits_with_the_console_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingAdmin:
        def __init__(self, _gw_id: str) -> None:
            pass

        def run(self) -> int:
            return 1

    monkeypatch.setattr(console_mod, "AdminConsole", _FailingAdmin)
    monkeypatch.setattr(sys, "argv", ["pm-admin", "--id", "GW_ADMIN"])
    with pytest.raises(SystemExit) as exc:
        console_mod.main()
    assert exc.value.code == 1


@pytest.fixture
def rich_text(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Render through a real rich Console, so markup is really parsed."""
    import io

    from rich.console import Console

    buf = io.StringIO()
    monkeypatch.setattr(
        console_mod, "console", Console(file=buf, force_terminal=False, width=200)
    )
    return buf


@pytest.mark.parametrize(
    "line",
    [
        "ORDERS|GW=[/x]",
        "LEVEL|SYM=AAPL|PRICE=[/b]",
        "[/q]",
        "REOPEN|SYM=AAPL|PRICE=[/p]",
        "KILL|GW=[/x]",
    ],
)
def test_typed_markup_is_printed_literally(
    monkeypatch: pytest.MonkeyPatch, rich_text: Any, line: str
) -> None:
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: _FakeClient())
    console_mod.AdminConsole("GW_ADMIN")._dispatch(*console_mod._parse(line))
    assert "[/" in rich_text.getvalue()


def test_an_engine_reason_with_markup_is_printed_literally(
    monkeypatch: pytest.MonkeyPatch, rich_text: Any
) -> None:
    class _Refusing(_FakeClient):
        def symbol_halt(self, sym: str) -> dict[str, Any]:
            return {"accepted": False, "reason": f"Unknown symbol: {sym.upper()}"}

    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: _Refusing())
    console_mod.AdminConsole("GW_ADMIN")._dispatch("HALT_SYM", {"SYM": "[/x]"})
    assert "Unknown symbol: [/X]" in rich_text.getvalue()


def test_a_failing_command_does_not_end_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed = _capture_print(monkeypatch)
    calls = {"n": 0}

    def _boom(*_a: Any, **_k: Any) -> None:
        calls["n"] += 1
        raise RuntimeError("malformed reply")

    monkeypatch.setattr(console_mod, "execute_command", _boom)
    client = _LoggedOnClient()
    assert _run_console(monkeypatch, client, ["HALT", "VOLUME", "EXIT"]) == 0
    assert calls["n"] == 2  # the second line was still read and run
    assert any("Command failed" in str(args) for args, _ in printed)
    assert "disconnect" in [c[0] for c in client.calls]


# ---------------------------------------------------------------------------
# WP-ADM05 — prices and ids as they are; bad numbers refused locally
# ---------------------------------------------------------------------------


def test_the_repl_console_still_forces_ansi() -> None:
    """patch_stdout hides the terminal from rich; the REPL must colour anyway."""
    assert console_mod.console.is_terminal


@pytest.mark.parametrize(
    "line",
    [
        "REOPEN|SYM=AAPL|PRICE=nan",
        "REOPEN|SYM=AAPL|PRICE=inf",
        "REOPEN|SYM=AAPL|PRICE=0",
        "LEVEL|SYM=AAPL|PRICE=-1",
        "LEVEL|SYM=AAPL|PRICE=nan",
    ],
)
def test_a_non_finite_or_non_positive_price_is_refused_locally(
    monkeypatch: pytest.MonkeyPatch, line: str
) -> None:
    printed = _capture_print(monkeypatch)
    client = _FakeClient()
    ok, _ = console_mod.execute_command(
        cast(ExchangeCommandClient, client), *console_mod._parse(line)
    )
    assert ok is False
    assert "Invalid PRICE" in _text(printed)
    assert [c[0] for c in client.calls] == []  # nothing was sent


def _orders_table(monkeypatch: pytest.MonkeyPatch, rich_text: Any, line: str) -> str:
    class _Orders(_FakeClient):
        def order_list(self, gw: str) -> list[dict[str, Any]]:
            return _ORDERS

        def price_level_orders(
            self, sym: str, price: float | None = None
        ) -> dict[str, Any]:
            return {"symbol": sym, "rejected": False, "orders": _ORDERS}

    console_mod.execute_command(
        cast(ExchangeCommandClient, _Orders()), *console_mod._parse(line)
    )
    return str(rich_text.getvalue())


_ORDERS = [
    {
        "id": "0123456789abcdef0123456789abcdef",
        "gateway_id": "GW01",
        "symbol": "AAPL",
        "side": "BUY",
        "order_type": "LIMIT",
        "remaining_qty": 10,
        "price": 149.5,
        "stop_price": None,
        "tick_decimals": 2,
    },
    {
        "id": "fedcba9876543210fedcba9876543210",
        "gateway_id": "GW02",
        "symbol": "XYZ",
        "side": "SELL",
        "order_type": "STOP",
        "remaining_qty": 5,
        "price": None,
        "stop_price": 12.5,
        "tick_decimals": 3,
    },
]


@pytest.mark.parametrize("line", ["ORDERS|GW=GW01", "LEVEL|SYM=AAPL"])
def test_orders_and_level_show_full_ids_and_prices_at_scale(
    monkeypatch: pytest.MonkeyPatch, rich_text: Any, line: str
) -> None:
    out = _orders_table(monkeypatch, rich_text, line)
    assert "0123456789abcdef0123456789abcdef" in out
    assert "149.50" in out
    assert "stop 12.500" in out


def test_reopen_prints_prices_at_the_symbols_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed = _capture_print(monkeypatch)
    console_mod.execute_command(
        cast(ExchangeCommandClient, _FakeClient()), "REOPEN", {"SYM": "AAPL"}
    )
    assert "printed=100.00 x 50" in _text(printed)
    assert "indicative was 100.00 x 50" in _text(printed)


def test_position_spread_and_mid_are_rounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    _, result = console_mod.execute_command(
        cast(ExchangeCommandClient, _FakeClient()), "POSITION", {"GW": "MM01"}
    )
    aapl = next(r for r in result["positions"] if r["symbol"] == "AAPL")
    assert aapl["spread"] == 0.2
    assert aapl["mid"] == 149.8


def test_reopen_looks_up_the_scale_before_it_changes_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Holistic review HR1: a display lookup after the uncross could time out
    and report an executed REOPEN as TIMEOUT. It runs first, so a timeout
    means nothing was sent."""
    _capture_print(monkeypatch)

    class _SlowSymbols(_FakeClient):
        def tick_decimals(self, symbol: str) -> int | None:
            self.calls.append(("tick_decimals", (symbol,), {}))
            raise CommandTimeoutError("no symbols reply")

    client = _SlowSymbols()
    with pytest.raises(CommandTimeoutError):
        console_mod.execute_command(
            cast(ExchangeCommandClient, client), "REOPEN", {"SYM": "AAPL"}
        )
    assert [c[0] for c in client.calls] == ["tick_decimals"]


def test_reopen_json_needs_no_scale_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

    class _NoSymbols(_FakeClient):
        def tick_decimals(self, symbol: str) -> int | None:
            raise AssertionError("JSON output prints raw values")

    ok, _ = console_mod.execute_command(
        cast(ExchangeCommandClient, _NoSymbols()),
        "REOPEN",
        {"SYM": "AAPL"},
        json_output=True,
    )
    assert ok is True
