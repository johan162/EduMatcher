from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Any

import pytest

from edumatcher.commands import CommandTimeoutError
from edumatcher.commands import cli as cli_mod


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
    parser = cli_mod._build_parser()
    args = parser.parse_args(["--id", "GW_ADMIN", "session-status"])
    assert args.id == "GW_ADMIN"
    assert args.command == "session-status"
    assert args.timeout == 3000


def test_build_parser_enforces_required_fields_and_state_upper() -> None:
    parser = cli_mod._build_parser()

    args = parser.parse_args(["--id", "GW_ADMIN", "kill", "--gw", "TRADER01"])
    assert args.gw == "TRADER01"
    assert args.sym == ""

    args2 = parser.parse_args(["--id", "GW_ADMIN", "session", "--state", "continuous"])
    assert args2.state == "CONTINUOUS"


def test_args_to_fields_maps_only_present_keys() -> None:
    class _Args:
        gw = "TRADER01"
        sym = "AAPL"
        reason = "Compliance"
        state = "CONTINUOUS"

    fields = cli_mod._args_to_fields(_Args)
    assert fields == {
        "GW": "TRADER01",
        "SYM": "AAPL",
        "REASON": "Compliance",
        "STATE": "CONTINUOUS",
    }

    class _Args2:
        gw = None
        sym = ""
        reason = None
        state = None

    assert cli_mod._args_to_fields(_Args2) == {}


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

    def _exec(client: Any, cmd: str, fields: dict[str, str]) -> bool:
        seen["cmd"] = cmd
        seen["fields"] = fields
        return True

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


def test_main_normalizes_hyphen_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def _make_client(
        gw_id: str, push_addr: str, pub_addr: str, timeout_ms: int
    ) -> _FakeClient:
        return _FakeClient(
            gw_id=gw_id, push_addr=push_addr, pub_addr=pub_addr, timeout_ms=timeout_ms
        )

    observed: dict[str, Any] = {}

    def _exec(client: Any, cmd: str, fields: dict[str, str]) -> bool:
        observed["cmd"] = cmd
        return True

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

    def _exec(client: Any, cmd: str, fields: dict[str, str]) -> bool:
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
    monkeypatch.setattr(cli_mod, "execute_command", lambda *_: False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-admin-cli", "--id", "GW_ADMIN", "symbols"],
    )

    with pytest.raises(SystemExit) as exc:
        cli_mod.main()

    assert exc.value.code == 1
