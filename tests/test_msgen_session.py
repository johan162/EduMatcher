"""Phase 5.2a: the ``session`` family, and two new presence ideas.

``session.state`` is the most widely consumed topic in the system — 22 literal
occurrences across 15 modules before this phase — so it is where the
literal-elimination payoff is largest and where a silent rename would have been
most expensive.

It is also the first family whose adoption is **not byte-identical**, and that
is deliberate. Two field pairs travelled together or not at all:

    if next_state and next_at:        # in two builders
    if command_id and gateway_id:

The IDL could have grown a ``co_present: [a, b]`` constraint. It grew nothing,
because those pairs are records that had been flattened into ``a_b`` names for
want of one. A nullable record says "both or neither" by construction — the
half-set state is unrepresentable rather than detected — and it names the
thing: ``next`` is the next transition, ``reply_to`` is a return address.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import session as G
from edumatcher.models.generated._runtime import MessageValidationError


class TestOmitWhenEmpty:
    """The fourth presence regime, and the one the codebase already used most.

    ``SessionStatePayload.to_dict`` dropped ``prev_state`` with ``if x:`` — on
    the empty string, not on null. 27 hand-written builders do the same, so
    this is the regime Phase 5.2+ will lean on hardest.
    """

    def test_an_empty_string_is_omitted(self) -> None:
        _topic, payload = M.decode(M.make_session_state_msg("OPEN"))
        assert "prev_state" not in payload

    def test_a_set_value_is_present(self) -> None:
        _topic, payload = M.decode(M.make_session_state_msg("OPEN", "PRE_OPEN"))
        assert payload["prev_state"] == "PRE_OPEN"

    def test_it_round_trips_through_from_dict(self) -> None:
        """Absent and "" are the same thing to this regime."""
        assert G.SessionState.from_dict({"state": "OPEN"}).prev_state == ""
        assert G.SessionState.from_dict({"state": "OPEN"}).to_dict() == {
            "state": "OPEN"
        }

    def test_it_is_a_different_regime_from_omit_when_none(self) -> None:
        """``prev_state`` is a plain ``str``, never ``None``."""
        spec = {f["name"]: f for f in G.describe_session_state()}
        assert spec["prev_state"]["type"] == "string"
        assert G.SessionState.from_dict({"state": "OPEN"}).prev_state is not None


class TestPairedPresenceIsARecord:
    """Both-or-neither by construction, not by assertion."""

    def test_a_scheduler_transition_carries_next(self) -> None:
        _topic, payload = M.decode(
            M.make_session_state_msg("OPEN", "PRE_OPEN", "CLOSED", "2026-01-01T16:30Z")
        )
        assert payload["next"] == {"state": "CLOSED", "at": "2026-01-01T16:30Z"}

    def test_a_manual_transition_omits_it_entirely(self) -> None:
        _topic, payload = M.decode(M.make_session_state_msg("OPEN", "PRE_OPEN"))
        assert "next" not in payload

    @pytest.mark.parametrize(
        "next_state, next_at",
        [("CLOSED", ""), ("", "2026-01-01T16:30Z")],
    )
    def test_half_a_pair_emits_nothing(self, next_state: str, next_at: str) -> None:
        """The old rule, preserved: a phase with no time cannot be counted down.

        Under the old flat shape this was an ``if a and b:`` in the builder that
        every future caller had to remember. Now the builder cannot construct a
        half-set record at all.
        """
        _topic, payload = M.decode(
            M.make_session_state_msg("OPEN", "PRE_OPEN", next_state, next_at)
        )
        assert "next" not in payload

    def test_the_record_is_one_object_not_two_keys(self) -> None:
        _topic, payload = M.decode(
            M.make_session_state_msg("OPEN", "", "CLOSED", "2026-01-01T16:30Z")
        )
        assert "next_state" not in payload
        assert "next_at" not in payload
        assert isinstance(payload["next"], dict)

    def test_reply_to_behaves_the_same_way(self) -> None:
        _topic, payload = M.decode(
            M.make_session_transition_msg("OPEN", command_id="C1", gateway_id="GW1")
        )
        assert payload["reply_to"] == {"command_id": "C1", "gateway_id": "GW1"}

    def test_the_scheduler_sends_no_reply_to(self) -> None:
        """pm-scheduler drives the timetable and has nobody to report back to."""
        _topic, payload = M.decode(M.make_session_transition_msg("OPEN"))
        assert "reply_to" not in payload


class TestTheEngineStillReadsIt:
    """The consumers that had to change, driven for real."""

    def test_a_transition_request_round_trips(self) -> None:
        frames = M.make_session_transition_msg(
            "CONTINUOUS",
            next_state="CLOSED",
            next_at="2026-01-01T16:30Z",
            command_id="C1",
            gateway_id="GW1",
        )
        parsed = G.parse_session_transition(frames)
        assert parsed.to_state == "CONTINUOUS"
        assert parsed.next is not None and parsed.next.at == "2026-01-01T16:30Z"
        assert parsed.reply_to is not None and parsed.reply_to.gateway_id == "GW1"

    def test_the_ack_is_addressed_and_byte_identical(self) -> None:
        assert M.make_session_transition_ack_msg(
            "GW1", "C1", True, to_state="OPEN"
        ) == G.make_session_transition_ack_unchecked(
            gateway_id="GW1",
            command_id="C1",
            accepted=True,
            to_state="OPEN",
            reason="",
        )

    def test_the_ack_topic_carries_the_gateway(self) -> None:
        topic, payload = M.decode(M.make_session_transition_ack_msg("GW1", "C1", False))
        assert topic == "session.transition_ack.GW1"
        assert G.match_session_transition_ack(topic) == "GW1"
        assert payload["accepted"] is False


class TestValidation:
    def test_a_good_state_validates(self) -> None:
        G.SessionState.from_dict({"state": "OPEN"}).validate()

    def test_the_record_is_validated_too(self) -> None:
        bad = {"state": "OPEN", "next": {"state": "X" * 40, "at": "t"}}
        with pytest.raises(MessageValidationError, match="state"):
            G.SessionState.from_dict(bad).validate()

    def test_an_absent_record_is_not_validated(self) -> None:
        """A nullable record's rules apply only when the record is there."""
        G.SessionState.from_dict({"state": "OPEN"}).validate()


class TestTheTopicConstantsReplacedTheLiterals:
    @pytest.mark.parametrize(
        "constant, literal",
        [
            (G.TOPIC_SESSION_STATE, "session.state"),
            (G.TOPIC_SESSION_TRANSITION, "session.transition"),
        ],
    )
    def test_the_constant_is_the_old_literal(self, constant: str, literal: str) -> None:
        assert constant == literal

    def test_the_subscribers_use_the_constant(self) -> None:
        """21 literals across 10 modules; the point is that they are gone."""
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "src"
        users = [
            path.relative_to(src)
            for path in src.rglob("*.py")
            if "TOPIC_SESSION_STATE" in path.read_text(encoding="utf-8")
            and "generated" not in path.parts
        ]
        assert len(users) >= 10, users


class TestTheHandWrittenPayloadClassIsGone:
    """``SessionStatePayload`` was the generated class, written by hand.

    Keeping both would have been two definitions of one wire shape, free to
    drift — the exact failure the generator exists to remove.
    """

    def test_it_is_no_longer_in_feed_schema(self) -> None:
        from edumatcher.models import feed_schema

        assert not hasattr(feed_schema, "SessionStatePayload")

    def test_clearing_imports_the_generated_class(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src/edumatcher/clearing/main.py"
        ).read_text(encoding="utf-8")
        assert "from edumatcher.models.generated.session import SessionState" in source
        assert "SessionStatePayload" not in source

    def test_it_reads_a_real_broadcast(self) -> None:
        _topic, payload = M.decode(M.make_session_state_msg("CONTINUOUS", "OPEN"))
        assert G.SessionState.from_dict(payload).state == "CONTINUOUS"


class TestSpecStrictness:
    """``omit_when_empty`` is narrow on purpose."""

    def _load(self, tmp_path: Any, field: str) -> None:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", published_by: [engine], since: "1.0" }}
    fields: [{field}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        load_family(path, load_transports(root / "transports.yaml"))

    def test_it_is_rejected_on_a_number(self, tmp_path: Any) -> None:
        """On an int it would silently drop a legitimate zero.

        The reason is unchanged; the boundary moved in 5.2e. The regime was
        strings-only, and ``index``'s HistoryRecord showed that the
        justification never covered lists — absent and empty are already the
        same thing to a list on the read side, so omitting on empty is
        symmetric with the read. Numbers and enums are still excluded, for
        exactly the reason this test states.
        """
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="strings and lists only"):
            self._load(
                tmp_path,
                "{ name: x, type: int, unit: shares, required: false, "
                "omit_when_empty: true }",
            )

    def test_it_cannot_be_combined_with_omit_when_none(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="two different regimes"):
            self._load(
                tmp_path,
                "{ name: x, type: string, required: false, nullable: true, "
                "omit_when_none: true, omit_when_empty: true }",
            )

    def test_it_requires_optional(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="must also declare 'required: false'"):
            self._load(tmp_path, "{ name: x, type: string, omit_when_empty: true }")

    def test_it_cannot_be_combined_with_a_default(self, tmp_path: Any) -> None:
        """Found in 5.2a's holistic review, not by the build.

        ``from_dict`` reads an ``omit_when_empty`` field as
        ``str(p.get(key, ""))``, so a declared ``default:`` was silently
        ignored — the spec said one thing and the generated code did another.
        The empty string *is* the absence for this regime; there is nothing
        left for a default to supply.
        """
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="contradict each other"):
            self._load(
                tmp_path,
                '{ name: x, type: string, required: false, default: "z", '
                "omit_when_empty: true }",
            )
