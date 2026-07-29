"""LALF-PS configuration coverage across pm-config-gen and pm-cverifier.

The `log_server:` block now carries the twelve LALF-PS fields described in
docs/user-guide/280-log-srv.md. Three tools must agree about them: the
generator that writes them, the verifier that checks them, and the runtime
loader that consumes them. These tests pin all three together — in
particular the round-trip case, since a generator that emits a file its own
runtime loader rejects is the failure mode most likely to go unnoticed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.config_gen.cli import main as config_gen_main
from edumatcher.cverifier import layer2_schema, layer3_semantic
from edumatcher.log_srv.config import load_log_server_config

_PUBSUB_FIELDS = (
    "pubsub_enabled",
    "pub_port",
    "pull_port",
    "lease_sec",
    "max_lease_sec",
    "max_subscribers",
    "notify_interval_ms",
    "backfill_chunk_rows",
    "max_backfill_minutes",
    "max_backfill_rows",
    "max_pending_rows",
    "pub_sndhwm",
)

_GOOD_LOG_SERVER: dict[str, Any] = {
    "port": 5600,
    "pub_port": 5601,
    "pull_port": 5602,
    "pubsub_enabled": True,
    "lease_sec": 30,
    "max_lease_sec": 300,
    "max_subscribers": 32,
    "notify_interval_ms": 250,
    "backfill_chunk_rows": 500,
    "max_backfill_minutes": 1440,
    "max_backfill_rows": 100_000,
    "max_pending_rows": 20_000,
    "pub_sndhwm": 10_000,
}


def _run_gen(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv])
    config_gen_main()


def _base(**sections: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "symbols": {"AAPL": {"tick_decimals": 2}},
        "gateways": {"alf": [{"id": "GW01"}]},
    }
    raw.update(sections)
    return raw


def _log_server_findings(section: Any) -> list[tuple[str, str]]:
    results = layer2_schema.check(_base(log_server=section), Path("engine_config.yaml"))
    return [(r.code, r.path) for r in results if r.path.startswith("log_server")]


def _port_collisions(**sections: Any) -> list[str]:
    results = layer3_semantic.check(_base(**sections), Path("engine_config.yaml"))
    return [r.message for r in results if r.code == "M018"]


# ---------------------------------------------------------------------------
# pm-config-gen — emission
# ---------------------------------------------------------------------------


def test_generated_log_server_carries_every_pubsub_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "engine_config.yaml"
    _run_gen(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "GW01",
            "--log-server",
            "--output",
            str(out),
        ],
    )
    section = yaml.safe_load(out.read_text())["log_server"]
    assert [f for f in _PUBSUB_FIELDS if f not in section] == []
    assert section["pubsub_enabled"] is True
    assert (section["port"], section["pub_port"], section["pull_port"]) == (
        5600,
        5601,
        5602,
    )


def test_generated_config_round_trips_through_the_runtime_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generator must never emit a file pm-log-srv would refuse."""
    out = tmp_path / "engine_config.yaml"
    _run_gen(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "GW01",
            "--log-server-pub-port",
            "7601",
            "--log-server-pull-port",
            "7602",
            "--log-server-lease-sec",
            "10",
            "--log-server-max-lease-sec",
            "60",
            "--log-server-max-subscribers",
            "4",
            "--output",
            str(out),
        ],
    )
    cfg = load_log_server_config(out)
    assert cfg.pub_port == 7601
    assert cfg.pull_port == 7602
    assert cfg.lease_sec == 10
    assert cfg.max_lease_sec == 60
    assert cfg.max_subscribers == 4
    assert cfg.pub_addr == "tcp://0.0.0.0:7601"
    assert cfg.pull_addr == "tcp://0.0.0.0:7602"


def test_any_pubsub_flag_alone_emits_the_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A LALF-PS flag must imply the block, without also passing --log-server."""
    out = tmp_path / "engine_config.yaml"
    _run_gen(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "GW01",
            "--log-server-max-subscribers",
            "8",
            "--output",
            str(out),
        ],
    )
    section = yaml.safe_load(out.read_text())["log_server"]
    assert section["max_subscribers"] == 8


def test_pubsub_disabled_flag_is_emitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "engine_config.yaml"
    _run_gen(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "GW01",
            "--log-server-pubsub-disabled",
            "--output",
            str(out),
        ],
    )
    section = yaml.safe_load(out.read_text())["log_server"]
    assert section["pubsub_enabled"] is False
    assert load_log_server_config(out).pubsub_enabled is False


# ---------------------------------------------------------------------------
# pm-config-gen — rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--log-server-pub-port", "5600"], "must all be different"),
        (["--log-server-pull-port", "5601"], "must all be different"),
        (["--log-server-pub-port", "5602"], "must all be different"),
        (
            ["--log-server-lease-sec", "30", "--log-server-max-lease-sec", "5"],
            "must be >=",
        ),
        (["--log-server-max-subscribers", "0"], "must be > 0"),
        (["--log-server-notify-interval-ms", "0"], "must be > 0"),
        (["--log-server-backfill-chunk-rows", "-1"], "must be > 0"),
        (["--log-server-max-backfill-minutes", "0"], "must be > 0"),
        (["--log-server-max-backfill-rows", "-5"], "must be > 0"),
        (["--log-server-max-pending-rows", "0"], "must be > 0"),
        (["--log-server-pub-sndhwm", "0"], "must be > 0"),
    ],
)
def test_generator_rejects_invalid_pubsub_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected: str,
) -> None:
    out = tmp_path / "engine_config.yaml"
    base = ["--symbols", "AAPL", "--gateways", "GW01", "--output", str(out)]
    with pytest.raises(SystemExit):
        _run_gen(monkeypatch, base + argv)
    assert expected in capsys.readouterr().err
    assert not out.exists()


# ---------------------------------------------------------------------------
# pm-cverifier — layer 2 schema
# ---------------------------------------------------------------------------


def test_valid_pubsub_section_produces_no_findings() -> None:
    assert _log_server_findings(_GOOD_LOG_SERVER) == []


def test_omitting_every_pubsub_field_is_valid() -> None:
    """The whole block is optional; so is every LALF-PS field within it."""
    assert _log_server_findings({"port": 5600}) == []


@pytest.mark.parametrize("field", ["enabled", "pubsub_enabled"])
def test_s096_non_boolean_switch(field: str) -> None:
    findings = _log_server_findings({**_GOOD_LOG_SERVER, field: "yes"})
    assert ("S096", f"log_server.{field}") in findings


@pytest.mark.parametrize("field", ["port", "pub_port", "pull_port"])
def test_s097_out_of_range_port(field: str) -> None:
    findings = _log_server_findings({**_GOOD_LOG_SERVER, field: 99_999})
    assert ("S097", f"log_server.{field}") in findings


@pytest.mark.parametrize(
    "field",
    [
        "lease_sec",
        "max_lease_sec",
        "max_subscribers",
        "notify_interval_ms",
        "backfill_chunk_rows",
        "max_backfill_minutes",
        "max_backfill_rows",
        "max_pending_rows",
        "pub_sndhwm",
    ],
)
def test_s099_non_positive_pubsub_int(field: str) -> None:
    findings = _log_server_findings({**_GOOD_LOG_SERVER, field: 0})
    assert ("S099", f"log_server.{field}") in findings


def test_s099_rejects_booleans_masquerading_as_ints() -> None:
    findings = _log_server_findings({**_GOOD_LOG_SERVER, "max_subscribers": True})
    assert ("S099", "log_server.max_subscribers") in findings


@pytest.mark.parametrize(
    ("overrides", "expected_path"),
    [
        ({"pull_port": 5600}, "log_server.pull_port"),
        ({"pub_port": 5600}, "log_server.pub_port"),
        # Fields are examined in port, pub_port, pull_port order and the
        # finding names the *second* field to claim a number — so setting
        # pub_port onto pull_port's value is reported against pull_port.
        ({"pub_port": 5602}, "log_server.pull_port"),
    ],
)
def test_s102_ports_must_be_distinct(
    overrides: dict[str, Any], expected_path: str
) -> None:
    findings = _log_server_findings({**_GOOD_LOG_SERVER, **overrides})
    assert ("S102", expected_path) in findings


def test_s102_uses_effective_defaults_not_just_explicit_values() -> None:
    """An explicit port colliding with another port's *default* still counts."""
    findings = _log_server_findings({"port": 5601})
    assert ("S102", "log_server.pub_port") in findings


def test_s103_lease_ceiling_below_default_lease() -> None:
    findings = _log_server_findings(
        {**_GOOD_LOG_SERVER, "lease_sec": 60, "max_lease_sec": 30}
    )
    assert ("S103", "log_server.max_lease_sec") in findings


def test_s103_allows_equal_lease_bounds() -> None:
    findings = _log_server_findings(
        {**_GOOD_LOG_SERVER, "lease_sec": 30, "max_lease_sec": 30}
    )
    assert findings == []


def test_s101_does_not_pile_on_top_of_a_specific_finding() -> None:
    """The loader safety net must not restate what S102 already reported."""
    findings = _log_server_findings({**_GOOD_LOG_SERVER, "pull_port": 5600})
    codes = {code for code, _ in findings}
    assert "S102" in codes
    assert "S101" not in codes


# ---------------------------------------------------------------------------
# pm-cverifier — layer 3 cross-section port collisions (M018)
# ---------------------------------------------------------------------------


def test_m018_flags_pub_port_against_another_gateway() -> None:
    messages = _port_collisions(
        log_server={**_GOOD_LOG_SERVER, "pub_port": 5570},
        market_data_gateway={"port": 5570},
    )
    assert any("pub_port" in m and "pm-md-gwy" in m for m in messages)


def test_m018_flags_defaulted_pull_port() -> None:
    """pull_port need not be written down to collide with something else."""
    messages = _port_collisions(
        log_server={"port": 5600},
        dc_gateway={"port": 5602},
    )
    assert any("pull_port" in m for m in messages)


def test_m018_ignores_pubsub_ports_when_the_interface_is_disabled() -> None:
    """A disabled interface binds nothing, so it cannot collide with anything."""
    messages = _port_collisions(
        log_server={**_GOOD_LOG_SERVER, "pub_port": 5570, "pubsub_enabled": False},
        market_data_gateway={"port": 5570},
    )
    assert messages == []


def test_m018_still_reports_plain_gateway_collisions() -> None:
    """Regression guard for the label/field refactor M018 went through."""
    messages = _port_collisions(
        market_data_gateway={"port": 5570},
        dc_gateway={"port": 5570},
    )
    assert len(messages) == 1
    assert "pm-md-gwy" in messages[0] and "pm-dc-gwy" in messages[0]
    assert ".port" in messages[0]


def test_m018_is_silent_on_an_all_defaults_layout() -> None:
    messages = _port_collisions(
        log_server={},
        market_data_gateway={},
        dc_gateway={},
        balf_gateway={},
    )
    assert messages == []


# ---------------------------------------------------------------------------
# End-to-end: generate → verify
# ---------------------------------------------------------------------------


def test_generated_config_passes_the_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "engine_config.yaml"
    _run_gen(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "GW01",
            "--log-server",
            "--output",
            str(out),
        ],
    )
    raw = yaml.safe_load(out.read_text())
    path = Path(out)
    findings = [
        r
        for r in layer2_schema.check(raw, path) + layer3_semantic.check(raw, path)
        if r.severity.name == "ERROR" and "log_server" in (r.path or "")
    ]
    assert findings == []


def test_handwritten_broken_config_is_caught(tmp_path: Path) -> None:
    raw = yaml.safe_load(textwrap.dedent("""
            symbols:
              AAPL:
                tick_decimals: 2
            gateways:
              alf:
                - id: GW01
            log_server:
              port: 5600
              pub_port: 5600
              lease_sec: 60
              max_lease_sec: 30
              max_subscribers: 0
            """))
    codes = {
        r.code
        for r in layer2_schema.check(raw, tmp_path / "engine_config.yaml")
        if r.path.startswith("log_server")
    }
    assert {"S099", "S102", "S103"} <= codes
