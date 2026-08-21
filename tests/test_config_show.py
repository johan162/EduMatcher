"""Tests for pm-config-show.

Layout code is notoriously untested because "does it look right" is not an
assertion.  These are the four that are:

* nothing ever exceeds the width it was given;
* an API key is never wrapped or truncated;
* the port inventory matches the shared table the collision checker uses;
* density is monotone -- more information, never less.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
import yaml
from rich.console import Console

from edumatcher.config_show.cli import main
from edumatcher.config_show.extract import build_view, resolve_source
from edumatcher.config_show.model import ConfigView, Source
from edumatcher.config_show.panels import mask_key
from edumatcher.config_show.render_term import render
from edumatcher.gateway_ports import (
    DEFAULT_API_GATEWAY_PORT,
    LOG_SERVER_EXTRA_PORTS,
    SINGLETON_GATEWAYS,
    FIXED_LISTENERS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "docs" / "examples" / "ref_data"

WIDTHS = (72, 80, 100, 120, 160, 200, 250)
DENSITIES = (0, 1, 2)


def _config_files() -> list[Path]:
    """Every config in the repo worth rendering.

    The generated examples are the real corpus; a working config at the repo
    root is picked up when present, but is not required to be.
    """
    files = sorted(EXAMPLE_DIR.glob("*/engine_config.yaml"))
    assert files, f"no example configs found under {EXAMPLE_DIR}"
    root_config = REPO_ROOT / "engine_config.yaml"
    if root_config.is_file():
        files.append(root_config)
    return files


CONFIGS = _config_files()


def _view(path: Path) -> ConfigView:
    source = resolve_source(str(path), path)
    with path.open("r", encoding="utf-8") as handle:
        return build_view(yaml.safe_load(handle), source)


def _render(
    view: ConfigView, width: int, density: int, reveal: bool = False, height: int = 400
) -> str:
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=width,
        height=height,
        no_color=True,
        force_terminal=False,
        highlight=False,
        soft_wrap=False,
    )
    render(view, console, density, reveal=reveal)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# the load-bearing invariant
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("density", DENSITIES)
def test_no_line_exceeds_width(path: Path, width: int, density: int) -> None:
    output = _render(_view(path), width, density)
    for number, line in enumerate(output.splitlines(), start=1):
        assert len(line) <= width, (
            f"{path.parent.name} @ w={width} d={density}: line {number} is "
            f"{len(line)} columns:\n{line}"
        )


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
def test_no_line_exceeds_width_when_revealed(path: Path) -> None:
    """--all lengthens nothing: masked and revealed keys are the same width."""
    view = _view(path)
    for width in WIDTHS:
        output = _render(view, width, 2, reveal=True)
        assert all(len(line) <= width for line in output.splitlines())


def test_tiny_mode_below_the_breakpoint() -> None:
    view = _view(CONFIGS[0])
    output = _render(view, 60, 0, height=14)
    assert "PORTS" in output
    assert "╭" not in output and "+-" not in output  # no panel chrome
    assert all(len(line) <= 60 for line in output.splitlines())


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("width", WIDTHS)
def test_keys_are_never_broken(path: Path, width: int) -> None:
    view = _view(path)
    if not view.credentials:
        pytest.skip("config declares no credentials")
    output = _render(view, width, 2, reveal=True)
    for cred in view.credentials:
        assert (
            cred.api_key in output
        ), f"key for {cred.gateway_id} truncated or wrapped at width {width}"


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
def test_keys_masked_by_default(path: Path) -> None:
    view = _view(path)
    if not view.credentials:
        pytest.skip("config declares no credentials")
    output = _render(view, 200, 0)
    for cred in view.credentials:
        assert cred.api_key not in output
        assert mask_key(cred.api_key) in output


def test_masking_preserves_length_and_prefix() -> None:
    key = "key-trader01-phrx67z3zi88g5pld6jx0mlodz8t9ryr"
    masked = mask_key(key)
    assert len(masked) == len(key)  # --all must not move the layout
    assert masked.startswith("key-trader01-")
    assert masked.endswith(key[-4:])
    assert key[13:-4] not in masked  # the secret really is hidden


# ---------------------------------------------------------------------------
# port inventory
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
def test_port_inventory_matches_shared_table(path: Path) -> None:
    """Every listener the shared table implies is present, and no others."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    expected: set[int] = {listener.port for listener in FIXED_LISTENERS}
    for spec in SINGLETON_GATEWAYS:
        section = raw.get(spec.key)
        if not isinstance(section, dict):
            continue
        expected.add(section.get("port", spec.default_port))
        if (
            spec.key == "log_server"
            and section.get("pubsub_enabled", True) is not False
        ):
            for extra in LOG_SERVER_EXTRA_PORTS:
                expected.add(section.get(extra.field, extra.default_port))
    for section in (raw.get("api_gateways") or {}).values():
        if isinstance(section, dict):
            expected.add(section.get("port", DEFAULT_API_GATEWAY_PORT))

    assert {listener.port for listener in _view(path).listeners} == expected


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
def test_fixed_and_env_sockets_are_always_shown(path: Path) -> None:
    """They appear nowhere in the YAML, so only the viewer can surface them."""
    ports = {listener.port for listener in _view(path).listeners}
    assert {5555, 5556, 5557, 5558, 5559} <= ports


def test_collision_is_detected_and_marked(tmp_path: Path) -> None:
    config = tmp_path / "engine_config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "symbols": {"AAPL": {"tick_decimals": 2}},
                "gateways": {"alf": [{"id": "T1", "role": "TRADER"}]},
                # Both land on 5570 -- one explicitly, one via the runtime default.
                "market_data_gateway": {"port": 5570},
                "post_trade_gateway": {"port": 5570},
            }
        ),
        encoding="utf-8",
    )

    view = _view(config)
    assert view.port_collisions == {5570}
    assert "CLASH" in _render(view, 120, 0)


def test_section_without_port_key_still_binds_its_default() -> None:
    source = Source(Path("x.yaml"), True, 0, 0.0, "--file")
    view = build_view({"market_data_gateway": {"enabled": True}}, source)
    listener = next(x for x in view.listeners if x.process == "pm-md-gwy")
    assert listener.port == 5570
    assert listener.origin == "default"


# ---------------------------------------------------------------------------
# density
# ---------------------------------------------------------------------------
#: Panel titles sit inside the top border, and a row may carry several, so
#: they have to be scraped from anywhere in the line -- not just its start.
_TITLE_RE = re.compile(r"╭─\s{2}([A-Z][A-Z &()./a-z_]*?)\s{2}─")


def _panel_titles(output: str) -> set[str]:
    return set(_TITLE_RE.findall(output))


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name)
def test_density_is_monotone(path: Path) -> None:
    """A panel visible at density n is still visible at n+1."""
    view = _view(path)
    titles = [_panel_titles(_render(view, 200, density)) for density in DENSITIES]
    assert titles[0], "no panels found -- the title scraper is broken"
    assert titles[0] <= titles[1], f"density 1 lost {titles[0] - titles[1]}"
    assert titles[1] <= titles[2], f"density 2 lost {titles[1] - titles[2]}"


# ---------------------------------------------------------------------------
# robustness and the read-only contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"symbols": None, "gateways": None},
        {"symbols": "not a mapping", "api_gateways": [1, 2]},
        {"symbols": {"AAPL": None}, "gateways": {"alf": ["nope"]}},
        {"market_data_gateway": {"port": "not-an-int"}},
        {"api_gateways": {"desk": {"credentials": ["nope", {"api_key": None}]}}},
    ],
)
def test_malformed_sections_never_raise(raw: object) -> None:
    """A viewer is most needed when the file is wrong; it must not crash."""
    source = Source(Path("x.yaml"), True, 0, 0.0, "--file")
    view = build_view(raw, source)
    for density in DENSITIES:
        _render(view, 120, density)


def test_bad_yaml_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "engine_config.yaml"
    bad.write_text("symbols: [unclosed\n", encoding="utf-8")
    assert main(["--file", str(bad), "--width", "100"]) == 3
    assert "not valid YAML" in capsys.readouterr().err


def test_missing_file_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--file", str(tmp_path / "nope.yaml")]) == 2
    assert "no such config file" in capsys.readouterr().err


def test_config_file_is_not_modified(tmp_path: Path) -> None:
    config = tmp_path / "engine_config.yaml"
    config.write_text(CONFIGS[0].read_text(encoding="utf-8"), encoding="utf-8")
    before = (config.stat().st_mtime_ns, config.read_bytes())

    assert main(["--file", str(config), "--width", "120", "--all"]) == 0

    assert (config.stat().st_mtime_ns, config.read_bytes()) == before


def test_pdf_is_written_and_multipage(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    target = tmp_path / "out.pdf"
    assert (
        main(["--file", str(CONFIGS[0]), "--format", "pdf", "--output", str(target)])
        == 0
    )
    assert target.is_file()
    assert target.read_bytes().startswith(b"%PDF")
    assert target.read_bytes().count(b"/Type /Page\n") >= 3


# ---------------------------------------------------------------------------
# the shared table vs. the normative specification
# ---------------------------------------------------------------------------
#: Default ports as published in docs/user-guide/990-app-config-spec.md §6.
#: gateway_ports.py claims to mirror the runtime loaders, and the spec claims
#: to describe the same loaders, so the two must agree.  Restating them here
#: turns a silent documentation drift into a failing test.
SPEC_DEFAULT_PORTS = {
    "alf_gateway": 5565,
    "balf_gateway": 5560,
    "market_data_gateway": 5570,
    "post_trade_gateway": 5580,
    "dc_gateway": 5590,
    "log_server": 5600,
}
SPEC_LOG_SERVER_EXTRA_PORTS = {"pub_port": 5601, "pull_port": 5602}
SPEC_API_GATEWAY_PORT = 8080


def test_shared_table_matches_the_specification() -> None:
    assert {
        spec.key: spec.default_port for spec in SINGLETON_GATEWAYS
    } == SPEC_DEFAULT_PORTS
    assert {
        extra.field: extra.default_port for extra in LOG_SERVER_EXTRA_PORTS
    } == SPEC_LOG_SERVER_EXTRA_PORTS
    assert DEFAULT_API_GATEWAY_PORT == SPEC_API_GATEWAY_PORT


def test_every_documented_default_port_is_unique() -> None:
    """Two sections sharing a default would make M018 fire on every config."""
    ports = list(SPEC_DEFAULT_PORTS.values())
    ports += list(SPEC_LOG_SERVER_EXTRA_PORTS.values())
    ports += [SPEC_API_GATEWAY_PORT]
    ports += [listener.port for listener in FIXED_LISTENERS]
    assert len(ports) == len(set(ports))


def test_piped_output_is_plain_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Escape codes in a redirect are corruption, not decoration.

    pytest captures stdout, so ``isatty()`` is False here -- exactly the
    condition a shell redirect or a pipe into grep produces.
    """
    assert main(["--file", str(CONFIGS[0])]) == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    assert max(len(line) for line in out.splitlines()) <= 100
