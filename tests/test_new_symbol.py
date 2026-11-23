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
    # The host's real process table is no business of these tests.
    monkeypatch.setattr(install, "other_processes", lambda: [])
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
    head = original[: original.index("# -- Market-maker seed quotes --")]
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


# -- a source split with include: ----------------------------------------------


@pytest.fixture
def split_source(source: Path, data_dir: Path) -> Path:
    """The same source, with its symbols moved into an included file."""
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    (source.parent / "symbols.yaml").write_text(
        yaml.safe_dump({"symbols": raw.pop("symbols")}, sort_keys=False),
        encoding="utf-8",
    )
    source.write_text(
        yaml.safe_dump({"include": ["symbols.yaml"], **raw}, sort_keys=False),
        encoding="utf-8",
    )
    deploy(source, data_dir / "ref_data" / "engine_config.json")
    return source


def test_symbol_goes_into_the_included_file(split_source: Path, data_dir: Path) -> None:
    included = split_source.parent / "symbols.yaml"
    main_before = split_source.read_bytes()
    before = included.read_text(encoding="utf-8")

    result = add_symbol(_args())

    assert result.edited == included and result.source == split_source
    assert split_source.read_bytes() == main_before
    assert included.read_text(encoding="utf-8").startswith(before.rstrip("\n"))
    assert "IPO1" in yaml.safe_load(included.read_text(encoding="utf-8"))["symbols"]
    assert "IPO1" in _deployed(data_dir).engine.symbols
    assert not [p for p in split_source.parent.iterdir() if p.name.startswith(".new")]


def test_the_last_file_supplying_symbols_is_the_one_edited(
    split_source: Path, data_dir: Path
) -> None:
    first = yaml.safe_load((split_source.parent / "symbols.yaml").read_text("utf-8"))
    name, body = next(iter(first["symbols"].items()))
    extra = split_source.parent / "more.yaml"
    extra.write_text(
        yaml.safe_dump({"symbols": {name + "X": body}}, sort_keys=False),
        encoding="utf-8",
    )
    raw = yaml.safe_load(split_source.read_text(encoding="utf-8"))
    raw["include"].append("more.yaml")
    split_source.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    deploy(split_source, data_dir / "ref_data" / "engine_config.json")

    assert add_symbol(_args()).edited == extra


def test_undeployed_edit_of_an_include_blocks_the_listing(split_source: Path) -> None:
    included = split_source.parent / "symbols.yaml"
    included.write_text(included.read_text("utf-8") + "# pending\n", encoding="utf-8")
    with pytest.raises(ValueError, match="never deployed"):
        add_symbol(_args())


def test_bad_listing_into_an_include_changes_nothing(
    split_source: Path, data_dir: Path
) -> None:
    included = split_source.parent / "symbols.yaml"
    before = (included.read_bytes(), split_source.read_bytes())
    artifact = (data_dir / "ref_data" / "engine_config.json").read_bytes()
    with pytest.raises(ValueError, match="tick grid"):
        add_symbol(_args("--ipo-price", "20.001"))
    assert (included.read_bytes(), split_source.read_bytes()) == before
    assert (data_dir / "ref_data" / "engine_config.json").read_bytes() == artifact
    assert not [p for p in split_source.parent.iterdir() if p.name.startswith(".new")]


# -- WP-NSY01: a name with saved state can be listed again ---------------------


def _saved_state(data_dir: Path) -> dict[str, str]:
    """Saved state for IPO1 and AAPL, written by the engine's own writers:
    book stats for both, a resting IPO1 order, an AAPL order, and a combo
    with one IPO1 leg and one AAPL leg (its legs persist as orders)."""
    from edumatcher.engine.order_book import OrderBook
    from edumatcher.engine.persistence import (
        save_book_stats,
        save_gtc_combos,
        save_gtc_orders,
    )
    from edumatcher.models.combo import ComboLeg, ComboOrder, ComboStatus, ComboType
    from edumatcher.models.order import TIF, Order, OrderType, Side

    def order(symbol: str, **extra: object) -> Order:
        o = Order.create(
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="TRADER01",
            tif=TIF.GTC,
            price_ticks=1000,
        )
        for key, value in extra.items():
            setattr(o, key, value)
        return o

    combo = ComboOrder.create(
        combo_id="CMB1",
        gateway_id="TRADER01",
        combo_type=ComboType.AON,
        tif=TIF.GTC,
        legs=[
            ComboLeg(
                symbol="IPO1", side=Side.BUY, order_type=OrderType.LIMIT,
                quantity=10, tick_decimals=2, price_ticks=1000,
            ),
            ComboLeg(
                symbol="AAPL", side=Side.SELL, order_type=OrderType.LIMIT,
                quantity=10, tick_decimals=2, price_ticks=15000,
            ),
        ],
    )  # fmt: skip
    combo.status = ComboStatus.PENDING
    ipo_leg = order("IPO1", combo_parent_id="CMB1")
    aapl_leg = order("AAPL", combo_parent_id="CMB1")
    combo.child_order_ids = [ipo_leg.id, aapl_leg.id]
    lone_ipo, lone_aapl = order("IPO1"), order("AAPL")
    save_book_stats(
        {"IPO1": OrderBook("IPO1"), "AAPL": OrderBook("AAPL")},
        {},
        data_dir / "book_stats.json",
    )
    save_gtc_orders(
        [lone_ipo, lone_aapl, ipo_leg, aapl_leg], data_dir / "gtc_orders.json"
    )
    save_gtc_combos([combo], data_dir / "gtc_combos.json")
    return {"lone_aapl": lone_aapl.id, "aapl_leg": aapl_leg.id}


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_saved_state_refusal_names_the_option_not_a_bare_clear(
    source: Path, data_dir: Path
) -> None:
    _saved_state(data_dir)
    with pytest.raises(ValueError) as exc:
        add_symbol(_args())
    message = str(exc.value)
    assert "--discard-saved-state" in message
    assert "'pm-opctl-cli clear'" not in message
    assert "clear --state" in message and "clearing.db" in message


def test_discard_saved_state_removes_only_the_symbols_state(
    source: Path, data_dir: Path
) -> None:
    ids = _saved_state(data_dir)
    result = add_symbol(_args("--discard-saved-state"))

    assert result.deployed and "IPO1" in _deployed(data_dir).engine.symbols
    stats = _json(data_dir / "book_stats.json")
    assert isinstance(stats, dict) and set(stats) == {"AAPL"}
    orders = _json(data_dir / "gtc_orders.json")
    assert isinstance(orders, list)
    # The lone AAPL order stays; the combo's AAPL leg goes with its combo.
    assert [o["id"] for o in orders] == [ids["lone_aapl"]]
    assert _json(data_dir / "gtc_combos.json") == []
    assert result.discarded and any("combo" in line for line in result.discarded)


def test_discard_saved_state_removes_nothing_when_the_listing_is_invalid(
    source: Path, data_dir: Path
) -> None:
    _saved_state(data_dir)
    before = {
        name: (data_dir / name).read_bytes()
        for name in ("book_stats.json", "gtc_orders.json", "gtc_combos.json")
    }
    with pytest.raises(CompileError):
        add_symbol(_args("--discard-saved-state", "--field", "level=NO_SUCH_LEVEL"))
    for name, content in before.items():
        assert (data_dir / name).read_bytes() == content


def test_discard_saved_state_is_refused_while_the_engine_runs(
    tmp_path: Path, source: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Also for a file that is only edited: the engine would rewrite the very
    files the option edits at its next checkpoint."""
    _saved_state(data_dir)
    before = (data_dir / "gtc_orders.json").read_bytes()
    other = tmp_path / "draft.yaml"
    other.write_text(source.read_text("utf-8"), encoding="utf-8")
    monkeypatch.setattr(install, "engine_running", lambda: "pm-engine is running")
    with pytest.raises(ValueError, match="pm-engine is running"):
        add_symbol(_args("--discard-saved-state", config=other))
    assert (data_dir / "gtc_orders.json").read_bytes() == before


def test_discard_without_saved_state_changes_nothing_else(
    source: Path, data_dir: Path
) -> None:
    result = add_symbol(_args("--discard-saved-state"))
    assert result.discarded == []
    assert not (data_dir / "gtc_orders.json").exists()


def test_main_reports_what_was_discarded(
    source: Path, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _saved_state(data_dir)
    main(
        [
            "--symbol", "IPO1", "--ipo-price", "20.00",
            "--outstanding-shares", "1000000", "--discard-saved-state",
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert "Removed saved state for IPO1" in out and "gtc_orders.json" in out


# -- WP-NSY02: every price is refused or listed exactly ------------------------


@pytest.mark.parametrize(
    "extra",
    [
        ("--ipo-price", "1e30"),
        ("--ipo-price", "123456789012345678901234567890"),
        ("--ipo-price", "1e20"),
        ("--mm-bid-price", "1e40", "--mm-ask-price", "2e40"),
    ],
)
def test_an_unrepresentable_price_is_refused_without_a_traceback(
    source: Path, data_dir: Path, extra: tuple[str, ...]
) -> None:
    original = source.read_bytes()
    with pytest.raises(ValueError, match="cannot be represented exactly"):
        add_symbol(_args(*extra))
    assert source.read_bytes() == original


def test_main_reports_an_unrepresentable_price_as_a_refusal(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--symbol", "IPO1", "--ipo-price", "1e30", "--outstanding-shares", "10"])
    assert exc.value.code == 1
    assert "cannot be represented exactly" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra",
    [
        ("--ipo-price", "20.00"),
        ("--tick-decimals", "8", "--ipo-price", "0.00000001",
         "--mm-bid-price", "0.00000001", "--mm-ask-price", "0.00000002"),
    ],
)  # fmt: skip
def test_ordinary_prices_are_still_listed(source: Path, extra: tuple[str, ...]) -> None:
    assert add_symbol(_args(*extra)).symbol == "IPO1"


# -- WP-NSY03: other processes still on the old configuration ------------------


def test_a_listing_names_the_processes_still_running_on_the_old_config(
    source: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        install, "other_processes", lambda: ["pm-md-gwy (pid 41)", "pm-stats (pid 42)"]
    )
    main(["--symbol", "IPO1", "--ipo-price", "20.00", "--outstanding-shares", "10"])
    captured = capsys.readouterr()
    assert "pm-md-gwy (pid 41), pm-stats (pid 42)" in captured.err
    assert "restart" in captured.err


def test_a_quiet_exchange_gets_no_warning_and_a_clear_start_line(
    source: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(install, "other_processes", lambda: [])
    main(["--symbol", "IPO1", "--ipo-price", "20.00", "--outstanding-shares", "10"])
    captured = capsys.readouterr()
    assert "[WARN]" not in captured.err
    assert "Start every process of the exchange" in captured.out


def test_other_processes_leave_out_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine is refused outright when deploying; the warning is for the
    rest."""
    from types import SimpleNamespace

    fake = [
        (SimpleNamespace(pid=7), "pm-engine"),
        (SimpleNamespace(pid=8), "pm-md-gwy"),
    ]
    monkeypatch.setattr(guards, "pm_processes", lambda: fake)
    assert guards.other_processes() == ["pm-md-gwy (pid 8)"]


def test_a_failed_deploy_after_a_discard_says_the_state_is_gone(
    source: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Holistic review HR1: the saved state is removed before the file is
    replaced and deployed; an error after that must not hide it."""
    _saved_state(data_dir)

    def fail(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(install, "deploy", fail)
    with pytest.raises(ValueError) as exc:
        add_symbol(_args("--discard-saved-state"))
    message = str(exc.value)
    assert "not deployed" in message
    assert "saved state was already removed" in message
    assert "gtc_orders.json" in message


def _free_tcp_addr() -> str:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{s.getsockname()[1]}"


def test_a_command_that_only_mentions_pm_engine_is_not_an_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Holistic review HR2: the pgrep pattern matched any command line with
    ``…/pm-engine `` in it (a wrapper shell, a tmux or watch command)."""
    import subprocess

    monkeypatch.setattr(guards, "ENGINE_PUB_ADDR", _free_tcp_addr())
    shell = subprocess.Popen(
        ["bash", "-c", "sleep 30; echo /venv/bin/pm-engine --verbose"]
    )
    try:
        assert guards.engine_running() is None
    finally:
        shell.kill()
        shell.wait(5)


def test_a_running_pm_engine_program_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    import sys
    import time

    monkeypatch.setattr(guards, "ENGINE_PUB_ADDR", _free_tcp_addr())
    script = tmp_path / "pm-engine"
    script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    script.chmod(0o755)
    engine = subprocess.Popen([str(script), "--verbose"])
    try:
        deadline = time.monotonic() + 5
        found = guards.engine_running()
        while found is None and time.monotonic() < deadline:
            time.sleep(0.1)  # until the interpreter has exec'd the script
            found = guards.engine_running()
        assert found is not None and str(engine.pid) in found
    finally:
        engine.kill()
        engine.wait(5)
