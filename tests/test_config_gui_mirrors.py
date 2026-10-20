"""web-apps/config-gui mirrors the engine_config format in TypeScript.

The browser app builds and imports engine_config.yaml itself, so it carries
copies of what Python owns: the recognised sections and keys, the default
values, and the --comment-default-config-fields text. Nothing but this file
ties the copies to their sources -- before it existed config-gui wrote a
top-level ``country`` no loader reads, imported a missing
``mm_max_spread_ticks`` as 10 after the engine's default became 20, and
printed a defaults header 274 lines out of date. The TypeScript is read as
text, so no Node toolchain is needed.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.config_gen.cli_comments import build_default_engine_field_comment_lines
from edumatcher.config_show.extract import KNOWN_TOP_LEVEL
from edumatcher.cverifier import layer2_schema
from edumatcher.engine import config_loader
from edumatcher.log_srv.config import LogClientConfig
from edumatcher.monitor.config import (
    INVERTED_THRESHOLDS,
    THRESHOLD_RULES,
    MonitorConfig,
)

REPO = Path(__file__).resolve().parents[1]
GUI = REPO / "web-apps" / "config-gui" / "packages"
BUILD = (GUI / "yaml-codec" / "src" / "build.ts").read_text(encoding="utf-8")
PARSE = (GUI / "yaml-codec" / "src" / "parse.ts").read_text(encoding="utf-8")
TYPES = (GUI / "schema" / "src" / "types.ts").read_text(encoding="utf-8")
DEFAULTS = (GUI / "schema" / "src" / "defaults.ts").read_text(encoding="utf-8")
COMMENTS = GUI / "yaml-codec" / "src" / "defaultFieldComments.ts"


def _mentions(source: str, key: str) -> bool:
    return re.search(rf"\b{re.escape(key)}\b", source) is not None


# ---------------------------------------------------------------------------
# sections and keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", sorted(KNOWN_TOP_LEVEL))
def test_every_top_level_section_is_written_and_imported(section: str) -> None:
    assert _mentions(BUILD, section), f"build.ts never writes '{section}'"
    # parse.ts lists what it maps in KNOWN_TOP_LEVEL_KEYS; anything else is
    # kept as uneditable passthrough
    assert f'"{section}"' in PARSE, f"parse.ts does not map '{section}'"


def test_no_section_python_does_not_read_is_written() -> None:
    """The GUI once wrote a top-level ``country``; Python reads ``locale``."""
    written = set(re.findall(r"^\s*cfg\.([a-z_]+) =", BUILD, re.MULTILINE))
    assert written, "the scanner found no cfg.<section> assignments"
    assert written <= KNOWN_TOP_LEVEL, written - KNOWN_TOP_LEVEL


def _key_tables() -> dict[str, frozenset[str]]:
    tables = {
        f"{name}": keys for name, keys in layer2_schema._PROCESS_BLOCK_KEYS.items()
    }
    for name in (
        "_LOG_CLIENT_KEYS",
        "_MONITOR_RETENTION_KEYS",
        "_MONITOR_THRESHOLD_KEYS",
        "_MONITOR_BAND_KEYS",
        "_API_INSTANCE_KEYS",
        "_API_RATE_LIMIT_KEYS",
        "_API_TIMEOUT_KEYS",
        "_API_CREDENTIAL_KEYS",
    ):
        tables[name] = getattr(layer2_schema, name)
    return tables


@pytest.mark.parametrize("table", sorted(_key_tables()))
def test_every_accepted_key_is_written_and_imported(table: str) -> None:
    keys = _key_tables()[table]
    # Threshold rule names live in one TypeScript constant, used by both.
    sources = (BUILD + TYPES, PARSE + TYPES)
    for source, side in zip(sources, ("build.ts", "parse.ts"), strict=True):
        missing = sorted(k for k in keys if not _mentions(source, k))
        assert not missing, f"{side} lacks {table} keys {missing}"


def test_threshold_rules_match() -> None:
    match = re.search(r"MONITOR_THRESHOLD_RULES = \[(.*?)\] as const", TYPES, re.DOTALL)
    assert match is not None
    assert re.findall(r'"([a-z0-9_]+)"', match.group(1)) == list(THRESHOLD_RULES)
    inverted = re.search(
        r"INVERTED_THRESHOLD_RULES[^=]*= new Set\(\[(.*?)\]", TYPES, re.DOTALL
    )
    assert inverted is not None
    assert set(re.findall(r'"([a-z0-9_]+)"', inverted.group(1))) == set(
        INVERTED_THRESHOLDS
    )


# ---------------------------------------------------------------------------
# default values
# ---------------------------------------------------------------------------


def _ts_const(name: str) -> str:
    match = re.search(rf"export const {name}\b[^=]*= (.*?);\n", DEFAULTS, re.DOTALL)
    assert match is not None, f"defaults.ts has no {name}"
    return match.group(1)


def _ts_scalar(name: str) -> str:
    return _ts_const(name).strip().strip('"')


def _ts_field(block: str, field: str) -> str:
    match = re.search(rf"\b{field}: ([^,\n}}]+)", block)
    assert match is not None, field
    return match.group(1).strip().strip('"')


def _num(text: str) -> float:
    return float(text)


def test_engine_loader_defaults() -> None:
    assert _num(_ts_scalar("ENGINE_DEFAULT_MM_MAX_SPREAD_TICKS")) == (
        config_loader._DEFAULT_MM_MAX_SPREAD_TICKS
    )
    assert _num(_ts_scalar("DEFAULT_AUCTION_INDICATIVE_INTERVAL_SEC")) == (
        config_loader._DEFAULT_AUCTION_INDICATIVE_INTERVAL_SEC
    )
    assert (
        _ts_scalar("DEFAULT_SESSION_TIMEZONE") == config_loader.DEFAULT_SESSION_TIMEZONE
    )
    assert _ts_scalar("DEFAULT_COUNTRY") == config_loader.DEFAULT_COUNTRY


def test_monitor_defaults() -> None:
    block = _ts_const("DEFAULT_MONITOR")
    cfg = MonitorConfig()
    assert _ts_field(block, "enabled") == str(cfg.enabled).lower()
    assert _ts_field(block, "bindAddress") == cfg.bind_address
    assert _ts_field(block, "host") == cfg.host
    for ts, value in (
        ("pullPort", cfg.pull_port),
        ("pubPort", cfg.pub_port),
        ("beaconIntervalSec", cfg.beacon_interval_sec),
        ("hungAfterSec", cfg.hung_after_sec),
        ("silentAfterBeacons", cfg.silent_after_beacons),
        ("bookMetricsIntervalSec", cfg.book_metrics_interval_sec),
        ("rawHours", cfg.retention.raw_hours),
        ("minuteDays", cfg.retention.minute_days),
    ):
        assert _num(_ts_field(block, ts)) == value, ts
    bands = _ts_const("DEFAULT_MONITOR_THRESHOLDS").split("> = ", 1)[-1]
    for rule in THRESHOLD_RULES:
        match = re.search(rf"{rule}: \{{ warn: ([\d.]+), crit: ([\d.]+) \}}", bands)
        assert match is not None, rule
        band = getattr(cfg.thresholds, rule)
        assert (_num(match.group(1)), _num(match.group(2))) == (
            band.warn,
            band.crit,
        ), rule


def test_log_client_defaults() -> None:
    block = _ts_const("DEFAULT_LOG_CLIENT")
    cfg = LogClientConfig()
    assert _num(_ts_field(block, "connectTimeoutSec")) == cfg.connect_timeout_sec
    assert _num(_ts_field(block, "failoverTimeoutSec")) == cfg.failover_timeout_sec
    # resolved under the data directory, which the test session relocates
    assert Path(_ts_field(block, "failoverDir")).name == cfg.failover_dir.name


def test_api_bus_defaults() -> None:
    block = _ts_const("DEFAULT_API_BUS")
    cfg = ApiGatewayConfig()
    assert _num(_ts_field(block, "marketDataCacheSec")) == cfg.market_data_cache_sec
    for ts, py in (
        ("enginePullAddr", cfg.engine_pull_addr),
        ("enginePubAddr", cfg.engine_pub_addr),
        ("indexPullAddr", cfg.index_pull_addr),
        ("indexPubAddr", cfg.index_pub_addr),
    ):
        assert _ts_field(block, ts) == py, ts
    assert Path(_ts_field(block, "clearingDb")).name == Path(cfg.clearing_db).name


# ---------------------------------------------------------------------------
# --comment-default-config-fields text
# ---------------------------------------------------------------------------


def test_comment_defaults_text_is_generated_from_python() -> None:
    spec = importlib.util.spec_from_file_location(
        "gen_config_gui_comments", REPO / "tools" / "gen_config_gui_comments.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    assert COMMENTS.read_text(encoding="utf-8") == generator.render(), (
        "defaultFieldComments.ts is out of date: "
        "run `poetry run python tools/gen_config_gui_comments.py`"
    )


def test_comment_defaults_text_has_content() -> None:
    """Guards the guard: an empty Python text would make both sides agree."""
    lines = build_default_engine_field_comment_lines({})
    assert len(lines) > 500
    assert "monitor:" in lines and "locale:" in lines
