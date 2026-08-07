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

    def test_external_transport_is_rejected_until_phase_4(
        self, tmp_path: Path, transports: dict[str, Any]
    ) -> None:
        fam = _minimal_family(transport=["engine_pub", "calf"])
        with pytest.raises(SpecError, match="external protocol"):
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
