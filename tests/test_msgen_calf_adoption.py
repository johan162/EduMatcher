"""Phase 4a adoption: the CALF field map now comes from the spec.

``md_gateway/normaliser.py::normalise_trade`` used to build ``{PX, QTY, SIDE}``
as a dict literal. It now calls the generated projection, so adding a field to
the public trade feed is a spec edit rather than three coordinated ones that
still never reach the C clients.

These tests pin what that changed and — more importantly — what it did not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.md_gateway.normaliser import EngineNormaliser
from edumatcher.models.generated.trade import (
    TradeExecuted,
    project_trade_executed_calf,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_SAMPLE: dict[str, Any] = {
    "id": "42",
    "symbol": "ACME",
    "buy_order_id": "b-1",
    "sell_order_id": "s-1",
    "buy_gateway_id": "GW1",
    "sell_gateway_id": "GW2",
    "price": 101.5,
    "quantity": 300,
    "aggressor_side": "BUY",
    "timestamp": 1_700_000_000.0,
    "tick_decimals": 2,
}


class TestProjectionMatchesTheHandWrittenNormaliser:
    """Wire compatibility, the same bar every other family adoption met."""

    @pytest.mark.parametrize(
        "override",
        [
            {},
            {"aggressor_side": "SELL"},
            {"aggressor_side": "AUCTION"},
            {"price": 0.05},
            {"price": 150.0},
            {"price": 12345.6789},
            {"quantity": 1},
            {"quantity": 1_000_000},
        ],
    )
    def test_same_field_map(self, override: dict[str, Any]) -> None:
        payload = {**_SAMPLE, **override}
        generated = project_trade_executed_calf(payload)
        assert generated == {
            "PX": str(payload["price"]),
            "QTY": str(int(payload["quantity"])),
            "SIDE": str(payload["aggressor_side"]).upper(),
        }

    def test_normalise_trade_returns_the_projection(self) -> None:
        symbol, fields = EngineNormaliser().normalise_trade(_SAMPLE)
        assert symbol == "ACME"
        assert fields == project_trade_executed_calf(_SAMPLE)

    def test_the_projection_carries_exactly_three_keys(self) -> None:
        """CH/SYM/SEQ/TS belong to the envelope, not the payload (section 4.6)."""
        fields = project_trade_executed_calf(_SAMPLE)
        assert sorted(fields) == ["PX", "QTY", "SIDE"]

    def test_enum_rendering_is_idempotent(self) -> None:
        """``.upper()`` reproduces the old literal without changing valid data."""
        for side in ("BUY", "SELL", "AUCTION"):
            payload = {**_SAMPLE, "aggressor_side": side}
            projected = project_trade_executed_calf(payload)
            assert projected["SIDE"] == side


class TestStatefulBehaviourIsUnchanged:
    """Section 4.6 N1: the generator owns the projection, not the state."""

    def test_top_of_book_cache_is_still_updated(self) -> None:
        normaliser = EngineNormaliser()
        normaliser.normalise_trade(_SAMPLE)
        cached = normaliser.top_cache["ACME"]
        assert cached.last == "101.5"
        assert cached.last_sz == "300"

    def test_top_sent_is_still_left_alone(self) -> None:
        """Marking it sent here is what used to suppress the next LAST field."""
        normaliser = EngineNormaliser()
        before = dict(getattr(normaliser, "top_sent", {}))
        normaliser.normalise_trade(_SAMPLE)
        assert dict(getattr(normaliser, "top_sent", {})) == before

    def test_symbol_is_still_extracted_by_the_normaliser(self) -> None:
        """SYM is gateway-injected, so it is not in the projection."""
        symbol, fields = EngineNormaliser().normalise_trade(
            {**_SAMPLE, "symbol": "acme"}
        )
        assert symbol == "ACME"
        assert "SYM" not in fields


class TestTheProjectionNeedsOnlyWhatItProjects:
    """The bug the full suite caught: a projection must depend on a subset.

    The first version of this adoption built a whole ``TradeExecuted`` before
    projecting, which meant a CALF gateway had to hold ``id``,
    ``buy_order_id`` and every other bus field in order to emit three. Eight
    existing tests failed with ``KeyError: 'id'`` and they were right to: they
    pass exactly what the CALF feed carries.
    """

    def test_a_payload_of_only_the_projected_fields_works(self) -> None:
        minimal = {
            "symbol": "AAPL",
            "price": 151.5,
            "quantity": 25,
            "aggressor_side": "BUY",
        }
        symbol, fields = EngineNormaliser().normalise_trade(minimal)
        assert symbol == "AAPL"
        assert fields == {"PX": "151.5", "QTY": "25", "SIDE": "BUY"}

    @pytest.mark.parametrize(
        "absent",
        ["id", "buy_order_id", "sell_order_id", "buy_gateway_id", "timestamp"],
    )
    def test_fields_calf_drops_are_never_read(self, absent: str) -> None:
        payload = {k: v for k, v in _SAMPLE.items() if k != absent}
        assert project_trade_executed_calf(payload) == project_trade_executed_calf(
            _SAMPLE
        )

    def test_projecting_a_payload_equals_projecting_a_typed_message(self) -> None:
        """The two entry points must not drift apart."""
        message = TradeExecuted.from_dict(_SAMPLE)
        assert project_trade_executed_calf(_SAMPLE) == project_trade_executed_calf(
            message.to_dict()
        )


class TestMalformedPayloads:
    """A deliberate change of failure mode, documented in normalise_trade."""

    @pytest.mark.parametrize("missing", ["price", "quantity"])
    def test_a_missing_required_field_now_raises(self, missing: str) -> None:
        """It used to publish a print of zero shares at zero price.

        The caller (``_poll_engine_events``) wraps every handler in
        ``except Exception: log.warning(...)``, so this surfaces as a dropped
        message with a warning rather than a fabricated trade on a live feed.
        """
        payload = {k: v for k, v in _SAMPLE.items() if k != missing}
        with pytest.raises(KeyError):
            EngineNormaliser().normalise_trade(payload)

    def test_the_gateway_handler_still_guards_every_topic(self) -> None:
        """The above is only acceptable because the caller catches it."""
        source = (
            REPO_ROOT / "src" / "edumatcher" / "md_gateway" / "gateway.py"
        ).read_text(encoding="utf-8")
        assert "except Exception:" in source
        assert "md_gateway handler error on engine topic=%s" in source

    def test_a_missing_aggressor_side_still_projects(self) -> None:
        """parse_default keeps the archive readable (section B.7.1)."""
        payload = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
        _symbol, fields = EngineNormaliser().normalise_trade(payload)
        assert fields["SIDE"] == ""


class TestTheCExampleUsesTheGeneratedBinding:
    def test_calf_subscriber_parses_trades_with_the_generated_struct(self) -> None:
        source = (
            REPO_ROOT / "docs" / "examples" / "calf" / "calf_subscriber.c"
        ).read_text(encoding="utf-8")
        assert "edu_trade_executed_calf_parse" in source
        assert "edu_trade_executed_calf_validate" in source
        assert 'calf_get_field(msg, "QTY")' not in source
        assert 'calf_get_field(msg, "SIDE")' not in source

    def test_it_still_prints_the_price_from_the_wire(self) -> None:
        """This client deliberately never reformats a decimal.

        The generated struct holds ``price`` as a double, and using it would
        mean choosing a decimal count — the per-symbol REF= problem the file's
        header comment explains it avoids. A typed binding removes guesswork
        about names and types, not about an instrument's tick scale.
        """
        source = (
            REPO_ROOT / "docs" / "examples" / "calf" / "calf_subscriber.c"
        ).read_text(encoding="utf-8")
        assert 'calf_get_field(msg, "PX")' in source
        assert "%.*f" not in source

    def test_the_example_build_links_the_generated_sources(self) -> None:
        makefile = (REPO_ROOT / "docs" / "examples" / "calf" / "Makefile").read_text(
            encoding="utf-8"
        )
        assert "edumatcher_trade.c" in makefile
        assert "edumatcher_msg.c" in makefile
