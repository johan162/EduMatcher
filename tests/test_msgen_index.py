"""Phase 5.2e: the ``index`` family, specified but not yet adopted.

Three things this family was the first to need, and one it deliberately did
not get:

* **A third paired-presence group.** ``make_index_update_msg`` guarded
  ``day_open``/``day_high``/``day_low`` with a single ``if day_open is not
  None``. Design section 16.2 settled that shape for ``session``: an
  ``a_b``-prefixed group sharing one guard is a record that was flattened for
  want of one. ``DaySummary`` makes the half-set state unrepresentable.
* **A list that omits when empty.** ``HistoryRecord`` is a union of five
  archived shapes and only two carry a list, so a always-emitted list would
  have added ``"constituents": []`` and ``"symbols": []`` to four record types
  that have neither — a change to already-written JSONL. See
  :class:`TestOmitWhenEmptyReachesLists` for why the strings-only restriction
  did not survive being asked about.
* **A scalar list on a flat message.** ``index.history_request.types`` is the
  first, and it crashed the emitter — see
  :class:`TestTheHotPathBuilderHandlesScalarLists`.
* **No variant type.** ``index.corp_action``'s parameters are action-specific
  and stay flat; design section 20.3 records why one family is not enough to
  build a discriminated union for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.models.generated import index as G
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.msgen.spec import SpecError, load_family, load_transports

SPEC_ROOT = Path(__file__).resolve().parents[1] / "spec"


def _update(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "index_id": "OMX30",
        "level": 1234.5,
        "aggregate_cap": 9_000_000.0,
        "divisor": 7.25,
        "session_state": "OPEN",
        "timestamp": 1700000000.0,
    }
    base.update(over)
    return base


class TestTheGuardedTripleBecameARecord:
    """``day_open``/``day_high``/``day_low`` under one guard was a record."""

    def test_a_session_with_no_level_yet_omits_the_key(self) -> None:
        """``_reset_for_new_session`` clears all three; absent says so."""
        emitted = G.IndexUpdate.from_dict(_update()).to_dict()
        assert "day" not in emitted

    def test_a_day_summary_round_trips(self) -> None:
        payload = _update(day={"open": 1200.0, "high": 1250.0, "low": 1190.0})
        parsed = G.IndexUpdate.from_dict(payload)
        assert parsed.day is not None
        assert parsed.day.open == 1200.0
        assert parsed.to_dict() == payload

    def test_the_half_set_state_is_unrepresentable(self) -> None:
        """The point of the record, not merely a rule that rejects it.

        A flat triple can be built with two of three keys and is only caught
        afterwards. A record has no such shape: omitting ``high`` is a missing
        required field of ``DaySummary``, raised at read time.
        """
        payload = _update(day={"open": 1200.0, "low": 1190.0})
        with pytest.raises(KeyError):
            G.IndexUpdate.from_dict(payload)

    def test_it_is_the_third_instance_and_the_pattern_is_named(self) -> None:
        """After ``next_state``/``next_at`` and ``command_id``/``gateway_id``.

        The spec should say so, because the rule generalises: a group of
        ``a_b``-prefixed fields sharing one guard is a flattened record.
        """
        source = (SPEC_ROOT / "messages/index.yaml").read_text(encoding="utf-8")
        assert "section 16.2" in source


class TestTheArchiveRoundTripsUnchanged:
    """Five shapes, one record, and not one byte added to any of them."""

    _RECORDS: tuple[dict[str, Any], ...] = (
        {
            "type": "INIT",
            "timestamp": 1.0,
            "index_id": "OMX30",
            "base_value": 1000.0,
            "divisor": 2.0,
            "constituents": ["ACME", "BOLT"],
            "level": 1000.0,
        },
        {
            "type": "CORP_ACTION",
            "timestamp": 2.0,
            "index_id": "OMX30",
            "symbol": "ACME",
            "action": "SPLIT",
            "detail": "2:1",
            "old_divisor": 2.0,
            "new_divisor": 1.9,
            "level": 1001.0,
        },
        {
            "type": "ADD_CONSTITUENT",
            "timestamp": 3.0,
            "index_id": "OMX30",
            "level": 1002.0,
            "symbol": "COG",
            "shares_outstanding": 1000,
            "reference_price": 10.0,
            "old_divisor": 1.9,
            "new_divisor": 2.1,
        },
        {
            "type": "DELIST",
            "timestamp": 4.0,
            "index_id": "OMX30",
            "level": 1003.0,
            "symbol": "BOLT",
            "old_divisor": 2.1,
            "new_divisor": 2.0,
        },
        {
            "type": "REBALANCE",
            "timestamp": 5.0,
            "index_id": "OMX30",
            "symbols": ["ACME", "COG"],
            "old_divisor": 2.0,
            "new_divisor": 2.2,
            "level": 1004.0,
        },
    )

    @pytest.mark.parametrize("record", _RECORDS, ids=lambda r: str(r["type"]))
    def test_each_shape_survives_a_round_trip(self, record: dict[str, Any]) -> None:
        """Byte for byte: this is replayed from disk, not built fresh.

        A record written before the spec existed must read back and re-emit
        unchanged, or specifying the family would rewrite history.
        """
        assert G.HistoryRecord.from_dict(record).to_dict() == record

    def test_a_record_without_a_list_gains_no_empty_one(self) -> None:
        """The reason ``omit_when_empty`` had to reach lists.

        Only INIT carries ``constituents`` and only REBALANCE carries
        ``symbols``. An always-emitted list would have put ``[]`` on the other
        three.
        """
        emitted = G.HistoryRecord.from_dict(self._RECORDS[1]).to_dict()
        assert "constituents" not in emitted
        assert "symbols" not in emitted

    def test_a_legacy_add_record_still_round_trips(self) -> None:
        """5.2e added ``shares_outstanding`` to the ADD entry; the archive did not.

        The field is optional precisely so the records already on disk read
        back and re-emit unchanged. Making it required would have made the
        spec reject the very history it exists to describe.
        """
        legacy = {
            "type": "ADD_CONSTITUENT",
            "timestamp": 3.0,
            "index_id": "OMX30",
            "level": 1002.0,
            "symbol": "COG",
            "reference_price": 10.0,
            "old_divisor": 1.9,
            "new_divisor": 2.1,
        }
        parsed = G.HistoryRecord.from_dict(legacy)
        assert parsed.shares_outstanding is None
        assert parsed.to_dict() == legacy

    def test_the_whole_reply_round_trips(self) -> None:
        payload = {"index_id": "OMX30", "records": [dict(r) for r in self._RECORDS]}
        parsed = G.IndexHistory.from_dict(payload)
        assert isinstance(parsed.records[0], G.HistoryRecord)
        assert parsed.to_dict() == payload

    def test_no_warnings_means_no_key(self) -> None:
        """``if warnings:`` in the hand-written builder, said in the spec."""
        emitted = G.IndexHistory.from_dict(
            {"index_id": "OMX30", "records": []}
        ).to_dict()
        assert "warnings" not in emitted

    def test_warnings_survive_when_there_are_some(self) -> None:
        payload = {
            "index_id": "OMX30",
            "records": [],
            "warnings": ["ignored malformed history line"],
        }
        assert G.IndexHistory.from_dict(payload).to_dict() == payload

    def test_an_unknown_record_type_is_rejected(self) -> None:
        """``IndexHistory.query`` drops these with a warning, so none reach here."""
        bad = {**self._RECORDS[0], "type": "LEVEL_TICK"}
        with pytest.raises(MessageValidationError, match="type"):
            G.HistoryRecord.from_dict(bad).validate()


class TestOmitWhenEmptyReachesLists:
    """The restriction was narrower than its reason, for the fourth time.

    ``omit_when_empty`` was strings-only because falsy-omit would silently
    drop a legitimate zero on a number, and because ``""`` is not a declared
    value of an enum. Neither is true of a list: design section 18.3 already
    established that absent and empty are the same thing to a list on the read
    side (``p.get(key, [])``), so omitting on empty is exactly symmetric with
    the read.
    """

    def _load(self, tmp_path: Any, field: str) -> Any:
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", since: "1.0" }}
    fields:
      - {{ name: a, type: string, validate: {{ max_len: 8 }} }}
      - {field}
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        return load_family(path, load_transports(SPEC_ROOT / "transports.yaml"))

    def test_a_list_may_omit_when_empty(self, tmp_path: Any) -> None:
        family = self._load(
            tmp_path,
            "{ name: xs, type: list, item: string, required: false, "
            "omit_when_empty: true }",
        )
        assert family.messages[0].fields[1].omit_when_empty is True

    def test_a_number_still_may_not(self, tmp_path: Any) -> None:
        """On a number it would drop a legitimate zero — the original reason."""
        with pytest.raises(SpecError, match="strings and lists only"):
            self._load(
                tmp_path,
                "{ name: n, type: int, unit: dimensionless, required: false, "
                "omit_when_empty: true }",
            )

    def test_an_enum_still_may_not(self, tmp_path: Any) -> None:
        with pytest.raises(SpecError, match="strings and lists only"):
            self._load(
                tmp_path,
                "{ name: e, type: enum, values: [A, B], required: false, "
                "omit_when_empty: true }",
            )

    def test_min_items_and_omit_when_empty_contradict(self, tmp_path: Any) -> None:
        """A rule that can itself be invalid, which only the loader can say.

        A list that must carry an item can never be empty, so the omission
        could never fire and the field would silently always be present —
        design section 17.3's class of defect exactly.
        """
        with pytest.raises(SpecError, match="min_items"):
            self._load(
                tmp_path,
                "{ name: xs, type: list, item: string, required: false, "
                "omit_when_empty: true, validate: { min_items: 1 } }",
            )

    def test_min_items_zero_is_not_a_contradiction(self, tmp_path: Any) -> None:
        """Only a *positive* lower bound conflicts; ``0`` says nothing."""
        self._load(
            tmp_path,
            "{ name: xs, type: list, item: string, required: false, "
            "omit_when_empty: true, validate: { min_items: 0 } }",
        )

    def test_parse_default_on_a_list_is_rejected(self, tmp_path: Any) -> None:
        """Found by this phase's holistic review, not by the build.

        A list reads through ``p.get(key, [])`` before any of the
        ``parse_default`` machinery, so a declared one loaded, generated and
        was silently never substituted — the same objection section 18.1 made
        to scalar ``validate`` rules on a list. It slipped through because it
        was only ever checked on the ``ref:`` branch, which is section 18.3's
        regression shape a second time.
        """
        with pytest.raises(SpecError, match="does nothing on a list"):
            self._load(
                tmp_path,
                "{ name: xs, type: list, item: string, required: false, "
                'omit_when_empty: true, parse_default: ["SENTINEL"] }',
            )

    def test_a_list_may_still_not_be_nullable(self, tmp_path: Any) -> None:
        """The neighbouring rule is untouched: null is a second spelling."""
        with pytest.raises(SpecError, match="may not be nullable"):
            self._load(
                tmp_path,
                "{ name: xs, type: list, item: string, required: false, "
                "nullable: true, omit_when_none: true }",
            )


class TestTheHotPathBuilderHandlesScalarLists:
    """``index.history_request`` is the first message with a list of scalars.

    Design section 18.1 stated that a scalar list keeps its
    ``make_*_unchecked`` "since it embeds no record". It was true as a
    decision and false as code: no committed spec had ever put a scalar list
    on a *message* — ``log``'s three are inside ``LogFilter`` — so the builder
    reached ``_COERCE["list"]`` and raised ``KeyError`` at generation time. A
    documented behaviour with no spec exercising it is design section 15.5's
    "a restriction with no test is a comment", in the other direction.
    """

    def test_the_builder_exists(self) -> None:
        assert hasattr(G, "make_index_history_request_unchecked")

    def test_it_matches_the_validating_builder_byte_for_byte(self) -> None:
        kw: dict[str, Any] = {
            "gateway_id": "GW1",
            "index_id": "OMX30",
            "from_ts": 0.0,
            "to_ts": 1700000000.0,
            "types": ["INIT", "REBALANCE"],
        }
        assert G.make_index_history_request_unchecked(
            **kw
        ) == G.make_index_history_request(**kw)

    def test_it_coerces_elements_as_from_dict_does(self) -> None:
        """The promise is byte-identical frames *for any input*, not valid input."""
        kw: dict[str, Any] = {
            "gateway_id": "GW1",
            "index_id": "OMX30",
            "from_ts": 0.0,
            "to_ts": 1.0,
            "types": [1, 2],
        }
        assert G.make_index_history_request_unchecked(
            **kw
        ) == G.make_index_history_request(**kw)

    def test_a_message_carrying_a_record_gets_none(self) -> None:
        """Unchanged rule: a record has no dict-literal form."""
        assert not hasattr(G, "make_index_update_unchecked")
        assert not hasattr(G, "make_index_history_unchecked")
        assert not hasattr(G, "make_index_rebalance_unchecked")


class TestTheDefaultThatDroppedRebalance:
    """A drift the spec had to resolve rather than reproduce.

    ``make_index_history_request_msg`` defaulted ``types`` to ``["INIT",
    "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"]`` — four of the five
    structural types. The server's own default is ``sorted(
    STRUCTURAL_RECORD_TYPES)``, which includes ``REBALANCE``. Every caller
    taking the builder's default therefore silently never saw a rebalance.

    Omitting the key is what ``log.subscribe`` does with ``lease_sec`` for the
    same reason: the server applies its own default and cannot tell an omitted
    value from one that happens to equal it.
    """

    def test_types_is_absent_when_unset(self) -> None:
        emitted = G.IndexHistoryRequest.from_dict(
            {
                "gateway_id": "GW1",
                "index_id": "OMX30",
                "from_ts": 0.0,
                "to_ts": 1.0,
            }
        ).to_dict()
        assert "types" not in emitted

    def test_the_five_structural_types_agree_with_the_server(self) -> None:
        """The drift that made the builder's default wrong, pinned.

        ``IndexHistory.query`` filters against ``STRUCTURAL_RECORD_TYPES``, so
        a type the spec declares and the server drops — or the reverse — is a
        request nobody can satisfy.
        """
        from typing import get_args

        from edumatcher.index.history import STRUCTURAL_RECORD_TYPES

        assert set(get_args(G.HistoryRecordType)) == set(STRUCTURAL_RECORD_TYPES)


class TestTheCorpActionParametersStayFlat:
    """No variant type: the IDL describes the field set, not the discriminant."""

    def test_a_split_carries_only_its_own_parameters(self) -> None:
        payload = {
            "action": "SPLIT",
            "index_id": "OMX30",
            "symbol": "ACME",
            "gateway_id": "GW1",
            "ratio_numerator": 2,
            "ratio_denominator": 1,
        }
        parsed = G.IndexCorpAction.from_dict(payload)
        assert parsed.dividend_per_share is None
        assert parsed.to_dict() == payload

    def test_a_dividend_carries_only_its_own(self) -> None:
        payload = {
            "action": "CASH_DIVIDEND",
            "index_id": "OMX30",
            "symbol": "ACME",
            "gateway_id": "GW1",
            "dividend_per_share": 1.5,
        }
        assert G.IndexCorpAction.from_dict(payload).to_dict() == payload

    def test_the_spec_cannot_say_a_split_needs_both_ratio_fields(self) -> None:
        """The cost of having no variant type, stated as a test.

        This payload is nonsense — a split with a numerator and no denominator
        — and ``validate()`` accepts it, because the rule lives in
        ``_handle_corp_action`` and cannot be expressed here. Recorded so the
        limitation is a known one rather than an assumed absence.
        """
        G.IndexCorpAction.from_dict(
            {
                "action": "SPLIT",
                "index_id": "OMX30",
                "symbol": "ACME",
                "gateway_id": "GW1",
                "ratio_numerator": 2,
            }
        ).validate()

    def test_an_unsupported_action_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="action"):
            G.IndexCorpAction.from_dict(
                {
                    "action": "BAD",
                    "index_id": "OMX30",
                    "symbol": "ACME",
                    "gateway_id": "GW1",
                }
            ).validate()


class TestAdoptionDidNotMakeAMalformedRequestFatal:
    """The one regression 5.2f's adoption could have shipped.

    Every rejection path in pm-index quotes the identifier it could not
    resolve, and ``gateway_id`` / ``index_id`` arrive unbounded from the wire
    while ``reason`` is declared ``max_len: 512``. Before adoption an
    over-long id merely produced an oversized reason; after it, ``make_*``
    validates, so the same input raised MessageValidationError out of a
    handler with no exception guard and out of the run loop — taking pm-index
    down while answering a malformed request.

    Found by probing the adopted builders with inputs no test sends, not by
    the suite. The handlers clamp their identifiers now.
    """

    def test_an_over_long_reason_is_still_rejected_by_the_spec(self) -> None:
        """The bound is real, which is why the producer has to respect it."""
        with pytest.raises(MessageValidationError, match="max_len"):
            G.make_index_error(
                gateway_id="GW1",
                accepted=False,
                reason="X" * 600,
                timestamp=1700000000.0,
            )

    def test_the_handlers_clamp_what_they_echo_back(self) -> None:
        from edumatcher.index.main import _MAX_ID_LEN, _clamp_id

        assert _clamp_id("x" * 5000) == "X" * _MAX_ID_LEN
        assert _clamp_id("edu100") == "EDU100"

    def test_a_hostile_index_id_still_produces_a_valid_reply(self) -> None:
        from edumatcher.index.main import _clamp_id

        from edumatcher.models.message import make_index_error_msg

        frames = make_index_error_msg(
            _clamp_id("gw1"), f"Unknown index_id '{_clamp_id('X' * 5000)}'"
        )
        assert frames[0] == b"index.error.GW1"

    def test_every_rejection_path_reads_its_ids_through_the_clamp(self) -> None:
        """A grep, because the risk is a handler added later that forgets.

        The clamp only helps where it is actually called, and the failure mode
        if one is missed is a crash rather than a wrong value.
        """
        import inspect

        from edumatcher.index.main import IndexProcess

        for name in (
            "_handle_history_request",
            "_handle_corp_action",
            "_handle_constituent_change",
            "_handle_rebalance",
        ):
            source = inspect.getsource(getattr(IndexProcess, name))
            assert "_clamp_id(payload.get(" in source, name
            assert 'str(payload.get("gateway_id", "")).upper()' not in source, name


class TestTheTopicsAreAllDeclared:
    def test_the_family_declares_ten(self) -> None:
        assert len(G.FAMILY_TOPICS) == 10

    def test_the_addressed_replies_are_parameterised(self) -> None:
        assert G.topic_index_error("GW1") == "index.error.GW1"
        assert G.topic_index_history("GW1") == "index.history.GW1"
        assert G.match_index_error("index.error.GW1") == "GW1"
        assert G.match_index_error("index.error.GW1.extra") is None

    def test_an_addressed_reply_does_not_repeat_its_gateway_in_the_body(self) -> None:
        """The default projection rule, and what the builders already did."""
        emitted = G.IndexError.from_dict(
            {
                "gateway_id": "GW1",
                "accepted": False,
                "reason": "Unknown index_id 'X'",
                "timestamp": 1700000000.0,
            }
        ).to_dict()
        assert "gateway_id" not in emitted
        assert emitted["accepted"] is False
