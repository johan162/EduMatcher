"""Per-symbol configuration for pm-mm-bot — CLI scopes, YAML v1, precedence.

These tests treat the feature as a black box with a contract:

* a command line and a config file are two spellings of the same
  configuration, and must resolve identically;
* a parameter set for one symbol never leaks into another;
* the five-rank precedence ladder promotes exactly one source at a time;
* an impossible configuration is refused at startup, naming the symbol.

They deliberately assert on observable outcomes — the resolved parameter
table, the ``quote.new`` payloads actually put on the wire, the process exit
code — rather than on the shape of the code that produces them.

See docs-design/EduMatcher-mm-bot-multi.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from edumatcher.mm_bot.bot import BotState, MMBot
from edumatcher.mm_bot.cli_scope import ScopeError, split_argv_scopes
from edumatcher.mm_bot.config import (
    EMPTY_FILE_CONFIG,
    FileConfig,
    load_bot_config,
)
from edumatcher.mm_bot.params import TIER2_DEFAULTS, TIER2_KEYS
from edumatcher.mm_bot.resolve import NoSymbolsError, resolve_symbol_params
from edumatcher.models.message import decode as msg_decode, encode

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "mm-bot"


# ========================================================================
# Helpers
# ========================================================================


def write(tmp_path: Path, text: str, name: str = "mm.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def resolve_cli(
    argv: list[str], file_config: FileConfig | None = None
) -> dict[str, dict[str, Any]]:
    """Resolve a command line the way ``main.py`` does, minus the bot.

    Returns SYMBOL -> resolved Tier-2 parameters.
    """
    from edumatcher.mm_bot import main as mm_main

    parser = mm_main.build_parser()
    scopes = split_argv_scopes(argv)
    args = parser.parse_args(scopes.global_argv)
    symbol_cli, _hoisted = mm_main._parse_symbol_scopes(parser, scopes.symbol_argv)
    extra = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else []
    )
    resolved = resolve_symbol_params(
        file_config or EMPTY_FILE_CONFIG,
        mm_main._given(args, TIER2_KEYS),
        symbol_cli,
        extra,
    )
    return resolved.params


class FakeBot:
    """Stand-in for MMBot that records the kwargs main.py built for it."""

    instances: list["FakeBot"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        FakeBot.instances.append(self)

    def run(self) -> int:
        return 0

    def shutdown(self) -> None:  # pragma: no cover - never reached in tests
        pass


@pytest.fixture
def fake_bot(monkeypatch: pytest.MonkeyPatch) -> type[FakeBot]:
    FakeBot.instances = []
    monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", FakeBot)
    return FakeBot


def run_main(argv: list[str]) -> int:
    """Run ``main(argv)`` and return the exit code it raised."""
    from edumatcher.mm_bot import main as mm_main

    with pytest.raises(SystemExit) as exc:
        mm_main.main(argv)
    return int(exc.value.code or 0)


# ========================================================================
# 1. Splitting a command line into per-symbol scopes
# ========================================================================


class TestArgvScopeSplitting:
    """``--symbol`` is the only token that changes scope; nothing else moves."""

    def test_no_symbol_flag_leaves_everything_global(self) -> None:
        argv = ["--symbols", "AAPL,MSFT", "--gap", "0.1"]
        scopes = split_argv_scopes(argv)
        assert scopes.global_argv == argv
        assert scopes.symbol_argv == []

    def test_splitting_is_a_pure_regrouping(self) -> None:
        """Rejoining the pieces reproduces the original command line."""
        argv = [
            "--qty",
            "500",
            "--symbol",
            "AAPL",
            "--gap",
            "0.1",
            "--symbol",
            "MSFT",
            "--gap",
            "0.2",
            "--qty",
            "200",
        ]
        scopes = split_argv_scopes(argv)
        rejoined = list(scopes.global_argv)
        for symbol, scope_argv in scopes.symbol_argv:
            rejoined += ["--symbol", symbol, *scope_argv]
        assert rejoined == argv

    def test_input_is_never_mutated(self) -> None:
        argv = ["--symbol", "AAPL", "--gap", "0.1"]
        snapshot = list(argv)
        split_argv_scopes(argv)
        assert argv == snapshot

    def test_equals_form_opens_the_same_scope(self) -> None:
        spaced = split_argv_scopes(["--symbol", "AAPL", "--gap", "0.1"])
        equals = split_argv_scopes(["--symbol=AAPL", "--gap", "0.1"])
        assert spaced == equals

    def test_symbol_names_are_normalised(self) -> None:
        scopes = split_argv_scopes(["--symbol", " aapl "])
        assert scopes.symbols == ["AAPL"]

    def test_symbols_plural_flag_is_not_a_scope_boundary(self) -> None:
        """--symbols shares a prefix with --symbol but must not open a scope."""
        for form in (["--symbols", "AAPL,MSFT"], ["--symbols=AAPL,MSFT"]):
            scopes = split_argv_scopes(form)
            assert scopes.symbol_argv == []
            assert scopes.global_argv == form

    def test_double_dash_stops_scope_detection(self) -> None:
        scopes = split_argv_scopes(["--symbol", "AAPL", "--", "--symbol", "MSFT"])
        assert scopes.symbols == ["AAPL"]
        assert scopes.symbol_argv[0][1] == ["--", "--symbol", "MSFT"]

    def test_double_dash_before_any_symbol_stays_global(self) -> None:
        argv = ["--", "--symbol", "AAPL"]
        assert split_argv_scopes(argv).global_argv == argv

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["--gap", "0.1", "--symbol"], id="trailing"),
            pytest.param(["--symbol", "--gap"], id="followed-by-a-flag"),
            pytest.param(["--symbol="], id="empty-equals-form"),
        ],
    )
    def test_symbol_without_a_name_is_refused(self, argv: list[str]) -> None:
        with pytest.raises(ScopeError, match="requires a symbol name"):
            split_argv_scopes(argv)

    def test_the_same_symbol_twice_is_refused(self) -> None:
        """Two scopes for one symbol would silently merge; say so instead."""
        with pytest.raises(ScopeError, match="AAPL given more than once"):
            split_argv_scopes(["--symbol", "AAPL", "--symbol", "aapl"])


# ========================================================================
# 2. Flag position never changes the meaning of a one-symbol command line
# ========================================================================


class TestSingleSymbolCommandLinesAreUnchanged:
    """The scoping grammar is additive: old invocations mean what they did."""

    @pytest.mark.parametrize(
        "before, after",
        [
            (
                ["--gap", "0.2", "--qty", "200", "--symbol", "AAPL"],
                ["--symbol", "AAPL", "--gap", "0.2", "--qty", "200"],
            ),
            (
                ["--tif", "GTC", "--symbol", "MSFT", "--drift-ticks", "7"],
                ["--symbol", "MSFT", "--tif", "GTC", "--drift-ticks", "7"],
            ),
        ],
    )
    def test_flag_position_is_irrelevant_with_one_symbol(
        self, before: list[str], after: list[str]
    ) -> None:
        assert resolve_cli(before) == resolve_cli(after)

    def test_gateway_flag_after_symbol_still_applies(
        self, fake_bot: type[FakeBot]
    ) -> None:
        """A gateway-wide flag typed after --symbol is hoisted, not lost."""
        assert run_main(["--symbol", "MSFT", "--id-suffix", "03"]) == 0
        assert fake_bot.instances[0].kwargs["gateway_id"] == "MM_MSFT_03"


# ========================================================================
# 3. Per-symbol isolation of every Tier-2 parameter
# ========================================================================


class TestPerSymbolIsolation:
    """Setting a parameter on one symbol must not touch any other symbol."""

    OVERRIDES: dict[str, tuple[str, Any]] = {
        "gap": ("--gap", 0.75),
        "qty": ("--qty", 42),
        "drift_ticks": ("--drift-ticks", 9),
        "tif": ("--tif", "GTC"),
        "reissue_delay_ms": ("--reissue-delay-ms", 1234),
        "heartbeat_interval_sec": ("--heartbeat-interval-sec", 11.0),
        "bootstrap_timeout_sec": ("--bootstrap-timeout-sec", 2.5),
        "cancel_timeout_sec": ("--cancel-timeout-sec", 3.5),
        "qlegs_reconcile_interval_sec": ("--qlegs-reconcile-interval-sec", 99.0),
    }

    @pytest.mark.parametrize("key", sorted(OVERRIDES))
    def test_scoped_flag_touches_only_its_own_symbol(self, key: str) -> None:
        flag, value = self.OVERRIDES[key]
        params = resolve_cli(["--symbol", "AAPL", flag, str(value), "--symbol", "MSFT"])
        assert params["AAPL"][key] == value
        assert params["MSFT"][key] == TIER2_DEFAULTS[key]

    def test_every_tier2_key_is_reachable_from_a_symbol_scope(self) -> None:
        """No Tier-2 key may be silently unsettable per symbol."""
        covered = set(self.OVERRIDES) | {
            "strategy",
            "max_position",
            "initial_min",
            "initial_max",
        }
        assert covered == set(TIER2_KEYS)

    def test_strategy_and_max_position_are_per_symbol(self) -> None:
        params = resolve_cli(
            [
                "--symbol",
                "AAPL",
                "--symbol",
                "TSLA",
                "--strategy",
                "inventory_skew",
                "--max-position",
                "5000",
            ]
        )
        assert params["AAPL"]["strategy"] == "symmetric"
        assert params["AAPL"]["max_position"] is None
        assert params["TSLA"]["strategy"] == "inventory_skew"
        assert params["TSLA"]["max_position"] == 5000

    def test_bootstrap_range_is_per_symbol(self) -> None:
        params = resolve_cli(
            [
                "--symbol",
                "AAPL",
                "--symbol",
                "TSLA",
                "--initial_min",
                "180",
                "--initial_max",
                "220",
            ]
        )
        assert (params["AAPL"]["initial_min"], params["AAPL"]["initial_max"]) == (
            None,
            None,
        )
        assert (params["TSLA"]["initial_min"], params["TSLA"]["initial_max"]) == (
            180.0,
            220.0,
        )

    def test_global_flags_reach_every_symbol(self) -> None:
        params = resolve_cli(["--qty", "250", "--symbol", "AAPL", "--symbol", "MSFT"])
        assert [params[s]["qty"] for s in ("AAPL", "MSFT")] == [250, 250]


# ========================================================================
# 4. The precedence ladder
# ========================================================================


class TestPrecedenceLadder:
    """Removing the winning source promotes exactly the next one down."""

    SYMBOL_CLI = 0.11
    SYMBOL_FILE = 0.22
    GLOBAL_CLI = 0.33
    FILE_DEFAULTS = 0.44

    def _file(self, *, symbol_block: bool, defaults: bool) -> FileConfig:
        return FileConfig(
            defaults={"gap": self.FILE_DEFAULTS} if defaults else {},
            symbols={"AAPL": {"gap": self.SYMBOL_FILE} if symbol_block else {}},
        )

    def _argv(self, *, symbol_cli: bool, global_cli: bool) -> list[str]:
        argv: list[str] = []
        if global_cli:
            argv += ["--gap", str(self.GLOBAL_CLI)]
        argv += ["--symbol", "AAPL"]
        if symbol_cli:
            argv += ["--gap", str(self.SYMBOL_CLI)]
        return argv

    @pytest.mark.parametrize(
        "symbol_cli, symbol_file, global_cli, file_defaults, expected",
        [
            (True, True, True, True, SYMBOL_CLI),
            (False, True, True, True, SYMBOL_FILE),
            (False, False, True, True, GLOBAL_CLI),
            (False, False, False, True, FILE_DEFAULTS),
            (False, False, False, False, TIER2_DEFAULTS["gap"]),
        ],
        ids=["rank1", "rank2", "rank3", "rank4", "rank5-builtin"],
    )
    def test_each_rank_wins_when_the_ranks_above_it_are_absent(
        self,
        symbol_cli: bool,
        symbol_file: bool,
        global_cli: bool,
        file_defaults: bool,
        expected: float,
    ) -> None:
        params = resolve_cli(
            self._argv(symbol_cli=symbol_cli, global_cli=global_cli),
            self._file(symbol_block=symbol_file, defaults=file_defaults),
        )
        assert params["AAPL"]["gap"] == expected

    def test_a_per_symbol_file_value_beats_a_gateway_wide_flag(self) -> None:
        """Assumption A2: specificity beats source.

        A value written into a reviewed config file for one symbol is not
        un-tuned by a throwaway global flag. This is intentional — do not
        "fix" it. Overriding one symbol from the CLI is still possible, by
        naming it (see the next test).
        """
        params = resolve_cli(
            ["--gap", "0.33", "--symbol", "AAPL", "--symbol", "TSLA"],
            FileConfig(symbols={"TSLA": {"gap": 0.50}}),
        )
        assert params["AAPL"]["gap"] == 0.33
        assert params["TSLA"]["gap"] == 0.50

    def test_naming_the_symbol_on_the_cli_does_override_its_file_block(self) -> None:
        params = resolve_cli(
            ["--symbol", "TSLA", "--gap", "0.05"],
            FileConfig(symbols={"TSLA": {"gap": 0.50}}),
        )
        assert params["TSLA"]["gap"] == 0.05


# ========================================================================
# 5. The symbol universe
# ========================================================================


class TestSymbolUniverse:
    def test_file_symbols_come_first_then_cli_only_ones(self) -> None:
        params = resolve_cli(
            ["--symbol", "NVDA", "--symbol", "AAPL"],
            FileConfig(symbols={"AAPL": {}, "MSFT": {}}),
        )
        assert list(params) == ["AAPL", "MSFT", "NVDA"]

    def test_a_cli_symbol_already_in_the_file_opens_an_override_not_a_duplicate(
        self,
    ) -> None:
        params = resolve_cli(
            ["--symbol", "AAPL", "--qty", "111"],
            FileConfig(symbols={"AAPL": {"qty": 999}}),
        )
        assert list(params) == ["AAPL"]
        assert params["AAPL"]["qty"] == 111

    def test_symbols_plural_flag_adds_symbols_with_shared_settings(self) -> None:
        params = resolve_cli(["--symbols", "aapl, msft ", "--gap", "0.3"])
        assert list(params) == ["AAPL", "MSFT"]
        assert all(p["gap"] == 0.3 for p in params.values())

    def test_no_symbol_anywhere_is_refused(self) -> None:
        with pytest.raises(NoSymbolsError, match="no symbols configured"):
            resolve_symbol_params(EMPTY_FILE_CONFIG, {})


# ========================================================================
# 6. gap_was_explicit — the MM-obligation escape hatch
# ========================================================================


class TestGapExplicitness:
    """bot.py derives a symbol's gap from its MM obligation only when the
    operator never chose one. That distinction must survive every source."""

    def test_untouched_gap_is_not_explicit(self) -> None:
        params = resolve_cli(["--symbol", "AAPL"])
        assert params["AAPL"]["gap"] == TIER2_DEFAULTS["gap"]
        assert params["AAPL"]["gap_was_explicit"] is False

    @pytest.mark.parametrize(
        "argv, file_config",
        [
            pytest.param(["--symbol", "AAPL", "--gap", "0.1"], None, id="symbol-cli"),
            pytest.param(["--gap", "0.1", "--symbol", "AAPL"], None, id="global-cli"),
            pytest.param(
                ["--symbol", "AAPL"],
                FileConfig(symbols={"AAPL": {"gap": 0.1}}),
                id="symbol-block",
            ),
            pytest.param(
                ["--symbol", "AAPL"],
                FileConfig(defaults={"gap": 0.1}),
                id="file-defaults",
            ),
        ],
    )
    def test_a_gap_chosen_anywhere_counts_as_explicit(
        self, argv: list[str], file_config: FileConfig | None
    ) -> None:
        params = resolve_cli(argv, file_config)
        assert params["AAPL"]["gap_was_explicit"] is True

    def test_explicitness_is_tracked_per_symbol(self) -> None:
        params = resolve_cli(["--symbol", "AAPL", "--gap", "0.1", "--symbol", "MSFT"])
        assert params["AAPL"]["gap_was_explicit"] is True
        assert params["MSFT"]["gap_was_explicit"] is False

    def test_a_gap_equal_to_the_builtin_default_still_counts_as_chosen(self) -> None:
        params = resolve_cli(["--symbol", "AAPL", "--gap", "0.10"])
        assert params["AAPL"]["gap"] == TIER2_DEFAULTS["gap"]
        assert params["AAPL"]["gap_was_explicit"] is True


# ========================================================================
# 7. A config file and a command line are two spellings of one configuration
# ========================================================================


class TestConfigFileAndCommandLineAgree:
    def test_the_worked_example_resolves_the_same_either_way(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            """
version: 1
defaults:
  qty: 500
  tif: DAY
  drift_ticks: 3
symbols:
  AAPL:
    gap: 0.10
  MSFT:
    gap: 0.20
    qty: 200
  TSLA:
    gap: 0.50
    qty: 100
    strategy: inventory_skew
    max_position: 5000
    initial_min: 180
    initial_max: 220
""",
        )
        from_file = resolve_cli([], load_bot_config(path))
        from_cli = resolve_cli(
            [
                "--qty",
                "500",
                "--tif",
                "DAY",
                "--drift-ticks",
                "3",
                "--symbol",
                "AAPL",
                "--gap",
                "0.10",
                "--symbol",
                "MSFT",
                "--gap",
                "0.20",
                "--qty",
                "200",
                "--symbol",
                "TSLA",
                "--gap",
                "0.50",
                "--qty",
                "100",
                "--strategy",
                "inventory_skew",
                "--max-position",
                "5000",
                "--initial_min",
                "180",
                "--initial_max",
                "220",
            ]
        )
        assert from_file == from_cli

    def test_list_shorthand_equals_empty_blocks(self, tmp_path: Path) -> None:
        listed = load_bot_config(
            write(tmp_path, "version: 1\nsymbols: [AAPL, MSFT]\n", "a.yaml")
        )
        mapped = load_bot_config(
            write(tmp_path, "version: 1\nsymbols:\n  AAPL: {}\n  MSFT:\n", "b.yaml")
        )
        assert listed == mapped

    def test_legacy_flat_file_still_means_what_it_did(self, tmp_path: Path) -> None:
        legacy = load_bot_config(
            write(tmp_path, "symbol: AAPL\ngap: 0.08\nqty: 300\ntif: GTC\n", "l.yaml")
        )
        modern = load_bot_config(
            write(
                tmp_path,
                "version: 1\ndefaults:\n  gap: 0.08\n  qty: 300\n  tif: GTC\n"
                "symbols:\n  AAPL: {}\n",
                "m.yaml",
            )
        )
        assert resolve_cli([], legacy) == resolve_cli([], modern)

    def test_legacy_flat_multi_symbol_file_shares_its_settings(
        self, tmp_path: Path
    ) -> None:
        loaded = load_bot_config(
            write(tmp_path, "symbols: AAPL,MSFT\ngap: 0.3\n", "flat.yaml")
        )
        params = resolve_cli([], loaded)
        assert list(params) == ["AAPL", "MSFT"]
        assert all(p["gap"] == 0.3 for p in params.values())


# ========================================================================
# 8. Config-file schema rules
# ========================================================================


class TestConfigFileSchema:
    def test_gateway_and_logging_blocks_are_carried_through(
        self, tmp_path: Path
    ) -> None:
        loaded = load_bot_config(
            write(
                tmp_path,
                """
version: 1
gateway:
  label: TECH
  id_suffix: "07"
  engine_pull: tcp://10.0.0.1:5555
logging:
  level: DEBUG
  target: stdout
symbols: [AAPL]
""",
            )
        )
        assert loaded.gateway["label"] == "TECH"
        assert loaded.gateway["id_suffix"] == "07"
        assert loaded.logging == {"level": "DEBUG", "target": "stdout"}

    def test_symbol_names_are_upper_cased(self, tmp_path: Path) -> None:
        loaded = load_bot_config(
            write(tmp_path, "version: 1\nsymbols:\n  aapl:\n    gap: 0.2\n")
        )
        assert loaded.symbols == {"AAPL": {"gap": 0.2}}

    def test_a_symbols_mapping_selects_the_v1_schema_without_a_version_key(
        self, tmp_path: Path
    ) -> None:
        """The shape is enough to tell the two formats apart."""
        loaded = load_bot_config(write(tmp_path, "symbols:\n  AAPL:\n    gap: 0.2\n"))
        assert loaded.symbols == {"AAPL": {"gap": 0.2}}

    def test_a_legacy_file_naming_no_symbol_contributes_only_defaults(
        self, tmp_path: Path
    ) -> None:
        loaded = load_bot_config(write(tmp_path, "gap: 0.3\nqty: 20\n"))
        assert loaded.symbols == {}
        assert loaded.defaults == {"gap": 0.3, "qty": 20}

    def test_an_empty_file_configures_nothing(self, tmp_path: Path) -> None:
        assert load_bot_config(write(tmp_path, "")) == EMPTY_FILE_CONFIG

    @pytest.mark.parametrize(
        "text, message",
        [
            pytest.param(
                "version: 2\nsymbols: [AAPL]\n",
                "unsupported version",
                id="future-version",
            ),
            pytest.param(
                "version: 1\n", "'symbols:' block is required", id="no-symbols"
            ),
            pytest.param(
                "version: 1\nsymbols: {}\n",
                "at least one symbol",
                id="empty-symbols",
            ),
            pytest.param(
                "version: 1\nsymbols: 7\n",
                "must be a mapping of symbol blocks",
                id="symbols-wrong-type",
            ),
            pytest.param(
                "version: 1\nsymbols:\n  - 7\n",
                "list entries must be non-empty strings",
                id="symbols-list-non-string",
            ),
            pytest.param(
                "version: 1\nsymbols:\n  7: {}\n",
                "symbol names must be non-empty strings",
                id="symbol-key-non-string",
            ),
            pytest.param(
                "version: 1\nsymbols:\n  AAPL: 7\n",
                "'symbols.AAPL' must be a mapping",
                id="symbol-block-not-a-mapping",
            ),
            pytest.param(
                "version: 1\ngateway:\n  id_suffix: 01\nsymbols: [AAPL]\n",
                "id_suffix must be a string",
                id="unquoted-id-suffix",
            ),
            pytest.param(
                "version: 1\nbogus: 1\nsymbols: [AAPL]\n",
                "unknown key 'bogus'",
                id="unknown-top-level",
            ),
            pytest.param(
                "version: 1\ndefaults:\n  gapp: 0.1\nsymbols: [AAPL]\n",
                "did you mean 'gap'",
                id="typo-gets-a-suggestion",
            ),
            pytest.param(
                "version: 1\nsymbols:\n  AAPL:\n    engine_pull: tcp://x\n",
                "gateway-wide setting; move it under 'gateway:'",
                id="gateway-key-in-symbol-block",
            ),
            pytest.param(
                "version: 1\ndefaults:\n  log_level: INFO\nsymbols: [AAPL]\n",
                "logging setting; move it under 'logging:'",
                id="logging-key-in-defaults",
            ),
            pytest.param(
                "version: 1\ngateway:\n  gap: 0.1\nsymbols: [AAPL]\n",
                "per-symbol setting; move it under 'defaults:'",
                id="tier2-key-in-gateway",
            ),
            pytest.param(
                "version: 1\ngateway:\n  bogus: 1\nsymbols: [AAPL]\n",
                "unknown key 'bogus' under gateway",
                id="unknown-gateway-key",
            ),
            pytest.param(
                "version: 1\ngateway: 7\nsymbols: [AAPL]\n",
                "'gateway' must be a mapping",
                id="gateway-not-a-mapping",
            ),
        ],
    )
    def test_a_malformed_file_is_refused_with_a_useful_message(
        self, tmp_path: Path, text: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            load_bot_config(write(tmp_path, text))

    @pytest.mark.parametrize(
        "text, message",
        [
            ("- AAPL\n", "must contain a YAML mapping"),
            ("symbol: [unclosed\n", "not valid YAML"),
        ],
    )
    def test_an_unreadable_file_is_refused(
        self, tmp_path: Path, text: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            load_bot_config(write(tmp_path, text))

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cannot read config file"):
            load_bot_config(tmp_path / "nope.yaml")


# ========================================================================
# 9. Validation — impossible configurations are refused, naming the symbol
# ========================================================================


class TestValidation:
    @pytest.mark.parametrize(
        "block, message",
        [
            pytest.param({"gap": 0}, "gap must be positive", id="gap-zero"),
            pytest.param({"gap": -1.0}, "gap must be positive", id="gap-negative"),
            pytest.param(
                {"gap": "wide"}, "gap must be a number", id="gap-not-a-number"
            ),
            pytest.param({"qty": 0}, "qty must be positive", id="qty-zero"),
            pytest.param({"qty": 1.5}, "qty must be an integer", id="qty-fractional"),
            pytest.param({"qty": True}, "qty must be an integer", id="qty-boolean"),
            pytest.param(
                {"drift_ticks": 0}, "drift_ticks must be positive", id="drift-zero"
            ),
            pytest.param({"tif": "FOK"}, "tif must be one of", id="tif-unknown"),
            pytest.param({"tif": 7}, "tif must be a non-empty string", id="tif-int"),
            pytest.param(
                {"reissue_delay_ms": -1},
                "reissue_delay_ms must be non-negative",
                id="reissue-negative",
            ),
            pytest.param(
                {"heartbeat_interval_sec": 0},
                "heartbeat_interval_sec must be positive",
                id="heartbeat-zero",
            ),
            pytest.param(
                {"bootstrap_timeout_sec": -1},
                "bootstrap_timeout_sec must be positive",
                id="bootstrap-negative",
            ),
            pytest.param(
                {"cancel_timeout_sec": 0},
                "cancel_timeout_sec must be positive",
                id="cancel-zero",
            ),
            pytest.param(
                {"qlegs_reconcile_interval_sec": 0},
                "qlegs_reconcile_interval_sec must be positive",
                id="qlegs-zero",
            ),
            pytest.param(
                {"strategy": "martingale"}, "unknown strategy", id="strategy-unknown"
            ),
            pytest.param(
                {"strategy": ""},
                "strategy must be a non-empty string",
                id="strategy-empty",
            ),
            pytest.param(
                {"strategy": "inventory_skew"},
                "max_position is required",
                id="skew-without-max-position",
            ),
            pytest.param(
                {"max_position": 1000},
                "max_position is only meaningful",
                id="max-position-without-skew",
            ),
            pytest.param(
                {"strategy": "inventory_skew", "max_position": 0},
                "max_position must be positive",
                id="max-position-zero",
            ),
            pytest.param(
                {"initial_min": 10.0},
                "must be provided together",
                id="half-a-bootstrap-range",
            ),
            pytest.param(
                {"initial_min": 20.0, "initial_max": 10.0},
                "must be less than",
                id="inverted-bootstrap-range",
            ),
        ],
    )
    def test_a_bad_value_is_refused_and_names_the_symbol(
        self, block: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message) as exc:
            resolve_symbol_params(FileConfig(symbols={"TSLA": block}), {})
        assert "[TSLA]" in str(exc.value)

    def test_only_the_offending_symbol_is_named(self) -> None:
        with pytest.raises(ValueError) as exc:
            resolve_symbol_params(
                FileConfig(symbols={"AAPL": {}, "MSFT": {"qty": -5}}), {}
            )
        assert "[MSFT]" in str(exc.value)
        assert "[AAPL]" not in str(exc.value)

    def test_a_valid_skew_configuration_is_accepted(self) -> None:
        params = resolve_symbol_params(
            FileConfig(
                symbols={"TSLA": {"strategy": "inventory_skew", "max_position": 100}}
            ),
            {},
        ).params
        assert params["TSLA"]["max_position"] == 100


# ========================================================================
# 10. main.py wiring — what actually reaches MMBot
# ========================================================================


class TestMainWiring:
    def test_a_three_symbol_config_file_reaches_the_bot_intact(
        self, fake_bot: type[FakeBot]
    ) -> None:
        assert run_main(["--config", str(EXAMPLES / "tech-desk.yaml")]) == 0
        kwargs = fake_bot.instances[0].kwargs
        assert kwargs["gateway_id"] == "MM_TECH_01"
        assert kwargs["symbols"] == ["AAPL", "MSFT", "TSLA"]
        overrides = kwargs["overrides"]
        assert overrides["AAPL"]["gap"] == 0.10
        assert overrides["MSFT"]["gap"] == 0.20
        assert overrides["MSFT"]["qty"] == 200
        assert overrides["TSLA"]["strategy"] == "inventory_skew"
        assert overrides["TSLA"]["max_position"] == 5000
        assert overrides["TSLA"]["drift_ticks"] == 5

    def test_the_flat_kwargs_describe_the_first_symbol(
        self, fake_bot: type[FakeBot]
    ) -> None:
        """MMBot's flat kwargs are the baseline; overrides refine it. They
        must agree for the first symbol or the baseline is a lie."""
        assert run_main(["--config", str(EXAMPLES / "tech-desk.yaml")]) == 0
        kwargs = fake_bot.instances[0].kwargs
        first = kwargs["overrides"][kwargs["symbols"][0]]
        for key in ("strategy", "gap", "qty", "tif", "drift_ticks", "max_position"):
            assert kwargs[key] == first[key]

    def test_the_uniform_shorthand_file_reaches_the_bot(
        self, fake_bot: type[FakeBot]
    ) -> None:
        assert run_main(["--config", str(EXAMPLES / "uniform-desk.yaml")]) == 0
        kwargs = fake_bot.instances[0].kwargs
        assert kwargs["gateway_id"] == "MM_CORE_01"
        assert kwargs["symbols"] == ["AAPL", "MSFT", "TSLA"]
        assert all(p["tif"] == "GTC" for p in kwargs["overrides"].values())

    def test_the_single_symbol_example_file_reaches_the_bot(
        self, fake_bot: type[FakeBot]
    ) -> None:
        assert run_main(["--config", str(EXAMPLES / "single-symbol.yaml")]) == 0
        kwargs = fake_bot.instances[0].kwargs
        assert kwargs["gateway_id"] == "MM_AAPL_01"
        assert (kwargs["gap"], kwargs["qty"]) == (0.08, 300)

    def test_a_cli_scope_refines_a_config_file(
        self, fake_bot: type[FakeBot], tmp_path: Path
    ) -> None:
        path = write(tmp_path, "version: 1\nsymbols:\n  AAPL:\n    gap: 0.1\n")
        assert run_main(["--config", str(path), "--symbol", "AAPL", "--qty", "77"]) == 0
        overrides = fake_bot.instances[0].kwargs["overrides"]
        assert overrides["AAPL"] == {**overrides["AAPL"], "gap": 0.1, "qty": 77}

    @pytest.mark.parametrize(
        "argv, code",
        [
            pytest.param([], 2, id="no-symbol-anywhere"),
            pytest.param(
                ["--symbol", "AAPL", "--symbols", "MSFT"], 2, id="symbols-in-a-scope"
            ),
            pytest.param(
                ["--symbols", "MSFT", "--symbol", "AAPL"],
                2,
                id="symbol-and-symbols",
            ),
            pytest.param(["--symbols", " , "], 2, id="empty-symbols-list"),
            pytest.param(["--symbol", "AAPL", "--symbol", "AAPL"], 2, id="dup-symbol"),
            pytest.param(["--symbol"], 2, id="symbol-without-a-name"),
            pytest.param(
                ["--symbol", "AAPL", "--config", "x.yaml"], 2, id="scoped-config"
            ),
            pytest.param(
                ["--symbol", "AAPL", "--symbols", "MSFT", "--gap", "1"],
                2,
                id="scoped-symbols",
            ),
        ],
    )
    def test_a_malformed_command_line_is_a_usage_error(
        self, argv: list[str], code: int
    ) -> None:
        assert run_main(argv) == code

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["--symbol", "AAPL", "--gap", "-1"], id="bad-gap"),
            pytest.param(
                ["--symbol", "AAPL", "--strategy", "inventory_skew"], id="skew-no-cap"
            ),
            pytest.param(
                ["--symbol", "AAPL", "--startup-session-timeout-sec", "-1"],
                id="bad-session-timeout",
            ),
            pytest.param(
                ["--symbol", "AAPL", "--shutdown-timeout-sec", "0"],
                id="bad-shutdown-timeout",
            ),
        ],
    )
    def test_an_impossible_configuration_exits_one(self, argv: list[str]) -> None:
        assert run_main(argv) == 1

    def test_a_bad_config_file_exits_one(self, tmp_path: Path) -> None:
        assert run_main(["--config", str(write(tmp_path, "version: 9\n"))]) == 1

    def test_a_failing_bot_construction_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(**_kwargs: Any) -> None:
            raise RuntimeError("no sockets today")

        monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", explode)
        assert run_main(["--symbol", "AAPL"]) == 1

    def test_keyboard_interrupt_shuts_the_bot_down_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shutdowns: list[bool] = []

        class Interrupting(FakeBot):
            def run(self) -> int:
                raise KeyboardInterrupt

            def shutdown(self) -> None:
                shutdowns.append(True)

        monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", Interrupting)
        assert run_main(["--symbol", "AAPL"]) == 0
        assert shutdowns == [True]

    @pytest.mark.parametrize(
        "argv, expected",
        [
            pytest.param(["--symbol", "AAPL"], "MM_AAPL_01", id="one-symbol"),
            pytest.param(
                ["--symbol", "AAPL", "--symbol", "MSFT", "--symbol", "TSLA"],
                "MM_AAPL_MSFT_TSLA_01",
                id="derived-from-every-symbol",
            ),
            pytest.param(
                ["--label", "TECH", "--symbol", "AAPL", "--symbol", "MSFT"],
                "MM_TECH_01",
                id="explicit-label",
            ),
            pytest.param(
                ["--symbols", "AAPL,MSFT", "--id-suffix", "09"],
                "MM_AAPL_MSFT_09",
                id="suffix",
            ),
        ],
    )
    def test_gateway_identity(
        self, fake_bot: type[FakeBot], argv: list[str], expected: str
    ) -> None:
        assert run_main(argv) == 0
        assert fake_bot.instances[0].kwargs["gateway_id"] == expected

    def test_a_cli_label_beats_the_config_file(
        self, fake_bot: type[FakeBot], tmp_path: Path
    ) -> None:
        path = write(tmp_path, "version: 1\ngateway:\n  label: FILE\nsymbols: [AAPL]\n")
        assert run_main(["--config", str(path), "--label", "CLI"]) == 0
        assert fake_bot.instances[0].kwargs["gateway_id"] == "MM_CLI_01"

    def test_engine_endpoints_come_from_the_file_when_not_given(
        self, fake_bot: type[FakeBot], tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            "version: 1\ngateway:\n  engine_pull: tcp://10.0.0.1:1\n"
            "  engine_pub: tcp://10.0.0.1:2\nsymbols: [AAPL]\n",
        )
        assert run_main(["--config", str(path)]) == 0
        kwargs = fake_bot.instances[0].kwargs
        assert kwargs["engine_pull"] == "tcp://10.0.0.1:1"
        assert kwargs["engine_pub"] == "tcp://10.0.0.1:2"

    def test_verbosity_is_honoured_wherever_it_appears(
        self, fake_bot: type[FakeBot]
    ) -> None:
        for argv in (
            ["-v", "--symbol", "AAPL"],
            ["--symbol", "AAPL", "-v"],
            ["--symbol", "AAPL", "-vv"],
        ):
            FakeBot.instances = []
            assert run_main(argv) == 0
            assert fake_bot.instances[0].kwargs["verbose"] is True

    def test_an_explicit_log_level_beats_the_config_file(
        self, fake_bot: type[FakeBot], tmp_path: Path
    ) -> None:
        path = write(
            tmp_path, "version: 1\nlogging:\n  level: DEBUG\nsymbols: [AAPL]\n"
        )
        assert run_main(["--config", str(path), "--log-level", "ERROR"]) == 0
        assert fake_bot.instances[0].kwargs["verbose"] is False

    def test_quiet_after_a_symbol_is_hoisted(self, fake_bot: type[FakeBot]) -> None:
        assert run_main(["--symbol", "AAPL", "--quiet"]) == 0
        assert fake_bot.instances[0].kwargs["verbose"] is False

    def test_logging_settings_come_from_the_file(
        self, fake_bot: type[FakeBot], tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            "version: 1\nlogging:\n  level: DEBUG\n  target: stdout\nsymbols: [AAPL]\n",
        )
        assert run_main(["--config", str(path)]) == 0
        # DEBUG turns on the bot's own verbose flow tracing.
        assert fake_bot.instances[0].kwargs["verbose"] is True

    def test_a_gateway_flag_in_a_symbol_scope_is_reported(
        self, fake_bot: type[FakeBot], caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING", logger="edumatcher.mm_bot.main"):
            assert run_main(["--symbol", "AAPL", "--engine-pull", "tcp://x:1"]) == 0
        assert "gateway-wide" in caplog.text
        assert fake_bot.instances[0].kwargs["engine_pull"] == "tcp://x:1"


# ========================================================================
# 11. The bot honours its per-symbol parameters on the wire
# ========================================================================


class _Sock:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.recv_queue: list[list[bytes]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def recv_multipart(self) -> list[bytes]:
        return self.recv_queue.pop(0) if self.recv_queue else [b"", b"{}"]

    def close(self) -> None:
        self.closed = True

    def setsockopt(self, opt: int, val: bytes) -> None:
        pass

    def connect(self, addr: str) -> None:
        pass


class _Poller:
    """Poller that drains the queue, then stops the bot."""

    def __init__(self, sock: _Sock, bot_ref: list[MMBot | None]) -> None:
        self._sock = sock
        self._bot_ref = bot_ref
        self._empty = 0

    def register(self, _sock: object, _event: object) -> None:
        pass

    def poll(self, timeout: int = 0) -> list[tuple[object, int]]:
        if self._sock.recv_queue:
            self._empty = 0
            return [(self._sock, 1)]
        self._empty += 1
        bot = self._bot_ref[0]
        if bot is not None and self._empty >= 2:
            bot._running = False
        return []


GW = "MM_DESK_01"


def _build_bot(
    monkeypatch: pytest.MonkeyPatch,
    symbols: list[str],
    overrides: dict[str, dict[str, Any]] | None = None,
    **baseline: Any,
) -> tuple[MMBot, _Sock, _Sock, list[_Poller]]:
    import edumatcher.mm_bot.bot as bot_mod

    push, sub = _Sock(), _Sock()
    monkeypatch.setattr(bot_mod, "make_pusher", lambda _addr: push)
    monkeypatch.setattr(bot_mod, "make_subscriber", lambda _addr, *_t: sub)
    monkeypatch.setattr("edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None)

    bot_ref: list[MMBot | None] = [None]
    pollers: list[_Poller] = []

    def _poller() -> _Poller:
        poller = _Poller(sub, bot_ref)
        pollers.append(poller)
        return poller

    monkeypatch.setattr("edumatcher.mm_bot.bot.zmq.Poller", _poller)

    kwargs: dict[str, Any] = dict(
        gateway_id=GW,
        symbols=symbols,
        strategy="symmetric",
        gap=0.10,
        gap_was_explicit=True,
        qty=500,
        drift_ticks=3,
        reissue_delay_ms=200,
        tif="DAY",
        heartbeat_interval_sec=5.0,
        startup_session_timeout_sec=0.1,
        bootstrap_timeout_sec=0.1,
        cancel_timeout_sec=1.0,
        shutdown_timeout_sec=0.1,
        qlegs_reconcile_interval_sec=15.0,
        initial_min=95.0,
        initial_max=105.0,
        engine_pull="tcp://127.0.0.1:5555",
        engine_pub="tcp://127.0.0.1:5556",
        verbose=False,
        overrides=overrides,
    )
    kwargs.update(baseline)
    bot = MMBot(**kwargs)
    bot_ref[0] = bot
    return bot, push, sub, pollers


def _queue_startup(sub: _Sock, symbols: list[str]) -> None:
    sub.recv_queue.extend(
        [
            encode(f"system.gateway_auth.{GW}", {"accepted": True}),
            encode(
                f"system.symbols.{GW}",
                {"symbols": [{"symbol": s, "tick_decimals": 2} for s in symbols]},
            ),
            encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
            encode(f"system.quote_legs.{GW}", {"legs": []}),
            encode("session.state", {"state": "CONTINUOUS"}),
        ]
    )


def _quotes(push: _Sock) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for frames in push.sent:
        topic, payload = msg_decode(frames)
        if topic == "quote.new":
            out[payload["symbol"]] = payload
    return out


class TestBotHonoursPerSymbolParameters:
    """The parameters an operator configured are the ones that go on the wire."""

    def test_each_symbol_quotes_its_own_size_tif_and_spread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub, _ = _build_bot(
            monkeypatch,
            ["AAPL", "MSFT", "TSLA"],
            overrides={
                "AAPL": {"gap": 0.10, "qty": 500, "tif": "DAY"},
                "MSFT": {"gap": 0.20, "qty": 200, "tif": "GTC"},
                "TSLA": {"gap": 0.50, "qty": 100, "tif": "DAY"},
            },
        )
        _queue_startup(sub, ["AAPL", "MSFT", "TSLA"])
        bot.run()

        quotes = _quotes(push)
        assert set(quotes) == {"AAPL", "MSFT", "TSLA"}
        expected = {
            "AAPL": (500, "DAY", 10),
            "MSFT": (200, "GTC", 20),
            "TSLA": (100, "DAY", 50),
        }
        for symbol, (qty, tif, spread_ticks) in expected.items():
            payload = quotes[symbol]
            assert (payload["bid_qty"], payload["ask_qty"]) == (qty, qty)
            assert payload["tif"] == tif
            assert (
                payload["ask_price_ticks"] - payload["bid_price_ticks"] == spread_ticks
            )

    def test_a_per_symbol_strategy_is_used_for_that_symbol_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from edumatcher.mm_bot.pricer import InventorySkewPricer, QuotePricer

        bot, _push, sub, _ = _build_bot(
            monkeypatch,
            ["AAPL", "TSLA"],
            overrides={
                "TSLA": {"strategy": "inventory_skew", "max_position": 1000},
            },
        )
        _queue_startup(sub, ["AAPL", "TSLA"])
        bot.run()
        assert isinstance(bot._symbols_state["AAPL"].pricer, QuotePricer)
        assert isinstance(bot._symbols_state["TSLA"].pricer, InventorySkewPricer)

    def test_only_the_symbol_with_a_bootstrap_range_can_start_without_a_book(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per-symbol initial_min/max decides which symbols survive startup."""
        bot, push, sub, _ = _build_bot(
            monkeypatch,
            ["AAPL", "TSLA"],
            overrides={"TSLA": {"initial_min": 180.0, "initial_max": 220.0}},
            initial_min=None,
            initial_max=None,
        )
        _queue_startup(sub, ["AAPL", "TSLA"])
        assert bot.run() == 0
        assert set(_quotes(push)) == {"TSLA"}
        assert bot._symbols_state["AAPL"].startup_failed_reason is not None

    def test_heartbeat_clocks_run_independently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A symbol with a short heartbeat recovers without waiting for a
        symbol configured with a long one."""
        bot, _push, _sub, _ = _build_bot(
            monkeypatch,
            ["FAST", "SLOW"],
            overrides={
                "FAST": {"heartbeat_interval_sec": 1.0},
                "SLOW": {"heartbeat_interval_sec": 1000.0},
            },
        )
        clock = [1000.0]
        monkeypatch.setattr("edumatcher.mm_bot.bot.time.monotonic", lambda: clock[0])
        bot._session_state = "CONTINUOUS"
        for symbol in ("FAST", "SLOW"):
            st = bot._symbols_state[symbol]
            st.state = BotState.QUOTING
            st.pricer = __import__(
                "edumatcher.mm_bot.pricer", fromlist=["QuotePricer"]
            ).QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
            st.pricer.set_mid(100.0)
            st.last_heartbeat = clock[0]
            st.last_quote_sent_at = clock[0]

        clock[0] += 2.0
        bot._push_sock = None  # only the state transition matters here
        bot._tick()

        assert bot._symbols_state["FAST"].state == BotState.REISSUING
        assert bot._symbols_state["SLOW"].state == BotState.QUOTING

    def test_the_loop_wakes_often_enough_for_the_most_impatient_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub, _ = _build_bot(
            monkeypatch,
            ["PATIENT", "IMPATIENT"],
            overrides={
                "PATIENT": {"heartbeat_interval_sec": 60.0},
                "IMPATIENT": {"heartbeat_interval_sec": 0.4},
            },
            reissue_delay_ms=5000,
        )
        assert bot._poll_timeout_ms(["PATIENT"]) == 2500
        assert bot._poll_timeout_ms(["PATIENT", "IMPATIENT"]) == 200

    def test_a_zero_reissue_delay_does_not_produce_a_busy_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL"], reissue_delay_ms=0)
        assert bot._poll_timeout_ms(["AAPL"]) == 50


class TestBotOverrideContract:
    """``overrides`` is a narrow, checked surface, not an escape hatch."""

    def test_an_override_for_an_unquoted_symbol_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValueError, match="does not quote: NVDA"):
            _build_bot(monkeypatch, ["AAPL"], overrides={"NVDA": {"gap": 0.2}})

    def test_an_unknown_override_key_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValueError, match=r"\[AAPL\] unknown parameter"):
            _build_bot(monkeypatch, ["AAPL"], overrides={"AAPL": {"spread": 0.2}})

    def test_no_overrides_means_every_symbol_shares_the_baseline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL", "MSFT"], qty=321)
        assert [bot._symbols_state[s].qty for s in ("AAPL", "MSFT")] == [321, 321]

    @pytest.mark.parametrize(
        "attribute, value",
        [
            ("gap", 0.33),
            ("qty", 77),
            ("tif", "GTC"),
            ("strategy", "inventory_skew"),
            ("drift_ticks", 8),
            ("_max_position", 900),
            ("_reissue_delay_sec", 0.9),
            ("_heartbeat_interval_sec", 9.0),
            ("_bootstrap_timeout_sec", 9.0),
            ("_cancel_timeout_sec", 9.0),
            ("_qlegs_reconcile_interval_sec", 9.0),
            ("_initial_min", 9.0),
            ("_initial_max", 19.0),
            ("_last_heartbeat", 1234.0),
            ("_tick_size", 0.05),
            ("_mm_max_spread_ticks", 6),
            ("_pricer", None),
            ("_state", BotState.PAUSED),
            ("_quote_id", "Q-1"),
            ("_bid_order_id", "B-1"),
            ("_ask_order_id", "A-1"),
            ("_quoted_at_mid", 101.5),
            ("_reissue_at", 42.0),
            ("_last_quote_sent_at", 43.0),
            ("_last_qlegs_reconcile", 44.0),
            ("_awaiting_cancel_for_reissue", True),
        ],
    )
    def test_single_symbol_attribute_access_still_works(
        self, monkeypatch: pytest.MonkeyPatch, attribute: str, value: Any
    ) -> None:
        """The pre-multi-symbol scalar attributes remain readable and
        writable for a one-symbol bot, so existing call sites keep working."""
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL"])
        setattr(bot, attribute, value)
        assert getattr(bot, attribute) == value

    @pytest.mark.parametrize(
        "attribute, expected",
        [
            ("symbol", "AAPL"),
            ("net_position", 0),
            ("avg_cost", 0.0),
            ("_pending_fills_compat", []),
        ],
    )
    def test_read_only_single_symbol_views(
        self, monkeypatch: pytest.MonkeyPatch, attribute: str, expected: Any
    ) -> None:
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL", "MSFT"])
        assert getattr(bot, attribute) == expected

    def test_the_heartbeat_reset_applies_to_every_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """There is one conceptual "reset the heartbeat clock" action, and
        with per-symbol clocks it has to mean all of them."""
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL", "MSFT"])
        bot._last_heartbeat = 555.0
        assert [bot._symbols_state[s].last_heartbeat for s in bot.symbols] == [
            555.0,
            555.0,
        ]

    def test_a_symbols_list_of_blanks_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValueError, match="at least one non-empty entry"):
            _build_bot(monkeypatch, [" ", ""])

    def test_shutdown_stops_the_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL"])
        bot._running = True
        bot.shutdown()
        assert bot._running is False

    def test_an_unrecognised_topic_is_counted_not_crashed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub, _ = _build_bot(monkeypatch, ["AAPL"], verbose=True)
        bot._dispatch("weather.stockholm", {"rain": True})
        assert bot._debug_counts["incoming_unhandled"] == 1
        assert bot._debug_counts["incoming_topic_other"] == 1


# ========================================================================
# 12. Resilience — a quiet or misbehaving engine must not take the bot down
# ========================================================================


class TestStartupResilience:
    """Startup fails closed, per symbol, and never on a malformed payload."""

    def test_a_silent_engine_fails_startup_rather_than_quoting_blind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub, _ = _build_bot(monkeypatch, ["AAPL"])
        assert bot.run() == 1
        assert _quotes(push) == {}

    def test_a_session_update_during_authentication_is_not_lost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """session.state can arrive before the auth ack; dropping it would
        strand the bot waiting for a state it has already been told."""
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        sub.recv_queue.extend(
            [
                encode("session.state", {"state": "CONTINUOUS"}),
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode(
                    f"system.symbols.{GW}",
                    {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                ),
                encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
            ]
        )
        assert bot.run() == 0
        assert bot._session_state == "CONTINUOUS"
        assert set(_quotes(push)) == {"AAPL"}

    def test_a_symbol_missing_from_the_engines_universe_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL", "NOPE"])
        _queue_startup(sub, ["AAPL"])
        assert bot.run() == 0
        assert set(_quotes(push)) == {"AAPL"}
        assert "not in symbol list" in str(
            bot._symbols_state["NOPE"].startup_failed_reason
        )

    def test_unusable_obligation_metadata_is_ignored_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        sub.recv_queue.extend(
            [
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode(
                    f"system.symbols.{GW}",
                    {
                        "symbols": [
                            {
                                "symbol": "AAPL",
                                "tick_decimals": 2,
                                "mm_max_spread_ticks": "wide",
                            }
                        ]
                    },
                ),
                encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
                encode("session.state", {"state": "CONTINUOUS"}),
            ]
        )
        assert bot.run() == 0
        assert bot._symbols_state["AAPL"].mm_max_spread_ticks is None
        assert set(_quotes(push)) == {"AAPL"}

    def test_a_trade_arriving_during_startup_seeds_the_reference_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without this the symbol would have no mid and fail startup."""
        bot, push, sub, _ = _build_bot(
            monkeypatch, ["AAPL"], initial_min=None, initial_max=None
        )
        sub.recv_queue.extend(
            [
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode(
                    f"system.symbols.{GW}",
                    {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                ),
                encode("trade.executed", {"symbol": "AAPL", "price": 100.0}),
                encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
                encode("session.state", {"state": "CONTINUOUS"}),
            ]
        )
        assert bot.run() == 0
        assert set(_quotes(push)) == {"AAPL"}

    def test_a_bootstrap_quote_for_another_symbol_is_not_adopted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        sub.recv_queue.extend(
            [
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode(
                    f"system.symbols.{GW}",
                    {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                ),
                encode(
                    f"system.quote_bootstrap.{GW}",
                    {
                        "quotes": [
                            {
                                "symbol": "MSFT",
                                "state": "ACTIVE",
                                "quote_id": "Q-MSFT",
                                "bid_price": 10.0,
                                "ask_price": 11.0,
                            },
                            {
                                "symbol": "AAPL",
                                "state": "ACTIVE",
                                "quote_id": "",
                                "bid_price": None,
                                "ask_price": None,
                            },
                        ]
                    },
                ),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
                encode("session.state", {"state": "CONTINUOUS"}),
            ]
        )
        assert bot.run() == 0
        assert bot._symbols_state["AAPL"].quote_id != "Q-MSFT"
        assert "Q-MSFT" not in bot._quote_id_to_symbol

    def test_an_inactive_bootstrap_quote_seeds_the_reference_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub, _ = _build_bot(
            monkeypatch, ["AAPL"], initial_min=None, initial_max=None
        )
        sub.recv_queue.extend(
            [
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode(
                    f"system.symbols.{GW}",
                    {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                ),
                encode(
                    f"system.quote_bootstrap.{GW}",
                    {
                        "quotes": [
                            {"symbol": "MSFT", "state": "INACTIVE"},
                            {"symbol": "AAPL", "state": "INACTIVE"},
                            {
                                "symbol": "AAPL",
                                "state": "INACTIVE",
                                "bid_price": 99.0,
                                "ask_price": 101.0,
                            },
                        ]
                    },
                ),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
                encode("session.state", {"state": "CONTINUOUS"}),
            ]
        )
        assert bot.run() == 0
        assert set(_quotes(push)) == {"AAPL"}

    def test_an_engine_that_never_lists_its_symbols_fails_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        sub.recv_queue.append(encode(f"system.gateway_auth.{GW}", {"accepted": True}))
        assert bot.run() == 1
        assert _quotes(push) == {}

    def test_a_non_trading_session_starts_every_symbol_paused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The session phase is learned during the SYMBOLS wait here, which
        is exactly when a bot started before the open sees it."""
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL", "MSFT"])
        sub.recv_queue.extend(
            [
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode("session.state", {"state": "PRE_OPEN"}),
                encode(
                    f"system.symbols.{GW}",
                    {
                        "symbols": [
                            {"symbol": s, "tick_decimals": 2} for s in ("AAPL", "MSFT")
                        ]
                    },
                ),
                encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
                encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
            ]
        )
        assert bot.run() == 0
        assert _quotes(push) == {}
        assert all(
            bot._symbols_state[s].state == BotState.PAUSED for s in ("AAPL", "MSFT")
        )

    @pytest.mark.parametrize(
        "qlegs, still_adopted",
        [
            pytest.param(
                {"legs": [{"symbol": "AAPL", "quote_id": "Q-NEW"}]},
                False,
                id="engine-holds-a-different-quote",
            ),
            pytest.param({"legs": []}, True, id="engine-reports-no-legs"),
        ],
    )
    def test_startup_reconciles_an_adopted_quote_against_qlegs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        qlegs: dict[str, Any],
        still_adopted: bool,
    ) -> None:
        """QBOOT says the bot owns Q-OLD. A QLEGS snapshot naming a
        *different* quote means the engine has moved on, so the adoption is
        dropped. An empty snapshot is not treated as proof at startup — the
        periodic reconciliation owns that case once the bot is running.
        """
        bot, _push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        sub.recv_queue.extend(
            [
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode(
                    f"system.symbols.{GW}",
                    {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                ),
                encode(
                    f"system.quote_bootstrap.{GW}",
                    {
                        "quotes": [
                            {
                                "symbol": "AAPL",
                                "state": "ACTIVE",
                                "quote_id": "Q-OLD",
                                "bid_price": 99.0,
                                "ask_price": 101.0,
                            }
                        ]
                    },
                ),
                encode(f"system.quote_legs.{GW}", qlegs),
                encode("session.state", {"state": "CONTINUOUS"}),
            ]
        )
        assert bot.run() == 0
        assert (bot._symbols_state["AAPL"].quote_id == "Q-OLD") is still_adopted

    def test_unrelated_traffic_during_startup_is_absorbed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Book and trade traffic arrives on the same socket as the startup
        replies; it must be consumed, not mistaken for one of them."""
        bot, push, sub, _ = _build_bot(
            monkeypatch, ["AAPL"], initial_min=None, initial_max=None
        )
        sub.recv_queue.extend(
            [
                encode("book.AAPL", {"bids": [], "asks": []}),
                encode(f"system.gateway_auth.{GW}", {"accepted": True}),
                encode("trade.executed", {"symbol": "MSFT", "price": 1.0}),
                encode(
                    f"system.symbols.{GW}",
                    {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                ),
                encode(f"system.quote_bootstrap.{GW}", {"quotes": []}),
                encode(
                    "book.AAPL",
                    {"bids": [{"price": 99.0}], "asks": [{"price": 101.0}]},
                ),
                encode(f"system.quote_legs.{GW}", {"legs": []}),
                encode("session.state", {"state": "CONTINUOUS"}),
            ]
        )
        assert bot.run() == 0
        assert set(_quotes(push)) == {"AAPL"}


class TestSocketLifecycle:
    def test_closing_twice_is_harmless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        bot._setup_sockets()
        bot._close_sockets()
        bot._close_sockets()
        assert (push.closed, sub.closed) == (True, True)

    def test_sending_without_a_socket_is_a_no_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub, _ = _build_bot(monkeypatch, ["AAPL"])
        bot._send([b"quote.new", b"{}"])
        assert push.sent == []

    def test_an_empty_frame_list_is_not_counted_as_a_topic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub, _ = _build_bot(monkeypatch, ["AAPL"], verbose=True)
        bot._setup_sockets()
        bot._send([])
        assert push.sent == [[]]
        assert bot._debug_counts["outgoing_total"] == 1


class TestLifecycleAcrossSymbols:
    """Session, halt and shutdown events act on every symbol, independently."""

    def _running_bot(
        self, monkeypatch: pytest.MonkeyPatch, symbols: list[str]
    ) -> tuple[MMBot, _Sock, _Sock]:
        bot, push, sub, _ = _build_bot(monkeypatch, symbols)
        _queue_startup(sub, symbols)
        bot.run()
        # run() closes its sockets on the way out; these tests carry on
        # driving the same bot, so put them back.
        bot._push_sock, bot._sub_sock = push, sub
        for symbol in symbols:
            st = bot._symbols_state[symbol]
            st.state = BotState.QUOTING
            st.quote_id = f"Q-{symbol}"
            bot._quote_id_to_symbol[st.quote_id] = symbol
        push.sent.clear()
        return bot, push, sub

    def test_leaving_continuous_pulls_every_symbols_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub = self._running_bot(monkeypatch, ["AAPL", "MSFT"])
        bot._handle_session_state({"state": "CLOSING_AUCTION"})
        cancelled = {
            msg_decode(f)[1]["symbol"]
            for f in push.sent
            if msg_decode(f)[0] == "quote.cancel"
        }
        assert cancelled == {"AAPL", "MSFT"}
        assert all(
            bot._symbols_state[s].state == BotState.PAUSED for s in ("AAPL", "MSFT")
        )

    def test_returning_to_continuous_schedules_every_symbol_to_requote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL", "MSFT"])
        bot._handle_session_state({"state": "CLOSED"})
        bot._handle_session_state({"state": "CONTINUOUS"})
        assert all(
            bot._symbols_state[s].reissue_at is not None for s in ("AAPL", "MSFT")
        )

    def test_shutdown_waits_for_every_symbols_cancel_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub = self._running_bot(monkeypatch, ["AAPL", "MSFT"])
        sub.recv_queue.extend(
            [
                encode(
                    f"quote.status.{GW}",
                    {"quote_id": "Q-AAPL", "status": "CANCELLED"},
                ),
                encode(
                    f"quote.status.{GW}",
                    {"quote_id": "Q-MSFT", "status": "CANCELLED"},
                ),
            ]
        )
        bot._do_shutdown()
        cancelled = {
            msg_decode(f)[1]["symbol"]
            for f in push.sent
            if msg_decode(f)[0] == "quote.cancel"
        }
        assert cancelled == {"AAPL", "MSFT"}

    def test_a_resume_for_a_symbol_this_bot_does_not_quote_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL"])
        bot._handle_circuit_breaker_resume("NVDA")
        assert bot._symbols_state["AAPL"].state == BotState.QUOTING

    def test_a_halt_for_a_symbol_this_bot_does_not_quote_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub = self._running_bot(monkeypatch, ["AAPL"])
        bot._handle_circuit_breaker_halt("NVDA")
        assert push.sent == []
        assert bot._symbols_state["AAPL"].state == BotState.QUOTING

    def test_events_for_an_unknown_quote_do_not_disturb_other_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ack or status the bot cannot attribute must not be guessed
        onto a symbol whose quote is perfectly healthy."""
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL", "MSFT"])
        before = {s: bot._symbols_state[s].quote_id for s in bot.symbols}
        bot._handle_quote_ack({"quote_id": "Q-UNKNOWN", "accepted": True})
        bot._handle_quote_status({"quote_id": "Q-UNKNOWN", "status": "CANCELLED"})
        assert bot._symbols_state["MSFT"].quote_id == before["MSFT"]

    def test_a_paused_symbol_ignores_a_late_quote_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL"])
        bot._symbols_state["AAPL"].state = BotState.PAUSED
        bot._handle_quote_status({"quote_id": "Q-AAPL", "status": "CANCELLED"})
        assert bot._symbols_state["AAPL"].reissue_at is None

    def test_an_incomplete_qlegs_snapshot_is_still_reconciled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL"])
        bot._reconcile_qlegs(
            {
                "complete": False,
                "legs": [{"symbol": "AAPL", "quote_id": "Q-OTHER"}],
            }
        )
        assert bot._symbols_state["AAPL"].quote_id is None

    def test_a_qlegs_snapshot_for_an_untracked_symbol_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL"])
        bot._reconcile_qlegs({"legs": [{"symbol": "NVDA", "quote_id": "Q-X"}]})
        assert bot._symbols_state["AAPL"].quote_id == "Q-AAPL"

    def test_a_fill_reaches_its_symbol_through_the_normal_dispatch_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._running_bot(monkeypatch, ["AAPL", "MSFT"])
        bot._symbols_state["MSFT"].bid_order_id = "O-MSFT-BID"
        bot._dispatch(
            f"order.fill.{GW}",
            {"order_id": "O-MSFT-BID", "fill_qty": 100, "fill_price": 50.0},
        )
        assert bot._symbols_state["MSFT"].net_position == 100
        assert bot._symbols_state["AAPL"].net_position == 0

    def test_a_due_reissue_outside_continuous_waits_instead_of_quoting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub = self._running_bot(monkeypatch, ["AAPL"])
        bot._session_state = "CLOSED"
        st = bot._symbols_state["AAPL"]
        st.state = BotState.WAITING_FOR_SESSION
        st.reissue_at = 0.0
        bot._tick()
        assert _quotes(push) == {}
        assert st.state == BotState.WAITING_FOR_SESSION

    def test_a_termination_signal_stops_the_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import signal as signal_mod

        bot, _push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
        handlers: dict[int, Any] = {}
        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal",
            lambda sig, handler: handlers.__setitem__(sig, handler),
        )
        _queue_startup(sub, ["AAPL"])
        bot.run()
        bot._running = True
        handlers[signal_mod.SIGTERM](signal_mod.SIGTERM, None)
        assert bot._running is False


class TestUnattributableEvents:
    """Events the bot cannot tie to one of its symbols are ignored, never
    guessed onto a healthy symbol and never fatal."""

    def _bot(self, monkeypatch: pytest.MonkeyPatch) -> tuple[MMBot, _Sock, _Sock]:
        bot, push, sub, _ = _build_bot(monkeypatch, ["AAPL", "MSFT"], verbose=True)
        _queue_startup(sub, ["AAPL", "MSFT"])
        bot.run()
        bot._push_sock, bot._sub_sock = push, sub
        push.sent.clear()
        return bot, push, sub

    def test_a_quote_event_mapped_to_a_symbol_the_bot_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        bot._quote_id_to_symbol["Q-GHOST"] = "NVDA"
        bot._handle_quote_ack({"quote_id": "Q-GHOST", "accepted": True})
        bot._handle_quote_status({"quote_id": "Q-GHOST", "status": "CANCELLED"})
        assert all(
            bot._symbols_state[s].startup_failed_reason is None for s in bot.symbols
        )

    def test_an_ack_with_no_outstanding_send_for_that_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        bot._pending_ack_symbols.clear()
        bot._quote_id_to_symbol["Q-X"] = "AAPL"
        bot._handle_quote_ack(
            {
                "quote_id": "Q-X",
                "accepted": True,
                "bid_order_id": "B",
                "ask_order_id": "A",
            }
        )
        assert bot._symbols_state["AAPL"].quote_id == "Q-X"

    def test_a_fill_for_an_unknown_order_is_dropped_once_legs_are_known(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        bot._symbols_state["AAPL"].bid_order_id = "B-AAPL"
        bot._handle_order_fill({"order_id": "B-SOMEONE-ELSE", "fill_qty": 10})
        assert bot._pending_fills == []
        assert bot._symbols_state["AAPL"].net_position == 0

    def test_a_fill_for_a_known_leg_is_logged_in_verbose_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        bot._symbols_state["AAPL"].ask_order_id = "A-AAPL"
        bot._handle_order_fill(
            {"order_id": "A-AAPL", "fill_qty": 10, "fill_price": 100.0}
        )
        assert bot._symbols_state["AAPL"].net_position == -10

    def test_a_cancellation_for_an_unknown_order_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        bot._handle_order_cancelled({"order_id": "NOT-OURS"})

    def test_session_and_halt_events_leave_idle_symbols_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub = self._bot(monkeypatch)
        for symbol in bot.symbols:
            bot._symbols_state[symbol].state = BotState.WAITING_FOR_SESSION
        bot._handle_session_state({"state": "CLOSED"})
        bot._handle_session_state({"state": "CONTINUOUS"})
        bot._handle_circuit_breaker_halt("AAPL")
        assert push.sent == []

    def test_a_resumed_session_without_a_reference_price_does_not_schedule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        for symbol in bot.symbols:
            st = bot._symbols_state[symbol]
            st.state = BotState.PAUSED
            st.pricer = None
        bot._handle_session_state({"state": "CONTINUOUS"})
        assert all(bot._symbols_state[s].reissue_at is None for s in bot.symbols)

    def test_a_due_reissue_in_an_unexpected_state_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub = self._bot(monkeypatch)
        st = bot._symbols_state["AAPL"]
        st.state = BotState.PAUSED
        st.reissue_at = 0.0
        bot._tick()
        assert _quotes(push) == {}
        assert st.reissue_at is None

    def test_a_qlegs_leg_without_an_order_id_is_tolerated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        st = bot._symbols_state["AAPL"]
        st.state = BotState.QUOTING
        st.quote_id = "Q-AAPL"
        st.bid_order_id, st.ask_order_id = "B", "A"
        bot._reconcile_qlegs(
            {"legs": [{"symbol": "AAPL", "quote_id": "Q-AAPL", "order_id": ""}]}
        )
        assert st.quote_id == "Q-AAPL"

    def test_unrelated_traffic_during_shutdown_does_not_end_the_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, sub = self._bot(monkeypatch)
        st = bot._symbols_state["AAPL"]
        st.state = BotState.QUOTING
        st.quote_id = "Q-AAPL"
        bot._quote_id_to_symbol["Q-AAPL"] = "AAPL"
        sub.recv_queue.append(encode("book.AAPL", {"bids": [], "asks": []}))
        bot._do_shutdown()
        assert sub.recv_queue == []

    def test_a_book_update_before_a_pricer_exists_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        bot._symbols_state["AAPL"].pricer = None
        bot._handle_book({"bids": [{"price": 1.0}]}, symbol="AAPL")
        bot._handle_book({"bids": [{"price": 1.0}]}, symbol="NVDA")

    def test_an_inactivation_while_a_cancel_is_in_flight_clears_both(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = self._bot(monkeypatch)
        st = bot._symbols_state["AAPL"]
        st.state = BotState.REPRICING
        st.quote_id = "Q-AAPL"
        st.awaiting_cancel_for_reissue = True
        bot._quote_id_to_symbol["Q-AAPL"] = "AAPL"
        bot._handle_quote_status(
            {"quote_id": "Q-AAPL", "status": "INACTIVE_BID_FILLED"}
        )
        assert st.awaiting_cancel_for_reissue is False
        assert st.quote_id is None

    def test_a_continuous_session_leaves_a_still_quoting_symbol_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, _sub = self._bot(monkeypatch)
        for symbol in bot.symbols:
            bot._symbols_state[symbol].state = BotState.QUOTING
        bot._handle_session_state({"state": "CONTINUOUS"})
        assert push.sent == []
        assert all(bot._symbols_state[s].state == BotState.QUOTING for s in bot.symbols)


# ========================================================================
# 14. The documented examples are real, loadable files
# ========================================================================


@pytest.mark.parametrize(
    "name", ["tech-desk.yaml", "single-symbol.yaml", "uniform-desk.yaml"]
)
def test_every_documented_example_loads_and_resolves(name: str) -> None:
    resolved = resolve_symbol_params(load_bot_config(EXAMPLES / name), {})
    assert resolved.symbols
    assert set(resolved.params) == set(resolved.symbols)


def test_build_parser_still_accepts_a_plain_single_symbol_invocation() -> None:
    from edumatcher.mm_bot import main as mm_main

    args: argparse.Namespace = mm_main.build_parser().parse_args(
        ["--symbol", "AAPL", "-vv", "--quiet", "--log-level", "ERROR"]
    )
    assert (args.symbol, args.verbose, args.quiet, args.log_level) == (
        "AAPL",
        2,
        True,
        "ERROR",
    )
