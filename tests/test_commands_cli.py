from __future__ import annotations

from dataclasses import dataclass, field
import json
import sys
from typing import Any

import pytest

from edumatcher.commands import CommandTimeoutError
from edumatcher.commands import cli as cli_mod
from edumatcher.commands import console as console_mod
from edumatcher.commands.console import _COMMAND_HANDLERS


@pytest.fixture(autouse=True)
def _restore_shared_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() swaps the console the REPL shares for a detecting one."""
    monkeypatch.setattr(console_mod, "console", console_mod.console)


@dataclass
class _FakeClient:
    gw_id: str
    push_addr: str
    pub_addr: str
    timeout_ms: int
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )
    auth_response: dict[str, Any] = field(default_factory=lambda: {"accepted": True})
    raise_on_connect: bool = False

    def connect(self) -> dict[str, Any]:
        self.calls.append(("connect", (), {}))
        if self.raise_on_connect:
            raise CommandTimeoutError("no ack")
        return self.auth_response

    def disconnect(self) -> None:
        self.calls.append(("disconnect", (), {}))

    def close(self) -> None:
        self.calls.append(("close", (), {}))


def test_build_parser_parses_session_status_and_defaults() -> None:
    parser = cli_mod.build_parser()
    args = parser.parse_args(["--id", "GW_ADMIN", "session-status"])
    assert args.id == "GW_ADMIN"
    assert args.command == "session-status"
    assert args.timeout == 3000


def test_pm_admin_does_not_expose_alf_console_index_command() -> None:
    assert "INDEX" not in _COMMAND_HANDLERS


def test_build_parser_enforces_required_fields_and_state_upper() -> None:
    parser = cli_mod.build_parser()

    args = parser.parse_args(["--id", "GW_ADMIN", "kill", "--gw", "TRADER01"])
    assert args.gw == "TRADER01"
    assert args.sym == ""

    args2 = parser.parse_args(["--id", "GW_ADMIN", "session", "--state", "continuous"])
    assert args2.state == "CONTINUOUS"

    args3 = parser.parse_args(["--id", "GW_ADMIN", "level", "--sym", "AAPL"])
    assert args3.sym == "AAPL"
    assert args3.price == ""

    args4 = parser.parse_args(
        ["--id", "GW_ADMIN", "level", "--sym", "AAPL", "--price", "149.50"]
    )
    assert args4.price == "149.50"


def test_build_parser_format_defaults_to_text_and_accepts_json() -> None:
    parser = cli_mod.build_parser()

    args = parser.parse_args(["--id", "GW_ADMIN", "symbols"])
    assert args.format == "text"

    args2 = parser.parse_args(["--id", "GW_ADMIN", "--format", "json", "symbols"])
    assert args2.format == "json"

    with pytest.raises(SystemExit):
        parser.parse_args(["--id", "GW_ADMIN", "--format", "xml", "symbols"])


def test_build_parser_position_requires_gw_and_accepts_sym() -> None:
    parser = cli_mod.build_parser()

    args = parser.parse_args(["--id", "GW_ADMIN", "position", "--gw", "MM_AAPL_01"])
    assert args.gw == "MM_AAPL_01"
    assert args.sym == ""

    args2 = parser.parse_args(
        ["--id", "GW_ADMIN", "position", "--gw", "MM_AAPL_01", "--sym", "AAPL,MSFT"]
    )
    assert args2.sym == "AAPL,MSFT"

    with pytest.raises(SystemExit):
        parser.parse_args(["--id", "GW_ADMIN", "position"])


def test_args_to_fields_maps_only_present_keys() -> None:
    class _Args:
        gw = "TRADER01"
        sym = "AAPL"
        reason = "Compliance"
        state = "CONTINUOUS"
        price = "149.50"

    fields = cli_mod._args_to_fields(_Args)
    assert fields == {
        "GW": "TRADER01",
        "SYM": "AAPL",
        "REASON": "Compliance",
        "STATE": "CONTINUOUS",
        "PRICE": "149.50",
    }

    class _Args2:
        gw = None
        sym = ""
        reason = None
        state = None
        price = ""

    assert cli_mod._args_to_fields(_Args2) == {}


def test_build_parser_reopen_parses_sym_price_dry_run_note() -> None:
    parser = cli_mod.build_parser()

    args = parser.parse_args(["--id", "GW_ADMIN", "reopen", "--sym", "AAPL"])
    assert args.command == "reopen"
    assert args.sym == "AAPL"
    assert args.price is None
    assert args.dry_run is False
    assert args.note == ""

    args2 = parser.parse_args(
        [
            "--id",
            "GW_ADMIN",
            "reopen",
            "--sym",
            "AAPL",
            "--price",
            "100.5",
            "--dry-run",
            "--note",
            "manual open",
        ]
    )
    assert args2.price == 100.5
    assert args2.dry_run is True
    assert args2.note == "manual open"

    with pytest.raises(SystemExit):
        parser.parse_args(["--id", "GW_ADMIN", "reopen"])  # --sym is required


def test_args_to_fields_maps_reopen_price_dry_run_note() -> None:
    class _Args:
        sym = "AAPL"
        price = 100.5
        dry_run = True
        note = "manual open"

    assert cli_mod._args_to_fields(_Args) == {
        "SYM": "AAPL",
        "PRICE": "100.5",
        "DRY_RUN": "1",
        "NOTE": "manual open",
    }

    class _Args2:
        sym = "AAPL"
        price = None
        dry_run = False
        note = ""

    assert cli_mod._args_to_fields(_Args2) == {"SYM": "AAPL"}


def test_main_success_executes_and_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}

    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        c = _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )
        created["client"] = c
        return c

    seen: dict[str, Any] = {}

    def _exec(
        client: Any, cmd: str, fields: dict[str, str], *, json_output: bool = False
    ) -> tuple[bool, Any]:
        seen["cmd"] = cmd
        seen["fields"] = fields
        seen["json_output"] = json_output
        return True, {}

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(cli_mod, "execute_command", _exec)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-admin-cli",
            "--id",
            "GW_ADMIN",
            "--push",
            "tcp://127.0.0.1:5555",
            "--sub",
            "tcp://127.0.0.1:5556",
            "--timeout",
            "5000",
            "kill",
            "--gw",
            "TRADER01",
            "--sym",
            "AAPL",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 0
    c = created["client"]
    assert c.gw_id == "GW_ADMIN"
    assert c.timeout_ms == 5000
    assert seen["cmd"] == "KILL"
    assert seen["fields"] == {"GW": "TRADER01", "SYM": "AAPL"}
    names = [name for name, _, _ in c.calls]
    assert "disconnect" in names
    assert "close" in names


def test_main_format_json_propagates_to_execute_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        return _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )

    seen: dict[str, Any] = {}

    def _exec(
        client: Any, cmd: str, fields: dict[str, str], *, json_output: bool = False
    ) -> tuple[bool, Any]:
        seen["json_output"] = json_output
        seen["cmd"] = cmd
        seen["fields"] = fields
        return True, {"gateway_id": fields.get("GW", "")}

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(cli_mod, "execute_command", _exec)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-admin-cli",
            "--id",
            "GW_ADMIN",
            "--format",
            "json",
            "position",
            "--gw",
            "MM_AAPL_01",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 0
    assert seen["json_output"] is True
    assert seen["cmd"] == "POSITION"
    assert seen["fields"] == {"GW": "MM_AAPL_01"}


def test_main_normalizes_hyphen_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        return _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )

    observed: dict[str, Any] = {}

    def _exec(
        client: Any, cmd: str, fields: dict[str, str], *, json_output: bool = False
    ) -> tuple[bool, Any]:
        observed["cmd"] = cmd
        return True, {}

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(cli_mod, "execute_command", _exec)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-admin-cli", "--id", "GW_ADMIN", "session-status"],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 0
    assert observed["cmd"] == "SESSION_STATUS"


def test_main_reopen_maps_command_and_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        return _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )

    seen: dict[str, Any] = {}

    def _exec(
        client: Any, cmd: str, fields: dict[str, str], *, json_output: bool = False
    ) -> tuple[bool, Any]:
        seen["cmd"] = cmd
        seen["fields"] = fields
        return True, {}

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(cli_mod, "execute_command", _exec)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-admin-cli",
            "--id",
            "GW_ADMIN",
            "reopen",
            "--sym",
            "AAPL",
            "--price",
            "100.5",
            "--dry-run",
            "--note",
            "manual open",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 0
    assert seen["cmd"] == "REOPEN"
    assert seen["fields"] == {
        "SYM": "AAPL",
        "PRICE": "100.5",
        "DRY_RUN": "1",
        "NOTE": "manual open",
    }


def test_main_connect_timeout_exits_one_and_closes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created: dict[str, Any] = {}

    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        c = _FakeClient(
            gw_id=gw_id,
            push_addr=push_addr,
            pub_addr=pub_addr,
            timeout_ms=timeout_ms,
            raise_on_connect=True,
        )
        created["client"] = c
        return c

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-admin-cli", "--id", "GW_ADMIN", "symbols"],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Connection timed out" in err
    names = [name for name, _, _ in created["client"].calls]
    assert "close" in names


def test_main_auth_refused_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created: dict[str, Any] = {}

    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        c = _FakeClient(
            gw_id=gw_id,
            push_addr=push_addr,
            pub_addr=pub_addr,
            timeout_ms=timeout_ms,
            auth_response={"accepted": False, "reason": "Not ADMIN"},
        )
        created["client"] = c
        return c

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-admin-cli", "--id", "GW_ADMIN", "symbols"],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Auth refused" in err
    names = [name for name, _, _ in created["client"].calls]
    assert "close" in names


def test_main_execute_timeout_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created: dict[str, Any] = {}

    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        c = _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )
        created["client"] = c
        return c

    def _exec(
        client: Any, cmd: str, fields: dict[str, str], *, json_output: bool = False
    ) -> tuple[bool, Any]:
        raise CommandTimeoutError("late ack")

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(cli_mod, "execute_command", _exec)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-admin-cli", "--id", "GW_ADMIN", "symbols"],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Timeout:" in err
    names = [name for name, _, _ in created["client"].calls]
    assert "disconnect" in names
    assert "close" in names


def test_main_execute_rejected_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        return _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )

    monkeypatch.setattr(cli_mod, "ExchangeCommandClient", _make_client)
    monkeypatch.setattr(cli_mod, "execute_command", lambda *_, **__: (False, {}))
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-admin-cli", "--id", "GW_ADMIN", "symbols"],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 1


def test_main_unknown_gateway_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real executor with an engine answering UNKNOWN_GATEWAY: the
    `orders --gw TYPO` step of a runbook must fail the script."""

    class _UnknownGatewayClient(_FakeClient):
        def orders_reply(self, gw: str) -> dict[str, Any]:
            return {"gateway_id": gw.upper(), "orders": [], "status": "UNKNOWN_GATEWAY"}

    monkeypatch.setattr(
        cli_mod,
        "ExchangeCommandClient",
        lambda gw, push_addr, pub_addr, timeout_ms: _UnknownGatewayClient(
            gw, push_addr, pub_addr, timeout_ms
        ),
    )
    monkeypatch.setattr(
        sys, "argv", ["pm-admin-cli", "--id", "GW_ADMIN", "orders", "--gw", "NOSUCH01"]
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1


@pytest.mark.parametrize("fmt", ["text", "json"])
def test_main_engine_lost_exits_one_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    """The engine went away between connect and command: the send raises
    zmq.Again, and so does the final disconnect."""
    import zmq

    class _GoneClient(_FakeClient):
        def disconnect(self) -> None:
            raise zmq.Again()

    def _lost(*_a: Any, **_k: Any) -> Any:
        raise zmq.Again()

    monkeypatch.setattr(
        cli_mod,
        "ExchangeCommandClient",
        lambda gw, push_addr, pub_addr, timeout_ms: _GoneClient(
            gw, push_addr, pub_addr, timeout_ms
        ),
    )
    monkeypatch.setattr(cli_mod, "execute_command", _lost)
    monkeypatch.setattr(
        sys, "argv", ["pm-admin-cli", "--id", "GW_ADMIN", "--format", fmt, "halt"]
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    out, err = capsys.readouterr()
    if fmt == "json":
        assert json.loads(out) == {"error": "engine_unreachable"}
    else:
        assert "Engine connection lost" in err


def test_build_parser_refuses_a_non_positive_timeout() -> None:
    parser = cli_mod.build_parser()
    for bad in ("0", "-5"):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--id", "GW", "--timeout", bad, "halt"])
        assert exc.value.code == 2


def test_main_text_output_to_a_pipe_has_no_ansi(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """pm-admin-cli is the scripting tool: a redirected stdout gets plain text."""

    class _HaltClient(_FakeClient):
        def halt_all(self) -> dict[str, Any]:
            return {"accepted": True, "halted_symbols": 2, "cancelled_quotes": 0}

    for var in ("FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        cli_mod,
        "ExchangeCommandClient",
        lambda gw, push_addr, pub_addr, timeout_ms: _HaltClient(
            gw, push_addr, pub_addr, timeout_ms
        ),
    )
    monkeypatch.setattr(sys, "argv", ["pm-admin-cli", "--id", "GW_ADMIN", "halt"])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "HALTED  2 symbol(s)" in out
    assert "\x1b[" not in out


def test_main_reopen_nan_price_exits_one_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    class _ReopenClient(_FakeClient):
        def force_uncross(self, *a: Any, **k: Any) -> dict[str, Any]:
            sent.append("force_uncross")
            return {"accepted": True}

    monkeypatch.setattr(
        cli_mod,
        "ExchangeCommandClient",
        lambda gw, push_addr, pub_addr, timeout_ms: _ReopenClient(
            gw, push_addr, pub_addr, timeout_ms
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-admin-cli",
            "--id",
            "GW_ADMIN",
            "reopen",
            "--sym",
            "AAPL",
            "--price",
            "nan",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    assert sent == []
