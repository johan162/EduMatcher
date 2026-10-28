"""system.startup: the first message of every engine start (S21)."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.cli_version import package_version
from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.models.order import Order, OrderType, Side
from tests.engine_harness import SYMBOL, all_msgs, make_engine


def _files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("GTC_ORDERS_FILE", "GTC_COMBOS_FILE", "BOOK_STATS_FILE"):
        monkeypatch.setattr(engine_main, name, tmp_path / f"{name.lower()[:-5]}.json")


def test_it_names_the_engine_the_config_and_the_state_it_starts_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = tmp_path / "deployed" / "engine_config.json"
    compiled = deploy(resolve_example("s1-basic"), artifact)
    text = artifact.read_text(encoding="utf-8")
    _files(monkeypatch, tmp_path)
    (tmp_path / "gtc_orders.json").write_text("[]")
    engine, pub = make_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(
        engine_main, "_deployed_config", lambda: (compiled.engine, text)
    )
    engine = engine_main.Engine(config_path=None)

    engine._announce_startup(7)

    ((topic, p),) = all_msgs(pub)
    assert topic == "system.startup"
    assert p["format_version"] == 1
    assert p["engine_version"] == package_version()
    assert p["git_commit"]
    assert p["python_version"] == platform.python_version()
    assert p["run_seq"] == 7
    assert p["config"] == text
    assert p["config_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert json.loads(p["config"])["meta"]["schema_version"]
    assert p["loaded"] == [
        {"name": "gtc_orders.json", "sha256": hashlib.sha256(b"[]").hexdigest(), "entries": 0},  # fmt: skip
        {"name": "gtc_combos.json", "sha256": None, "entries": 0},
        {"name": "book_stats.json", "sha256": None, "entries": 0},
    ]


def test_it_comes_before_everything_the_restore_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """recovery_item lines precede startup_recovery: only system.startup
    can mark where a run's audit begins."""
    _files(monkeypatch, tmp_path)
    resting = Order.create(
        symbol=SYMBOL, side=Side.BUY, order_type=OrderType.LIMIT,
        quantity=5, gateway_id="GW01", price_ticks=9900,
    )  # fmt: skip
    engine, pub = make_engine(monkeypatch, tmp_path, gtc_orders=[resting])
    engine._announce_startup(1)
    engine._restore_gtc()
    topics = [t for t, _ in all_msgs(pub)]
    assert topics[0] == "system.startup"
    assert topics.index("system.recovery_item") < topics.index(
        "system.startup_recovery"
    )
    assert topics[0] != "system.startup_recovery"
    assert engine._config_text is None  # an engine on a YAML file: config null
    assert all_msgs(pub)[0][1]["config"] is None
