"""Loader tests: the spec model, and its strictness.

The strictness is the point. A silently-ignored ``requird: true`` disables a
field with no error, which is the exact failure class the generator exists to
remove (design section B.18 rule 15).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.msgen.spec import (
    SpecError,
    load_all,
    load_family,
    load_transports,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"


def _write(tmp_path: Path, family: dict[str, Any], name: str = "sample") -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(family, sort_keys=False), encoding="utf-8")
    return path


def _minimal_family(**message_overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "name": "thing_happened",
        "topic": "thing.happened",
        "transport": ["engine_pub"],
        "doc": {"motivation": "Something happened."},
        "fields": [
            {"name": "who", "type": "string", "validate": {"max_len": 8}},
            {"name": "how_many", "type": "int", "unit": "shares"},
        ],
    }
    message.update(message_overrides)
    return {"family": "sample", "version": 1, "messages": [message]}


@pytest.fixture(scope="module")
def transports() -> dict[str, Any]:
    return load_transports(SPEC_ROOT / "transports.yaml")


class TestRealSpec:
    """The committed spec must load, since everything else depends on it."""

    def test_transports_registry_loads(self, transports: dict[str, Any]) -> None:
        assert "engine_pub" in transports
        engine_pub = transports["engine_pub"]
        assert engine_pub.pattern == "PUB"
        assert engine_pub.subscriber_pattern == "SUB"
        assert engine_pub.address_config_key == "ENGINE_PUB_ADDR"
        assert engine_pub.is_bus is True

    def test_ralf_is_not_a_bus_transport(self, transports: dict[str, Any]) -> None:
        assert transports["ralf"].pattern == "TCP"
        assert transports["ralf"].is_bus is False

    def test_trade_family_loads(self) -> None:
        _registry, families = load_all(SPEC_ROOT)
        assert [f.family for f in families] == ["trade"]
        (trade,) = families
        assert trade.version == 1
        (msg,) = trade.messages
        assert msg.name == "trade_executed"
        assert msg.topic == "trade.executed"
        assert msg.topic_params == ()

    def test_trade_field_order_matches_feed_schema(self) -> None:
        """The spec's declared order is authoritative and must match today's.

        ``to_dict()`` feeds orjson, which preserves insertion order, so a
        reordering here would change the published bytes.
        """
        from edumatcher.models.feed_schema import TradeExecutedPayload

        _registry, families = load_all(SPEC_ROOT)
        (msg,) = families[0].messages
        hand = TradeExecutedPayload(
            id="1",
            symbol="A",
            buy_order_id="b",
            sell_order_id="s",
            buy_gateway_id="g1",
            sell_gateway_id="g2",
            price=1.0,
            quantity=1,
            aggressor_side="BUY",
            timestamp=0.0,
        ).to_dict()
        assert [f.name for f in msg.fields] == list(hand)

    def test_aggressor_side_declares_a_parse_default(self) -> None:
        """Strict contract, lenient reader — design section B.7.1."""
        _registry, families = load_all(SPEC_ROOT)
        (msg,) = families[0].messages
        (field,) = [f for f in msg.fields if f.name == "aggressor_side"]
        assert field.required is True
        assert field.values == ("BUY", "SELL", "AUCTION")
        assert field.has_parse_default is True
        assert field.parse_default == ""
        assert field.parse_default not in field.values


def _with_calf(**encoding_overrides: Any) -> dict[str, Any]:
    """A family carrying a CALF text projection, for the Phase 4a rules."""
    calf: dict[str, Any] = {
        "msg_type": "THING",
        "include": ["how_many"],
        "keys": {"how_many": "QTY"},
        "gateway_injected": ["CH", "SYM"],
    }
    calf.update(encoding_overrides)
    return _minimal_family(
        transport=["engine_pub", "calf"],
        encoding={"engine_pub": {"include": "all"}, "calf": calf},
    )


class TestTextEncoding:
    """Phase 4a: the CALF/RALF projection block (design section B.13)."""

    def test_real_trade_spec_declares_a_calf_projection(self) -> None:
        _registry, families = load_all(SPEC_ROOT)
        (msg,) = families[0].messages
        calf = msg.text_encoding["calf"]
        assert calf.msg_type == "TRADE"
        assert calf.include == ("price", "quantity", "aggressor_side")
        assert calf.keys == {
            "price": ("PX",),
            "quantity": ("QTY",),
            "aggressor_side": ("SIDE",),
        }
        assert calf.gateway_injected == ("CH", "SYM", "SEQ", "TS")

    def test_the_calf_projection_is_a_strict_subset(self) -> None:
        """Design section 4.6: a projection is a subset, not a rename of all."""
        _registry, families = load_all(SPEC_ROOT)
        (msg,) = families[0].messages
        carried = set(msg.text_encoding["calf"].include)
        assert "id" not in carried
        assert "symbol" not in carried
        assert "tick_decimals" not in carried

    def test_loads_a_minimal_projection(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = load_family(_write(tmp_path, _with_calf()), transports)
        calf = fam.messages[0].text_encoding["calf"]
        assert calf.keys == {"how_many": ("QTY",)}

    def test_one_field_may_map_to_several_wire_keys(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        """RALF's ``id: [EXEC_ID, MATCH_ID]`` shape."""
        fam = _with_calf(keys={"how_many": ["QTY", "SHARES"]})
        loaded = load_family(_write(tmp_path, fam), transports)
        assert loaded.messages[0].text_encoding["calf"].keys == {
            "how_many": ("QTY", "SHARES")
        }

    def test_missing_encoding_block_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        """`keys` has no defensible default; nothing can infer a wire name."""
        fam = _minimal_family(transport=["engine_pub", "calf"])
        with pytest.raises(SpecError, match="requires an 'encoding.calf' block"):
            load_family(_write(tmp_path, fam), transports)

    def test_msg_type_is_required(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _with_calf()
        del fam["messages"][0]["encoding"]["calf"]["msg_type"]
        with pytest.raises(SpecError, match="'msg_type' is required"):
            load_family(_write(tmp_path, fam), transports)

    def test_lowercase_msg_type_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        with pytest.raises(SpecError, match="SCREAMING_SNAKE"):
            load_family(_write(tmp_path, _with_calf(msg_type="thing")), transports)

    def test_keys_must_cover_every_included_field(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _with_calf(include=["who", "how_many"], keys={"how_many": "QTY"})
        with pytest.raises(SpecError, match="no wire name for included field"):
            load_family(_write(tmp_path, fam), transports)

    def test_keys_may_not_name_an_excluded_field(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _with_calf(keys={"how_many": "QTY", "who": "WHO"})
        with pytest.raises(SpecError, match="that 'include' omits"):
            load_family(_write(tmp_path, fam), transports)

    def test_a_wire_key_may_not_collide_with_a_gateway_injected_key(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _with_calf(keys={"how_many": "SYM"})
        with pytest.raises(SpecError, match="collides with a gateway_injected"):
            load_family(_write(tmp_path, fam), transports)

    def test_two_fields_may_not_produce_the_same_wire_key(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _with_calf(
            include=["who", "how_many"], keys={"who": "QTY", "how_many": "QTY"}
        )
        with pytest.raises(SpecError, match="produced by both"):
            load_family(_write(tmp_path, fam), transports)

    def test_a_string_reaching_a_text_transport_needs_max_len(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        """B.18 rule 8: the C binding must size a fixed buffer for it."""
        fam = _with_calf(include=["who"], keys={"who": "WHO"})
        del fam["messages"][0]["fields"][0]["validate"]
        with pytest.raises(SpecError, match="needs validate.max_len"):
            load_family(_write(tmp_path, fam), transports)

    def test_unknown_encoding_key_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _with_calf()
        fam["messages"][0]["encoding"]["calf"]["gateway_injcted"] = ["TS"]
        with pytest.raises(SpecError, match="unknown key"):
            load_family(_write(tmp_path, fam), transports)

    def test_a_text_only_message_must_omit_its_topic(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        """B.6; text-only messages are Phase 4b."""
        fam = _with_calf()
        fam["messages"][0]["transport"] = ["calf"]
        del fam["messages"][0]["encoding"]["engine_pub"]
        with pytest.raises(SpecError, match="must omit 'topic'"):
            load_family(_write(tmp_path, fam), transports)


class TestStrictness:
    """Every one of these must raise, not be quietly accepted."""

    def test_unknown_field_key_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][0]["requird"] = True
        with pytest.raises(SpecError, match="unknown key"):
            load_family(_write(tmp_path, fam), transports)

    def test_unknown_key_suggests_the_intended_one(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][0]["requird"] = True
        with pytest.raises(SpecError, match="did you mean 'required'"):
            load_family(_write(tmp_path, fam), transports)

    def test_unknown_validate_key_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][1]["validate"] = {"gte": 0}
        with pytest.raises(SpecError, match="unknown key"):
            load_family(_write(tmp_path, fam), transports)

    def test_unknown_message_key_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(publisher="engine")
        with pytest.raises(SpecError, match="unknown key"):
            load_family(_write(tmp_path, fam), transports)

    def test_filename_must_match_family(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        with pytest.raises(SpecError, match="must equal the filename stem"):
            load_family(_write(tmp_path, _minimal_family(), name="wrong"), transports)

    def test_unknown_transport_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(transport=["engine_pubb"])
        with pytest.raises(SpecError, match="absent from"):
            load_family(_write(tmp_path, fam), transports)

    def test_binary_transport_is_rejected_until_phase_4b(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(transport=["engine_pub", "balf"])
        with pytest.raises(SpecError, match="binary protocol"):
            load_family(_write(tmp_path, fam), transports)

    def test_unknown_unit_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][1]["unit"] = "shares_per_second"
        with pytest.raises(SpecError, match="is not one of"):
            load_family(_write(tmp_path, fam), transports)

    def test_numeric_field_requires_a_unit(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        del fam["messages"][0]["fields"][1]["unit"]
        with pytest.raises(SpecError, match="requires a declared 'unit'"):
            load_family(_write(tmp_path, fam), transports)

    def test_enum_without_values_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"].append({"name": "state", "type": "enum"})
        with pytest.raises(SpecError, match="requires a non-empty 'values'"):
            load_family(_write(tmp_path, fam), transports)

    def test_message_requires_a_motivation(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(doc={})
        with pytest.raises(SpecError, match="doc.motivation is required"):
            load_family(_write(tmp_path, fam), transports)

    def test_topic_parameter_must_be_a_field(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(topic="thing.happened.{gateway_id}")
        with pytest.raises(SpecError, match="is not a field"):
            load_family(_write(tmp_path, fam), transports)

    def test_optional_field_requires_a_default(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][0]["required"] = False
        with pytest.raises(SpecError, match="must declare a 'default'"):
            load_family(_write(tmp_path, fam), transports)

    def test_duplicate_field_name_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"].append(
            {"name": "who", "type": "string", "validate": {"max_len": 4}}
        )
        with pytest.raises(SpecError, match="duplicate field name"):
            load_family(_write(tmp_path, fam), transports)

    def test_include_cannot_name_an_undeclared_field(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(
            encoding={"engine_pub": {"include": ["who", "how_many", "ghost"]}}
        )
        with pytest.raises(SpecError, match="undeclared field"):
            load_family(_write(tmp_path, fam), transports)

    def test_required_field_must_reach_the_bus_projection(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        """B.18 rule 5: the bus payload is the authoritative projection."""
        fam = _minimal_family(encoding={"engine_pub": {"include": ["who"]}})
        with pytest.raises(SpecError, match="absent from the bus projection"):
            load_family(_write(tmp_path, fam), transports)

    def test_sequence_frame_may_not_be_declared(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        """The bus stamps the sequence; declaring it here would double-stamp."""
        fam = _minimal_family(
            encoding={"engine_pub": {"frames": ["topic", "json_payload", "sequence"]}}
        )
        with pytest.raises(SpecError, match="SequencedPublisher"):
            load_family(_write(tmp_path, fam), transports)

    def test_encoding_for_an_undeclared_transport_is_rejected(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(encoding={"log_pub": {"include": "all"}})
        with pytest.raises(SpecError, match="not listed in this message's"):
            load_family(_write(tmp_path, fam), transports)

    def test_unsupported_type_names_the_supported_ones(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][0]["type"] = "list[nested]"
        with pytest.raises(SpecError, match="not yet generated"):
            load_family(_write(tmp_path, fam), transports)

    def test_deprecated_field_requires_a_doc(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family()
        fam["messages"][0]["fields"][0]["deprecated_since"] = "1.2"
        with pytest.raises(SpecError, match="requires a non-empty 'doc'"):
            load_family(_write(tmp_path, fam), transports)

    def test_literal_address_in_registry_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "transports.yaml"
        path.write_text(
            "transports:\n"
            "  thing:\n"
            "    pattern: PUB\n"
            "    address_config_key: tcp://127.0.0.1:5556\n",
            encoding="utf-8",
        )
        with pytest.raises(SpecError, match="looks like a literal"):
            load_transports(path)

    def test_duplicate_message_name_across_families_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """Generated C symbols are message-scoped and would collide."""
        (tmp_path / "messages").mkdir()
        (tmp_path / "transports.yaml").write_text(
            (SPEC_ROOT / "transports.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        for index, name in enumerate(("alpha", "beta")):
            fam = _minimal_family(topic=f"thing.happened{index}")
            fam["family"] = name
            _write(tmp_path / "messages", fam, name=name)
        with pytest.raises(SpecError, match="generated C symbols"):
            load_all(tmp_path)

    def test_duplicate_topic_across_families_is_rejected(self, tmp_path: Path) -> None:
        """B.18 rule 14: topics are unique across the whole tree."""
        (tmp_path / "messages").mkdir()
        (tmp_path / "transports.yaml").write_text(
            (SPEC_ROOT / "transports.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        for name in ("alpha", "beta"):
            fam = _minimal_family()
            fam["family"] = name
            _write(tmp_path / "messages", fam, name=name)
        with pytest.raises(SpecError, match="declared in both"):
            load_all(tmp_path)
