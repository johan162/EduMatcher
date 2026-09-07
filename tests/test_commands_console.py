from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import json
import sys
from typing import Any, cast

import pytest

from edumatcher.commands import ExchangeCommandClient
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from edumatcher.commands import CommandTimeoutError
from edumatcher.commands import console as console_mod


@dataclass
class _FakeClient:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )

    def halt_all(self) -> dict[str, Any]:
        self.calls.append(("halt_all", (), {}))
        return {"accepted": True, "halted_symbols": 2, "cancelled_quotes": 4}

    def resume_all(self) -> dict[str, Any]:
        self.calls.append(("resume_all", (), {}))
        return {"accepted": True, "resumed_symbols": 2}

    def kill_switch(self, gw: str, symbol: str = "") -> dict[str, Any]:
        self.calls.append(("kill_switch", (gw,), {"symbol": symbol}))
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
            }
        ]

    def volume(self) -> dict[str, Any]:
        self.calls.append(("volume", (), {}))
        return {
            "symbols": {"AAPL": {"qty": 10, "value": 1500.0, "trades": 2}},
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

    def quote_bootstrap(self, target_gw: str, symbol: str = "") -> list[dict[str, Any]]:
        self.calls.append(("quote_bootstrap", (target_gw,), {"symbol": symbol}))
        quotes = [
            {"symbol": "AAPL", "bid_price": 149.70, "ask_price": 149.90},
        ]
        if symbol:
            quotes = [q for q in quotes if q["symbol"] == symbol.upper()]
        return quotes


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
        {"symbols": {}, "total_qty": 0, "total_value": 0.0, "total_trades": 0}
    )
    console_mod._print_volume(
        {
            "symbols": {"AAPL": {"qty": 1, "value": 10.0, "trades": 1}},
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

    client = cast(ExchangeCommandClient, _Rejecting())
    assert console_mod.execute_command(client, "HALT", {})[0] is False
    assert console_mod.execute_command(client, "RESUME", {})[0] is False
    assert console_mod.execute_command(client, "KILL", {"GW": "TRADER01"})[0] is False
    assert (
        console_mod.execute_command(client, "QCANCEL", {"GW": "MM01", "SYM": "AAPL"})[0]
        is False
    )


def test_cmd_position_requires_gw(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_print(monkeypatch)
    client = cast(ExchangeCommandClient, _FakeClient())
    accepted, result = console_mod.execute_command(client, "POSITION", {})
    assert accepted is False
    assert result == []


def test_cmd_position_merges_position_and_quote_by_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_print(monkeypatch)
    client = _FakeClient()
    accepted, rows = console_mod.execute_command(
        cast(ExchangeCommandClient, client), "POSITION", {"GW": "mm_aapl_01"}
    )
    assert accepted is True

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
    accepted, rows = console_mod.execute_command(
        client, "POSITION", {"GW": "MM_AAPL_01", "SYM": "aapl"}
    )
    assert accepted is True
    assert [row["symbol"] for row in rows] == ["AAPL"]


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
    accepted, rows = console_mod.execute_command(client, "POSITION", {"GW": "MM01"})
    assert accepted is True
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
    accepted, rows = console_mod.execute_command(client, "POSITION", {"GW": "MM01"})
    assert accepted is True
    assert rows == []


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

        def prompt(self, prompt_str: Any) -> str:
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


def test_main_parses_id_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}

    class _FakeAdmin:
        def __init__(self, gw_id: str) -> None:
            observed["gw_id"] = gw_id

        def run(self) -> None:
            observed["ran"] = True

    monkeypatch.setattr(console_mod, "AdminConsole", _FakeAdmin)
    monkeypatch.setattr(sys, "argv", ["pm-admin", "--id", "GW_ADMIN"])

    console_mod.main()
    assert observed == {"gw_id": "GW_ADMIN", "ran": True}
