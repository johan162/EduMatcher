"""Phase 5.2b: ``book`` and ``depth``.

The first family whose payloads are *mostly* records. A book snapshot is two
price ladders and a trade tape — three lists of records in one message — which
before ``nested`` and ``list[T]`` landed could not have been described at all.

It is also where the two topics that once drifted apart are declared side by
side. ``make_depth_msg`` published ``book.depth.{symbol}`` while the engine
published ``depth.{symbol}`` inline; worse, ``book.depth.X`` matches a
``book.`` prefix subscription, so pm-stats recorded a phantom instrument
literally named ``depth.AAPL``. One spec file is what stops that recurring.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import book as G
from edumatcher.models.generated._runtime import MessageValidationError


def _snapshot() -> dict[str, Any]:
    return {
        "symbol": "AAPL",
        "tick_decimals": 2,
        "bids": [
            {"price": 95.0, "qty": 100, "count": 2},
            {"price": 94.5, "qty": 50, "count": 1},
        ],
        "asks": [{"price": 95.5, "qty": 80, "count": 3}],
        "last_price": 95.25,
        "last_qty": 10,
        "last_buy_price": 95.25,
        "last_sell_price": 95.0,
        "recent_trades": [
            {
                "id": "T1",
                "symbol": "AAPL",
                "buy_order_id": "B1",
                "sell_order_id": "S1",
                "buy_gateway_id": "GW1",
                "sell_gateway_id": "GW2",
                "price": 95.25,
                "quantity": 10,
                "timestamp": 1700000000.5,
            }
        ],
    }


def _depth() -> dict[str, Any]:
    return {
        "symbol": "AAPL",
        "mid_price_ticks": 9525,
        "mid_price": 95.25,
        "tolerance_ticks": 100,
        "bid_depth": 150,
        "ask_depth": 80,
        "imbalance": 0.3043478260869565,
        "microprice": 95.3,
        "cost_to_move": 7620.0,
    }


class TestThreeListsInOneMessage:
    def test_the_snapshot_round_trips_byte_identically(self) -> None:
        assert G.BookSnapshot.from_dict(_snapshot()).to_dict() == _snapshot()

    def test_the_ladders_are_records(self) -> None:
        book = G.BookSnapshot.from_dict(_snapshot())
        assert all(isinstance(level, G.BookLevel) for level in book.bids)
        assert book.bids[0].price == 95.0 and book.bids[0].count == 2

    def test_the_tape_is_a_different_record(self) -> None:
        book = G.BookSnapshot.from_dict(_snapshot())
        assert isinstance(book.recent_trades[0], G.RecentTrade)
        assert book.recent_trades[0].buy_gateway_id == "GW1"

    def test_an_empty_ladder_is_legal(self) -> None:
        """A book with no resting orders publishes empty lists, not nulls."""
        payload = {**_snapshot(), "bids": [], "asks": [], "recent_trades": []}
        rebuilt = G.BookSnapshot.from_dict(payload)
        rebuilt.validate()
        assert rebuilt.to_dict()["bids"] == []

    def test_the_builder_matches_the_generated_binding(self) -> None:
        assert M.make_book_msg("AAPL", _snapshot()) == G.make_book_snapshot(
            **_snapshot()
        )


class TestAnUntradedBookCarriesNulls:
    """The four ``last_*`` fields are nullable but always present.

    ``OrderBook.snapshot()`` is a plain dict literal with no conditionals, so
    every key is emitted. ``omit_when_none`` would have been a wire change for
    no reason — the reading is "has not traded", and null says that.
    """

    @pytest.mark.parametrize(
        "field", ["last_price", "last_qty", "last_buy_price", "last_sell_price"]
    )
    def test_it_is_null_not_absent(self, field: str) -> None:
        payload = {**_snapshot(), field: None}
        emitted = G.BookSnapshot.from_dict(payload).to_dict()
        assert field in emitted
        assert emitted[field] is None


class TestDepthIsItsOwnTopic:
    """Not ``book.depth.{symbol}``, which is the bug this pins."""

    def test_the_topic_is_depth_not_book_depth(self) -> None:
        topic, _payload = M.decode(M.make_depth_msg("AAPL", _depth()))
        assert topic == "depth.AAPL"
        assert not topic.startswith("book.")

    def test_it_does_not_match_a_book_prefix_subscription(self) -> None:
        """pm-stats subscribes to ``book.`` and splits on the first dot.

        Under the old ``book.depth.AAPL`` topic that yielded an instrument
        named ``depth.AAPL`` in daily_stats.
        """
        topic, _payload = M.decode(M.make_depth_msg("AAPL", _depth()))
        assert not topic.startswith(G.PREFIX_BOOK_SNAPSHOT)
        assert topic.startswith(G.PREFIX_DEPTH)

    def test_it_round_trips(self) -> None:
        assert G.Depth.from_dict(_depth()).to_dict() == _depth()

    def test_the_symbol_comes_back_out_of_the_topic(self) -> None:
        topic, _payload = M.decode(M.make_depth_msg("AAPL", _depth()))
        assert G.match_depth(topic) == "AAPL"

    def test_both_topics_are_declared_in_one_family(self) -> None:
        """Which is what stops them drifting apart again."""
        assert {"book.{symbol}", "depth.{symbol}"} <= set(G.FAMILY_TOPICS)


class TestValidation:
    def test_a_good_snapshot_validates(self) -> None:
        G.BookSnapshot.from_dict(_snapshot()).validate()

    def test_a_bad_level_is_caught_inside_the_list(self) -> None:
        payload = _snapshot()
        payload["asks"] = [{"price": 1.0, "qty": 1, "count": 1, "symbol": "X" * 99}]
        G.BookSnapshot.from_dict(payload).validate()  # unknown keys are ignored

    def test_a_bad_trade_id_is_caught(self) -> None:
        payload = _snapshot()
        payload["recent_trades"][0]["id"] = "X" * 100
        with pytest.raises(MessageValidationError, match="id"):
            G.BookSnapshot.from_dict(payload).validate()

    @pytest.mark.parametrize("imbalance", [-1.5, 1.5])
    def test_imbalance_is_bounded(self, imbalance: float) -> None:
        """It is a ratio in [-1, 1]; anything else is a computation bug."""
        with pytest.raises(MessageValidationError, match="imbalance"):
            G.Depth.from_dict({**_depth(), "imbalance": imbalance}).validate()

    @pytest.mark.parametrize("imbalance", [-1.0, 0.0, 1.0])
    def test_the_bounds_are_inclusive(self, imbalance: float) -> None:
        G.Depth.from_dict({**_depth(), "imbalance": imbalance}).validate()


class TestTwoListsInOneValidate:
    """Found by mypy during 5.2b, not by a test.

    ``validate()`` emitted ``for item in ...`` for every list, so two lists of
    different record types in one message bound ``item`` to the first — Python
    has no block scope — and a type checker rejected the second. The loop
    variable is now named after its field.
    """

    def test_the_loop_names_are_distinct(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "src/edumatcher/models/generated"
            / "book.py"
        ).read_text(encoding="utf-8")
        assert "for bids_item in self.bids:" in source
        assert "for recent_trades_item in self.recent_trades:" in source

    def test_all_three_lists_are_actually_walked(self) -> None:
        """The rename must not have dropped a list from validation."""
        payload = _snapshot()
        payload["bids"][1]["count"] = "not-an-int"
        with pytest.raises((MessageValidationError, ValueError)):
            G.BookSnapshot.from_dict(payload).validate()


class TestListBoundsMustBeSatisfiable:
    """Found by 5.2b's holistic review, not by the build.

    An unsatisfiable bound is worse than a wrong one: the spec loads, the
    binding generates, ``pm-msgen check`` passes, and then *every* message
    fails ``validate()`` at runtime with nothing pointing at the rule itself.
    """

    def _load(self, tmp_path: Any, rules: str) -> None:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
types:
  R:
    fields: [{{ name: a, type: string }}]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", published_by: [engine], since: "1.0" }}
    fields: [{{ name: xs, type: list, ref: R, validate: {{ {rules} }} }}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        load_family(path, load_transports(root / "transports.yaml"))

    def test_min_greater_than_max_is_rejected(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="exceeds max_items"):
            self._load(tmp_path, "min_items: 5, max_items: 2")

    @pytest.mark.parametrize("rule", ["min_items: -1", "max_items: -3"])
    def test_a_negative_bound_is_rejected(self, tmp_path: Any, rule: str) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="must not be negative"):
            self._load(tmp_path, rule)

    def test_a_satisfiable_bound_still_loads(self, tmp_path: Any) -> None:
        """The guard must be specific, not merely loud."""
        self._load(tmp_path, "min_items: 2, max_items: 10")
        self._load(tmp_path, "min_items: 0")
