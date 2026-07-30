"""Tests for the compiled configuration artifact's schema and codec.

These exercise the codec against the real config dataclasses rather than
stand-ins. The whole point of compiling is that the artifact is the only thing
a running exchange reads, so a value that does not survive the round trip is a
value the exchange silently loses.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from pathlib import PurePath
from typing import Any, get_args, get_origin, get_type_hints

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.config_artifact import (
    SCHEMA_VERSION,
    _is_optional,
    _unwrap_optional,
    ArtifactError,
    ArtifactMeta,
    CompiledConfig,
    decode,
    encode,
    from_jsonable,
    source_digest,
    to_jsonable,
)
from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig, CircuitBreakerLevel
from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    MMQuoteSeed,
    ScheduleConfig,
    SymbolConfig,
)
from edumatcher.log_srv.config import LogClientConfig, LogServerConfig
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.models.order import TIF, SmpAction
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.ralf_gateway.config import RalfGatewayConfig


def _meta(**over: Any) -> ArtifactMeta:
    base = {
        "schema_version": SCHEMA_VERSION,
        "compiler_version": "0.17.0",
        "compiled_at": "2026-07-30T09:00:00.000Z",
        "source_path": "/src/engine_config.yaml",
        "source_sha256": "0" * 64,
    }
    base.update(over)
    return ArtifactMeta(**base)  # type: ignore[arg-type]


def _engine() -> EngineConfig:
    """An engine config exercising nesting, enums, optionals and collections."""
    return EngineConfig(
        symbols={
            "AAPL": SymbolConfig(
                name="AAPL",
                level="STRICT",
                tick_decimals=2,
                outstanding_shares=15_400_000_000,
                last_buy_price=149.7,
                last_sell_price=None,
                market_maker_quotes=[
                    MMQuoteSeed(
                        gateway_id="MM01",
                        bid_price=149.0,
                        ask_price=151.0,
                        bid_qty=500,
                        ask_qty=500,
                        tif=TIF.GTC,
                        quote_id="SEED-MM01-AAPL",
                    )
                ],
                collar=CollarConfig(
                    symbol="AAPL", static_band_pct=0.2, dynamic_band_pct=0.02
                ),
                circuit_breaker=CircuitBreakerConfig(
                    symbol="AAPL",
                    levels=[
                        CircuitBreakerLevel("L1", 0.07, 300_000_000_000),
                        CircuitBreakerLevel("L3", 0.20, None),
                    ],
                ),
            )
        },
        fix_gateways={
            "MM01": FixGatewayConfig(
                id="MM01",
                role=ParticipantRole.MARKET_MAKER,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
                smp_action=SmpAction.CANCEL_BOTH,
            )
        },
        sessions_enabled=True,
        schedule=ScheduleConfig(),
    )


def _config(**over: Any) -> CompiledConfig:
    base: dict[str, Any] = {
        "meta": _meta(),
        "engine": _engine(),
        "alf_gateway": AlfGatewayConfig(),
        "balf_gateway": BalfGatewayConfig(),
        "market_data_gateway": MarketDataGatewayConfig(),
        "post_trade_gateway": RalfGatewayConfig(),
        "dc_gateway": DcGatewayConfig(),
        "log_server": LogServerConfig(),
        "log_client": LogClientConfig(),
        "api_gateways": {
            # A tuple, as the real loader builds it — the field is declared
            # `tuple[ApiCredential, ...]` and the codec rebuilds the declared
            # type, so a list here would not round-trip to itself.
            "desk": ApiGatewayConfig(
                credentials=(ApiCredential(api_key="k", gateway_id="GW01"),)
            )
        },
    }
    base.update(over)
    return CompiledConfig(**base)


class TestRoundTrip:
    def test_survives_a_full_round_trip_unchanged(self) -> None:
        original = _config()
        assert decode(encode(original)) == original

    def test_rebuilds_enums_rather_than_leaving_bare_strings(self) -> None:
        # `TIF.GTC == "GTC"` is true for a str-enum, so equality alone would
        # not catch a decoder that never reconstructed the member.
        seed = decode(encode(_config())).engine.symbols["AAPL"].market_maker_quotes[0]

        assert isinstance(seed.tif, TIF)
        assert isinstance(
            decode(encode(_config())).engine.fix_gateways["MM01"].role, ParticipantRole
        )

    def test_keeps_an_absent_optional_absent(self) -> None:
        # Absent and zero are different facts everywhere in this codebase; a
        # codec that conflated them would undo that in one move.
        symbol = decode(encode(_config())).engine.symbols["AAPL"]

        assert symbol.last_sell_price is None
        assert symbol.last_buy_price == 149.7

    def test_keeps_a_rest_of_day_halt_distinct_from_a_zero_length_one(self) -> None:
        levels = (
            decode(encode(_config())).engine.symbols["AAPL"].circuit_breaker.levels  # type: ignore[union-attr]
        )

        assert levels[0].halt_duration_ns == 300_000_000_000
        assert levels[1].halt_duration_ns is None

    def test_rebuilds_nested_dataclasses_not_dicts(self) -> None:
        symbol = decode(encode(_config())).engine.symbols["AAPL"]

        assert isinstance(symbol.collar, CollarConfig)
        assert isinstance(symbol.circuit_breaker, CircuitBreakerConfig)
        assert isinstance(symbol.circuit_breaker.levels[0], CircuitBreakerLevel)

    def test_preserves_list_order(self) -> None:
        levels = (
            decode(encode(_config())).engine.symbols["AAPL"].circuit_breaker.levels  # type: ignore[union-attr]
        )
        assert [lvl.name for lvl in levels] == ["L1", "L3"]

    def test_carries_every_declared_section(self) -> None:
        # A section silently missing from the artifact would surface as a
        # process starting on defaults it was never configured with.
        payload = json.loads(encode(_config()))
        assert set(payload) == {f.name for f in dataclasses.fields(CompiledConfig)}


class TestDeterminism:
    def test_the_same_config_compiles_byte_for_byte_the_same(self) -> None:
        # "Has the configuration changed?" should be answerable with a
        # checksum, and a redeploy should not look like an edit.
        assert encode(_config()) == encode(_config())

    def test_key_order_does_not_depend_on_insertion_order(self) -> None:
        first = _config(api_gateways={"a": ApiGatewayConfig(), "b": ApiGatewayConfig()})
        second = _config(
            api_gateways={"b": ApiGatewayConfig(), "a": ApiGatewayConfig()}
        )

        assert encode(first) == encode(second)

    def test_ends_with_a_newline(self) -> None:
        assert encode(_config()).endswith("\n")


class TestSchemaVersion:
    def test_refuses_an_artifact_from_a_future_build(self) -> None:
        text = encode(_config(meta=_meta(schema_version=SCHEMA_VERSION + 1)))

        with pytest.raises(ArtifactError, match="schema version"):
            decode(text)

    def test_names_the_command_that_fixes_it(self) -> None:
        text = encode(_config(meta=_meta(schema_version=99)))

        with pytest.raises(ArtifactError, match="pm-config-compile"):
            decode(text)

    def test_rejects_an_artifact_with_no_meta(self) -> None:
        with pytest.raises(ArtifactError, match="schema_version"):
            decode(json.dumps({"engine": {}}))

    def test_rejects_text_that_is_not_json(self) -> None:
        with pytest.raises(ArtifactError, match="not valid JSON"):
            decode("symbols:\n  AAPL: {}\n")

    def test_rejects_a_json_document_that_is_not_an_object(self) -> None:
        with pytest.raises(ArtifactError, match="JSON object"):
            decode("[]")


class TestSourceDigest:
    def test_identical_text_digests_identically(self) -> None:
        assert source_digest("symbols:\n") == source_digest("symbols:\n")

    def test_a_single_character_change_is_visible(self) -> None:
        assert source_digest("a: 1\n") != source_digest("a: 2\n")

    def test_whitespace_counts_as_a_change(self) -> None:
        # The digest answers "is the deployed artifact built from this exact
        # file?", not "is it semantically equivalent?" — a reformat should
        # prompt a recompile rather than be silently accepted.
        assert source_digest("a: 1\n") != source_digest("a:  1\n")


class TestCodecEdges:
    def test_an_unknown_field_in_the_artifact_is_ignored(self) -> None:
        # Forward compatibility within one schema version: a newer compiler may
        # add a field this build has no use for.
        rebuilt = from_jsonable(
            ArtifactMeta,
            {**to_jsonable(_meta()), "unexpected": "value"},
        )
        assert rebuilt == _meta()

    def test_an_enum_value_outside_its_members_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            from_jsonable(TIF, "NOT_A_TIF")

    def test_to_jsonable_leaves_no_dataclass_or_enum_behind(self) -> None:
        def walk(node: Any) -> None:
            assert not dataclasses.is_dataclass(node)
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(to_jsonable(_config()))


# ---------------------------------------------------------------------------
# Declared-type conformance
#
# mypy already enforces this for normal source, but `pyproject.toml` disables
# `arg-type` for `tests.*`, so a fixture can construct a config whose runtime
# types contradict its own annotations — which is how a list reached a field
# declared `tuple[ApiCredential, ...]` and showed up as a confusing round-trip
# failure rather than a type error.
#
# The codec rebuilds whatever the annotation declares, so any such mismatch
# silently changes the value on the way through a compile.
# ---------------------------------------------------------------------------

_PRIMITIVES = (bool, int, float, str, PurePath)


def _mismatches(tp: Any, value: Any, path: str) -> list[str]:
    """Return one description per field whose value contradicts its annotation."""
    if tp is Any:
        return []

    def wrong(expected: str) -> list[str]:
        return [f"{path}: declared {expected}, got {type(value).__name__}"]

    if _is_optional(tp):
        return [] if value is None else _mismatches(_unwrap_optional(tp), value, path)

    origin = get_origin(tp)
    if origin is list:
        if not isinstance(value, list):
            return wrong("list")
        item_tp = (get_args(tp) or (Any,))[0]
        return [
            m
            for i, v in enumerate(value)
            for m in _mismatches(item_tp, v, f"{path}[{i}]")
        ]
    if origin is tuple:
        if not isinstance(value, tuple):
            return wrong("tuple")
        args = get_args(tp)
        if not args:
            return []
        if len(args) == 2 and args[1] is Ellipsis:
            return [
                m
                for i, v in enumerate(value)
                for m in _mismatches(args[0], v, f"{path}[{i}]")
            ]
        return [
            m
            for i, (arg, v) in enumerate(zip(args, value))
            for m in _mismatches(arg, v, f"{path}[{i}]")
        ]
    if origin is dict:
        if not isinstance(value, dict):
            return wrong("dict")
        key_tp, val_tp = get_args(tp) or (Any, Any)
        out: list[str] = []
        for k, v in value.items():
            out += _mismatches(key_tp, k, f"{path}.<key {k!r}>")
            out += _mismatches(val_tp, v, f"{path}[{k!r}]")
        return out

    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return [] if isinstance(value, tp) else wrong(tp.__name__)
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        if not isinstance(value, tp):
            return wrong(tp.__name__)
        hints = get_type_hints(tp)
        return [
            m
            for f in dataclasses.fields(tp)
            for m in _mismatches(
                hints[f.name], getattr(value, f.name), f"{path}.{f.name}"
            )
        ]

    if isinstance(tp, type) and issubclass(tp, _PRIMITIVES):
        # bool is a subclass of int, so an `int` field holding True would pass a
        # naive isinstance check — and a flag silently standing in for a count
        # is exactly the sort of thing this test is for.
        if tp is int and isinstance(value, bool):
            return wrong("int")
        # int where float is declared is the usual numeric-tower allowance.
        if tp is float and isinstance(value, int) and not isinstance(value, bool):
            return []
        return [] if isinstance(value, tp) else wrong(tp.__name__)
    return []


# Every config dataclass a compiled artifact carries.
_SECTION_TYPES = [
    AlfGatewayConfig,
    ApiGatewayConfig,
    BalfGatewayConfig,
    DcGatewayConfig,
    LogClientConfig,
    LogServerConfig,
    MarketDataGatewayConfig,
    RalfGatewayConfig,
    EngineConfig,
]


class TestDeclaredTypes:
    @pytest.mark.parametrize("section", _SECTION_TYPES, ids=lambda s: s.__name__)
    def test_a_default_instance_matches_its_own_annotations(self, section: Any) -> None:
        # A default that disagrees with its annotation would be compiled into
        # one type and read back as another.
        assert _mismatches(section, section(), section.__name__) == []

    def test_the_hand_built_fixture_matches_its_annotations(self) -> None:
        # Guards the fixtures in this file, which mypy is configured not to
        # check for argument types.
        assert _mismatches(CompiledConfig, _config(), "CompiledConfig") == []

    def test_a_decoded_artifact_matches_its_annotations(self) -> None:
        rebuilt = decode(encode(_config()))
        assert _mismatches(CompiledConfig, rebuilt, "CompiledConfig") == []

    def test_the_checker_catches_the_mistake_that_prompted_it(self) -> None:
        # A list where a tuple is declared — constructs happily, compares
        # unequal after a round trip.
        wrong = ApiGatewayConfig(
            credentials=[ApiCredential(api_key="k", gateway_id="GW01")]  # type: ignore[arg-type]
        )
        found = _mismatches(ApiGatewayConfig, wrong, "ApiGatewayConfig")

        assert found == ["ApiGatewayConfig.credentials: declared tuple, got list"]

    def test_the_checker_does_not_accept_a_bool_for_an_int(self) -> None:
        found = _mismatches(MarketDataGatewayConfig, MarketDataGatewayConfig(port=True), "md")  # type: ignore[arg-type]
        assert found == ["md.port: declared int, got bool"]
