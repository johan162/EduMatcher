from __future__ import annotations

from pathlib import Path
import sys

import pytest

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv import main as log_srv_main


class _DummyServer:
    def __init__(self, config: LogServerConfig, called: dict[str, object]) -> None:
        called["config"] = config
        self._called = called

    def run(self) -> None:
        self._called["run"] = True

    def close(self) -> None:
        self._called["close"] = True


class _ExplodingServer(_DummyServer):
    def run(self) -> None:
        self._called["run"] = True
        raise RuntimeError("boom")


def test_main_runs_server_with_resolved_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, object] = {"run": False, "close": False}

    monkeypatch.setattr(
        log_srv_main,
        "load_default_log_server_config",
        lambda: LogServerConfig(db_path=tmp_path / "log.db", pubsub_enabled=False),
    )
    monkeypatch.setattr(
        log_srv_main,
        "LogServer",
        lambda config: _DummyServer(config, called),
    )
    monkeypatch.setattr(
        "edumatcher.config_artifact.report_deployment", lambda _log: None
    )
    monkeypatch.setattr(sys, "argv", ["pm-log-srv", "--host", "127.0.0.1"])

    log_srv_main.main()

    assert called["run"] is True
    assert called["close"] is True
    cfg = called["config"]
    assert isinstance(cfg, LogServerConfig)
    assert cfg.bind_address == "127.0.0.1"


def test_main_exits_cleanly_when_log_server_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed = {"called": False}

    monkeypatch.setattr(
        log_srv_main,
        "load_default_log_server_config",
        lambda: LogServerConfig(
            enabled=False,
            db_path=tmp_path / "log.db",
            pubsub_enabled=False,
        ),
    )

    def _unexpected_server(_config: LogServerConfig) -> _DummyServer:
        constructed["called"] = True
        return _DummyServer(_config, {})

    monkeypatch.setattr(log_srv_main, "LogServer", _unexpected_server)
    monkeypatch.setattr(
        "edumatcher.config_artifact.report_deployment", lambda _log: None
    )
    monkeypatch.setattr(sys, "argv", ["pm-log-srv"])

    log_srv_main.main()
    assert constructed["called"] is False


def test_main_validates_port_collisions_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        log_srv_main,
        "load_default_log_server_config",
        lambda: LogServerConfig(
            db_path=tmp_path / "log.db",
            port=5601,
            pubsub_enabled=True,
            pub_port=5602,
            pull_port=5603,
        ),
    )
    monkeypatch.setattr(
        "edumatcher.config_artifact.report_deployment", lambda _log: None
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-log-srv", "--port", "7777", "--pub-port", "7777"],
    )

    with pytest.raises(SystemExit) as excinfo:
        log_srv_main.main()
    assert excinfo.value.code == 2


def test_main_closes_server_even_on_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, object] = {"run": False, "close": False}

    monkeypatch.setattr(
        log_srv_main,
        "load_default_log_server_config",
        lambda: LogServerConfig(db_path=tmp_path / "log.db", pubsub_enabled=False),
    )
    monkeypatch.setattr(
        log_srv_main,
        "LogServer",
        lambda config: _ExplodingServer(config, called),
    )
    monkeypatch.setattr(
        "edumatcher.config_artifact.report_deployment", lambda _log: None
    )
    monkeypatch.setattr(sys, "argv", ["pm-log-srv"])

    with pytest.raises(RuntimeError, match="boom"):
        log_srv_main.main()

    assert called["run"] is True
    assert called["close"] is True
