"""pm-new-symbol lists a symbol correctly or changes nothing at all."""

import json
from pathlib import Path

import pytest
import yaml

from edumatcher.config_artifact import decode
from edumatcher.config_deploy import CompileError, deploy, resolve_example
from edumatcher.new_symbol import config, guards, install
from edumatcher.new_symbol.install import add_symbol
from edumatcher.new_symbol.main import build_parser, main


def _args(*extra: str, config: Path | None = None):
    argv = [
        "--symbol",
        "IPO1",
        "--ipo-price",
        "20.00",
        "--outstanding-shares",
        "1000000",
    ]
    if config is not None:
        argv += ["--config", str(config)]
    return build_parser().parse_args([*argv, *extra])


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    (data / "ref_data").mkdir(parents=True)
    monkeypatch.setattr(
        config, "COMPILED_CONFIG_FILE", data / "ref_data" / "engine_config.json"
    )
    monkeypatch.setattr(guards, "BOOK_STATS_FILE", data / "book_stats.json")
    monkeypatch.setattr(guards, "GTC_ORDERS_FILE", data / "gtc_orders.json")
    monkeypatch.setattr(guards, "GTC_COMBOS_FILE", data / "gtc_combos.json")
    monkeypatch.setattr(install, "engine_running", lambda: None)
    return data


@pytest.fixture
def source(tmp_path: Path, data_dir: Path) -> Path:
    """An authored s3-basic that is the deployed configuration's source."""
    path = tmp_path / "authored" / "engine_config.yaml"
    path.parent.mkdir()
    path.write_text(
        resolve_example("s3-basic").read_text(encoding="utf-8"), encoding="utf-8"
    )
    path.chmod(0o644)
    deploy(path, data_dir / "ref_data" / "engine_config.json")
    return path


def _new(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["symbols"]["IPO1"]


def _deployed(data_dir: Path):
    return decode((data_dir / "ref_data" / "engine_config.json").read_text("utf-8"))


# -- the listing ---------------------------------------------------------------


def test_lists_and_deploys_the_deployed_source(source: Path, data_dir: Path) -> None:
    original = source.read_text(encoding="utf-8")

    result = add_symbol(_args())

    assert result.deployed and result.source == source
    updated = source.read_text(encoding="utf-8")
    # Inserted after the last symbol, before the next section's comment.
    head = original[: original.index("# -- Additional fields --")]
    assert updated.startswith(head.rstrip("\n") + "\n  IPO1:\n")
    assert updated.endswith(original[len(head) :])
    assert oct(source.stat().st_mode & 0o777) == "0o644"

    new = _new(source)
    assert new["last_buy_price"] == new["last_sell_price"] == 20.0
    quote = new["market_maker_quotes"][0]
    # s3-basic: mm_max_spread_ticks 20, so exactly 20 ticks around the price.
    assert (quote["bid_price"], quote["ask_price"]) == (19.9, 20.1)
    assert quote["gateway_id"] == "MM01"

    compiled = _deployed(data_dir)
    assert compiled.meta.source_path == str(source)
    seed = compiled.engine.symbols["IPO1"].market_maker_quotes[0]
    assert (seed.bid_price_ticks, seed.ask_price_ticks) == (1990, 2010)
    assert (data_dir / "ref_data" / "engine_config.yaml").read_text("utf-8") == updated


def test_generated_quote_raises_no_verifier_warning(source: Path) -> None:
    assert add_symbol(_args()).warnings == []


def test_quote_uses_the_gateways_own_spread(source: Path, data_dir: Path) -> None:
    text = source.read_text(encoding="utf-8").replace(
        "  description: Market maker\n",
        "  description: Market maker\n  mm_max_spread_ticks: 7\n",
    )
    source.write_text(text, encoding="utf-8")
    deploy(source, data_dir / "ref_data" / "engine_config.json")

    add_symbol(_args())

    quote = _new(source)["market_maker_quotes"][0]
    assert (quote["bid_price"], quote["ask_price"]) == (19.97, 20.04)


def test_explicit_quote_wider_than_obligation_is_refused(source: Path) -> None:
    original = source.read_bytes()
    with pytest.raises(ValueError, match="exceeds MM01's obligation"):
        add_symbol(_args("--mm-bid-price", "19.50", "--mm-ask-price", "20.50"))
    assert source.read_bytes() == original


def test_explicit_quote_must_straddle_the_ipo_price(source: Path) -> None:
    with pytest.raises(ValueError, match="straddle"):
        add_symbol(_args("--mm-bid-price", "20.05", "--mm-ask-price", "20.10"))


def test_seed_quantity_below_obligation_is_refused(source: Path) -> None:
    with pytest.raises(ValueError, match="obligation of 100"):
        add_symbol(_args("--mm-bid-qty", "50"))


def test_no_seed_quote_when_config_does_not_require_one(
    tmp_path: Path, data_dir: Path
) -> None:
    path = tmp_path / "nomm.yaml"
    path.write_text(
        resolve_example("s3-basic-nomm").read_text(encoding="utf-8"), "utf-8"
    )
    deploy(path, data_dir / "ref_data" / "engine_config.json")

    add_symbol(_args())

    assert "market_maker_quotes" not in _new(path)
    assert "IPO1" in _deployed(data_dir).engine.symbols


def test_field_sets_a_known_section(source: Path) -> None:
    add_symbol(_args("--field", "collar={static_band_pct: 0.15}"))
    assert _new(source)["collar"] == {"static_band_pct": 0.15}


@pytest.mark.parametrize("field", ["colar={static_band_pct: 0.1}", "tick_decimals=3"])
def test_unknown_or_reserved_field_is_refused(source: Path, field: str) -> None:
    with pytest.raises(ValueError, match="--field"):
        add_symbol(_args("--field", field))


# -- refusals that leave everything untouched -----------------------------------


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        (("--symbol", "aapl"), "already listed"),
        (("--symbol", "IPO-1"), "1-8 characters"),
        (("--symbol", "NINECHARS"), "1-8 characters"),
        (("--ipo-price", "20.001"), "tick grid"),
    ],
)
def test_bad_listing_changes_nothing(
    source: Path, data_dir: Path, extra: tuple[str, str], match: str
) -> None:
    original = source.read_bytes()
    artifact = (data_dir / "ref_data" / "engine_config.json").read_bytes()
    with pytest.raises(ValueError, match=match):
        add_symbol(_args(*extra))
    assert source.read_bytes() == original
    assert (data_dir / "ref_data" / "engine_config.json").read_bytes() == artifact


def test_running_engine_blocks_deploy(
    source: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source.read_bytes()
    monkeypatch.setattr(install, "engine_running", lambda: "pm-engine is running")
    with pytest.raises(ValueError, match="stop the exchange"):
        add_symbol(_args())
    assert source.read_bytes() == original


def test_undeployed_edits_block_the_listing(source: Path) -> None:
    source.write_text(source.read_text("utf-8") + "# pending\n", encoding="utf-8")
    with pytest.raises(ValueError, match="never deployed"):
        add_symbol(_args())


def test_deployed_copy_is_not_edited_in_place_of_its_source(
    source: Path, data_dir: Path
) -> None:
    with pytest.raises(ValueError, match="only the deployed copy"):
        add_symbol(_args(config=data_dir / "ref_data" / "engine_config.yaml"))


def test_bundled_example_is_never_edited(data_dir: Path) -> None:
    example = resolve_example("s3-basic")
    original = example.read_bytes()
    deploy(example, data_dir / "ref_data" / "engine_config.json")
    with pytest.raises(ValueError, match="bundled example"):
        add_symbol(_args())
    assert example.read_bytes() == original


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("book_stats.json", {"IPO1": {"last_buy_price": 9.0}}),
        ("gtc_orders.json", [{"symbol": "IPO1"}]),
        ("gtc_combos.json", [{"legs": [{"symbol": "IPO1"}]}]),
    ],
)
def test_saved_state_for_the_symbol_blocks_the_listing(
    source: Path, data_dir: Path, name: str, content: object
) -> None:
    (data_dir / name).write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="saved state for IPO1"):
        add_symbol(_args())


def test_other_file_is_edited_but_not_deployed(
    source: Path, tmp_path: Path, data_dir: Path
) -> None:
    other = tmp_path / "draft.yaml"
    other.write_text(source.read_text("utf-8"), encoding="utf-8")
    artifact = (data_dir / "ref_data" / "engine_config.json").read_bytes()

    result = add_symbol(_args(config=other))

    assert not result.deployed
    assert "IPO1" in yaml.safe_load(other.read_text("utf-8"))["symbols"]
    assert (data_dir / "ref_data" / "engine_config.json").read_bytes() == artifact


def test_invalid_result_reports_findings_and_changes_nothing(
    source: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = source.read_bytes()
    monkeypatch.setattr(
        "sys.argv",
        [
            "pm-new-symbol",
            "--symbol",
            "IPO1",
            "--ipo-price",
            "20",
            "--outstanding-shares",
            "1",
            "--field",
            "collar={static_band_pct: 5}",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "S03" in err and "Nothing was changed" in err
    assert source.read_bytes() == original


def test_malformed_price_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(
            ["--symbol", "X", "--ipo-price", "abc", "--outstanding-shares", "1"]
        )
    assert exit_info.value.code == 2


# -- the text edit ---------------------------------------------------------------

_GATEWAYS = "participants:\n  - id: T1\n    role: TRADER\n"


@pytest.mark.parametrize(
    "symbols",
    [
        "symbols:\n    AAPL:\n        tick_decimals: 2\n",  # four-space indent
        "symbols:\n  AAPL:\n    tick_decimals: 2",  # no trailing newline
        "symbols:\n  AAPL:\n    tick_decimals: 2\n  # BBB:\n  #   tick_decimals: 2\n",
    ],
)
def test_insertion_keeps_the_file_valid(
    tmp_path: Path, data_dir: Path, symbols: str
) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_GATEWAYS + symbols, encoding="utf-8")
    add_symbol(_args(config=path))
    loaded = yaml.safe_load(path.read_text("utf-8"))
    assert list(loaded["symbols"]) == ["AAPL", "IPO1"]


def test_flow_style_symbols_are_refused(tmp_path: Path, data_dir: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_GATEWAYS + "symbols: {AAPL: {tick_decimals: 2}}\n", "utf-8")
    with pytest.raises(ValueError, match="block style"):
        add_symbol(_args(config=path))


def test_compile_error_is_a_compile_error(tmp_path: Path, data_dir: Path) -> None:
    # A level the file does not define fails validation, not the edit.
    path = tmp_path / "c.yaml"
    path.write_text(_GATEWAYS + "symbols:\n  AAPL:\n    tick_decimals: 2\n", "utf-8")
    with pytest.raises(CompileError):
        add_symbol(_args("--field", "level=NOPE", config=path))
