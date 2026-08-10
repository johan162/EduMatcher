"""Phase 6.1e: ``system`` part one — fifteen topics, five maps, one collision.

What this file pins, in order of how much it cost to learn:

* **The class-name collision.** ``types: SessionSchedule`` beside a
  ``session_schedule`` message emitted ``class SessionSchedule`` twice into one
  module, and the second silently shadowed the first. ``lint``, ``pm-msgen
  check`` and black all passed on that spec. The loader rejects it now; the
  guard itself is tested in ``test_msgen_nested.py``, and what is pinned *here*
  is the property it protects — no generated module defines a class twice.
* **The five map conversions**, each judged separately (design section 28.2).
* **One spelling of tick scale.** ``tick_decimals``, the integer the engine
  holds, rather than ``tick_size`` — which two consumers reconstructed with
  ``round(-log10(x))`` and a third read under a name no producer sent.
* **The inbound clamps.** Five wire reads that fed spec-bounded reply fields
  ahead of the reply: section 22.3's silent non-answer, five times.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import system as G
from edumatcher.models.generated._runtime import MessageValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED = REPO_ROOT / "src" / "edumatcher" / "models" / "generated"


def _payload(frames: list[bytes]) -> dict[str, Any]:
    from edumatcher.models.message import decode

    _topic, payload = decode(frames)
    return dict(payload)


def _reference(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "gateway_id": "GW1",
        "symbols": [{"symbol": "AAPL", "tick_decimals": 2}],
        "risk": {"default_level": "L1", "levels": [{"name": "L1"}]},
        "indexes": [],
        "schedule": {"sessions_enabled": True, "country": "SE", "schedule": None},
        "config_version": "abc123",
    }
    base.update(over)
    return base


class TestNoGeneratedModuleDefinesAClassTwice:
    """The defect that motivated the loader guard, pinned as a property.

    The guard in ``spec.py`` fails the *spec*; this fails the *output*, which
    is what a future emitter change could break without touching the loader.
    Asserting it over every module rather than over ``system`` alone is the
    point: a scan that only looks where the bug already was is a scan that
    finds it once.
    """

    def test_every_generated_module_has_unique_class_names(self) -> None:
        checked = 0
        for path in sorted(GENERATED.glob("*.py")):
            if path.name.startswith("_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
            assert len(names) == len(set(names)), f"{path.name} defines a class twice"
            checked += 1
        # Section 23.1: a scan that matched nothing passes for the wrong reason.
        assert checked >= 14, f"expected every family module, scanned {checked}"


class TestSymbolsIsOneCollection:
    """`symbol_meta` was the same instruments written a second time."""

    def test_each_entry_carries_its_own_symbol(self) -> None:
        payload = _payload(
            M.make_symbols_msg(
                "GW1",
                [
                    {"symbol": "AAPL", "tick_decimals": 2, "mm_min_qty": 100},
                    {"symbol": "MSFT", "tick_decimals": 4},
                ],
            )
        )
        assert payload == {
            "symbols": [
                {"symbol": "AAPL", "tick_decimals": 2, "mm_min_qty": 100},
                {"symbol": "MSFT", "tick_decimals": 4},
            ]
        }

    def test_symbol_meta_is_gone(self) -> None:
        payload = _payload(
            M.make_symbols_msg("GW1", [{"symbol": "AAPL", "tick_decimals": 2}])
        )
        assert "symbol_meta" not in payload

    def test_the_optional_market_maker_fields_omit_rather_than_null(self) -> None:
        """Regime 3: "no obligation configured" is not "obligation disabled"."""
        entry = _payload(
            M.make_symbols_msg("GW1", [{"symbol": "AAPL", "tick_decimals": 2}])
        )["symbols"][0]
        assert entry == {"symbol": "AAPL", "tick_decimals": 2}


class TestTickScaleHasOneSpelling:
    def test_symbols_carries_the_exponent_not_the_size(self) -> None:
        entry = _payload(
            M.make_symbols_msg("GW1", [{"symbol": "AAPL", "tick_decimals": 2}])
        )["symbols"][0]
        assert entry["tick_decimals"] == 2
        assert "tick_size" not in entry

    def test_reference_agrees_with_symbols(self) -> None:
        """Two messages, one name for the same number.

        They disagreed before: `system.symbols` said `tick_size`, `book` and
        `system.eod` said `tick_decimals`, and `reference.symbols` said
        `tick_size` again.
        """
        entry = _payload(M.make_reference_msg(**_reference()))["symbols"][0]
        assert entry["tick_decimals"] == 2
        assert "tick_size" not in entry


class TestTheReferenceBundleHasOneShape:
    def test_an_unconfigured_engine_still_answers_completely(self) -> None:
        """It used to reply `{"config_version": None}` and nothing else.

        Every slicing endpoint compensated with `.get(key, {})`, so the second
        shape was invisible until one of them stopped doing it.
        """
        payload = _payload(
            M.make_reference_msg(
                "GW1",
                symbols=[],
                risk={"default_level": None, "levels": []},
                indexes=[],
                schedule={
                    "sessions_enabled": False,
                    "country": None,
                    "schedule": None,
                },
                config_version=None,
            )
        )
        assert payload == {
            "symbols": [],
            "risk": {"levels": []},
            "indexes": [],
            "schedule": {"sessions_enabled": False, "schedule": None},
            "config_version": None,
        }

    def test_config_version_is_present_even_when_null(self) -> None:
        """Regime 2, not 3: every consumer compares it, so it must be there."""
        payload = _payload(M.make_reference_msg(**_reference(config_version=None)))
        assert "config_version" in payload
        assert payload["config_version"] is None

    def test_symbols_is_a_list_of_records_not_a_map(self) -> None:
        payload = _payload(M.make_reference_msg(**_reference()))
        assert isinstance(payload["symbols"], list)

    def test_risk_levels_is_a_list_of_records_not_a_map(self) -> None:
        payload = _payload(M.make_reference_msg(**_reference()))
        assert payload["risk"]["levels"] == [{"name": "L1"}]

    def test_a_level_without_collar_omits_it_rather_than_sending_an_empty_box(
        self,
    ) -> None:
        payload = _payload(M.make_reference_msg(**_reference()))
        assert "collar" not in payload["risk"]["levels"][0]


class TestTheScheduleRecordIsDeclaredOnce:
    """`session_schedule.schedule` and `reference.schedule` are one shape.

    Which is why the two topics could not be split across 6.1e and 6.1f:
    describing the record in one phase and re-describing it in the next is the
    drift section 1 exists to stop.
    """

    TIMES = {
        "pre_open": "08:00",
        "opening_auction_start": "09:00",
        "continuous_start": "09:05",
        "closing_auction_start": "17:20",
        "closing_auction_end": "17:30",
    }

    def test_both_messages_carry_the_same_record(self) -> None:
        standalone = _payload(M.make_session_schedule_msg("GW1", True, self.TIMES))
        bundled = _payload(
            M.make_reference_msg(
                **_reference(
                    schedule={
                        "sessions_enabled": True,
                        "country": "SE",
                        "schedule": self.TIMES,
                    }
                )
            )
        )
        assert standalone["schedule"] == bundled["schedule"]["schedule"]

    def test_no_schedule_is_null_rather_than_an_empty_object(self) -> None:
        """One spelling of the absence. `schedule or {}` was the other."""
        payload = _payload(M.make_session_schedule_msg("GW1", False, None))
        assert payload == {"sessions_enabled": False, "schedule": None}


class TestTheTopicParameterProjection:
    """Section 26.4, verified per message rather than assumed.

    ``include: all`` means "every field except the topic parameters". Two of
    these five repeat the id in the body and three do not, and `pm-msgen check`
    passes either way — which is exactly how 6.1c nearly shipped five messages
    with `symbol` missing.
    """

    @pytest.mark.parametrize(
        "frames",
        [
            M.make_gateway_auth_msg("GW1", True),
            M.make_gateway_bye_msg("GW1", "done"),
        ],
    )
    def test_the_two_that_repeat_the_id_keep_it(self, frames: list[bytes]) -> None:
        assert _payload(frames)["gateway_id"] == "GW1"

    @pytest.mark.parametrize(
        "frames",
        [
            M.make_symbols_msg("GW1", []),
            M.make_session_status_msg("GW1", "CONTINUOUS", True),
            M.make_session_schedule_msg("GW1", False, None),
            M.make_reference_reload_ack_msg("GW1", "c1", True, config_version="v"),
        ],
    )
    def test_the_rest_drop_it(self, frames: list[bytes]) -> None:
        assert "gateway_id" not in _payload(frames)


class TestTheReloadAckVerdict:
    def test_acceptance_carries_the_version_and_no_reason(self) -> None:
        payload = _payload(
            M.make_reference_reload_ack_msg("GW1", "c1", True, config_version="v9")
        )
        assert payload == {"command_id": "c1", "accepted": True, "config_version": "v9"}

    def test_rejection_carries_the_reason_and_no_version(self) -> None:
        payload = _payload(
            M.make_reference_reload_ack_msg("GW1", "c1", False, reason="no config")
        )
        assert payload == {
            "command_id": "c1",
            "accepted": False,
            "reason": "no config",
        }


class TestEodTrimsTheSnapshotAndSaysSo:
    def test_a_full_snapshot_is_trimmed_to_the_five_declared_keys(self) -> None:
        """`SystemEodPayload.from_dict` did this without writing it down."""
        payload = _payload(
            M.make_eod_msg(
                [
                    {
                        "symbol": "AAPL",
                        "tick_decimals": 2,
                        "bids": [{"price": 149.0, "qty": 10, "count": 1}],
                        "asks": [{"price": 151.0, "qty": 10, "count": 1}],
                        "last_price": 150.0,
                        "last_qty": 5,
                        "last_buy_price": 149.5,
                        "recent_trades": [{"id": "T1"}],
                    }
                ]
            )
        )
        book = payload["books"][0]
        assert set(book) == {"symbol", "tick_decimals", "bids", "asks", "last_price"}

    def test_an_instrument_that_never_traded_omits_last_price(self) -> None:
        payload = _payload(
            M.make_eod_msg(
                [{"symbol": "AAPL", "tick_decimals": 2, "bids": [], "asks": []}]
            )
        )
        assert "last_price" not in payload["books"][0]


class TestTheAuditBounds:
    """Section 22.3's silent non-answer, checked by probe rather than reasoning.

    Every one of these validates *before* the reply leaves, so an unbounded
    value would raise inside the builder and the caller would wait for a
    timeout with no answer at all.
    """

    def test_an_over_long_gateway_id_raises_rather_than_shipping(self) -> None:
        with pytest.raises(MessageValidationError):
            M.make_symbols_msg("G" * 33, [])

    def test_an_over_long_command_id_raises(self) -> None:
        with pytest.raises(MessageValidationError):
            M.make_reference_reload_msg("GW1", "c" * 65)

    def test_a_level_name_is_bounded_through_two_levels_of_nesting(self) -> None:
        """The ladder `circuit_breaker.halt.level` quotes onward, bounded at 32.

        6.1c bounded the event; this bounds the configuration it comes from,
        which is where a deployment can introduce a long one.
        """
        with pytest.raises(MessageValidationError):
            M.make_reference_msg(
                **_reference(
                    symbols=[
                        {
                            "symbol": "AAPL",
                            "tick_decimals": 2,
                            "circuit_breaker": {
                                "reference_window_ns": 1,
                                "levels": [
                                    {
                                        "name": "X" * 33,
                                        "price_shift_pct": 1.0,
                                        "halt_duration_ns": 1,
                                    }
                                ],
                            },
                        }
                    ]
                )
            )


class TestTheGeneratedRecordsReplaceTheHandWrittenOnes:
    """`feed_schema`'s three ``system`` dataclasses are gone, not duplicated."""

    def test_feed_schema_no_longer_declares_them(self) -> None:
        from edumatcher.models import feed_schema

        for gone in ("SystemEodPayload", "GatewayAuthPayload", "GatewayByePayload"):
            assert not hasattr(feed_schema, gone)

    def test_the_generated_records_round_trip_what_they_replaced(self) -> None:
        auth = G.GatewayAuth.from_dict(_payload(M.make_gateway_auth_msg("GW1", True)))
        assert (auth.gateway_id, auth.accepted, auth.reason) == ("GW1", True, "")
        bye = G.GatewayBye.from_dict(_payload(M.make_gateway_bye_msg("GW1", "done")))
        assert (bye.gateway_id, bye.reason) == ("GW1", "done")
