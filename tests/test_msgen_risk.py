"""Phase 5.3a: the three kill switches.

``risk`` is sixteen topics and splits by what the command acts on — a
gateway's exposure (here) or an instrument (5.3b). The two groups share
nothing but ``gateway_id`` and ``reason``, which is what lets one land
without leaving the other half-migrated.

Nothing in the IDL had to grow. Design section 20.1 had already grepped all
thirty of this family's guards while deciding whether ``DaySummary`` was the
third paired-presence group or merely the third of many; every one is
single-key, so the family is presence regimes 1 and 4 throughout.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import risk as G
from edumatcher.models.generated._runtime import MessageValidationError


class TestTheWireIsUnchanged:
    """Byte-identical to the hand-written builders, which is the whole claim.

    Both sides derive from a ``to_dict`` over the same fields, so there is no
    excuse for a difference — the stronger of the two assertions design
    section "Two comparisons, not one" describes.
    """

    def test_kill_switch_minimal(self) -> None:
        assert M.make_kill_switch_msg("GW1") == G.make_kill_switch(
            gateway_id="GW1", symbol="", note="", command_id=""
        )

    def test_kill_switch_scoped_to_a_symbol(self) -> None:
        assert M.make_kill_switch_msg("GW1", "ACME", "C1") == G.make_kill_switch(
            gateway_id="GW1", symbol="ACME", note="", command_id="C1"
        )

    def test_kill_switch_ack_rejected(self) -> None:
        assert M.make_kill_switch_ack_msg(
            "GW1", False, "Gateway not connected: GW1"
        ) == G.make_kill_switch_ack(
            gateway_id="GW1", accepted=False, reason="Gateway not connected: GW1"
        )

    def test_kill_switch_ack_accepted(self) -> None:
        assert M.make_kill_switch_ack_msg(
            "GW1", True, cancelled_orders=3, cancelled_quotes=2, command_id="C1"
        ) == G.make_kill_switch_ack(
            gateway_id="GW1",
            accepted=True,
            cancelled_orders=3,
            cancelled_quotes=2,
            command_id="C1",
        )

    def test_gateway_targeted_pair(self) -> None:
        assert M.make_kill_switch_gateway_msg(
            "ADM", "GW2", note="fat finger", command_id="C1"
        ) == G.make_kill_switch_gateway(
            gateway_id="ADM",
            target_gateway_id="GW2",
            note="fat finger",
            command_id="C1",
        )
        assert M.make_kill_switch_gateway_ack_msg(
            "ADM", "GW2", True, cancelled_orders=5, cancelled_quotes=1
        ) == G.make_kill_switch_gateway_ack(
            gateway_id="ADM",
            accepted=True,
            target_gateway_id="GW2",
            cancelled_orders=5,
            cancelled_quotes=1,
        )

    def test_global_pair(self) -> None:
        assert M.make_kill_switch_global_msg(
            "ADM", note="halt", command_id="C1"
        ) == G.make_kill_switch_global(gateway_id="ADM", note="halt", command_id="C1")
        assert M.make_kill_switch_global_ack_msg(
            "ADM", True, cancelled_orders=9, cancelled_quotes=4, affected_gateways=3
        ) == G.make_kill_switch_global_ack(
            gateway_id="ADM",
            accepted=True,
            cancelled_orders=9,
            cancelled_quotes=4,
            affected_gateways=3,
        )


class TestPresence:
    def test_symbol_is_always_emitted_even_when_empty(self) -> None:
        """The handler reads ``if symbol_filter:``, so "" means all symbols.

        Regime 1, not regime 4: the hand-written builder always sent the key,
        and empty and absent are the same thing to the only consumer. Omitting
        it would be a defensible wire and a gratuitous change.
        """
        _topic, payload = M.decode(M.make_kill_switch_msg("GW1"))
        assert payload["symbol"] == ""

    def test_an_unset_note_and_command_id_are_absent(self) -> None:
        _topic, payload = M.decode(M.make_kill_switch_global_msg("ADM"))
        assert payload == {"gateway_id": "ADM"}

    def test_the_ack_counters_are_always_emitted(self) -> None:
        """0 on rejection, because a rejected kill switch cancelled nothing."""
        _topic, payload = M.decode(M.make_kill_switch_ack_msg("GW1", False, "nope"))
        assert payload["cancelled_orders"] == 0
        assert payload["cancelled_quotes"] == 0
        assert payload["reason"] == "nope"

    def test_the_ack_does_not_repeat_its_gateway_in_the_body(self) -> None:
        topic, payload = M.decode(M.make_kill_switch_ack_msg("GW1", True))
        assert topic == "risk.kill_switch_ack.GW1"
        assert "gateway_id" not in payload

    def test_the_gateway_ack_does_repeat_the_target(self) -> None:
        """Caller and target are different participants here.

        An ack naming only the topic's id would not say who was acted on,
        which is exactly what ``risk.kill_switch`` cannot express and this
        message exists for.
        """
        topic, payload = M.decode(
            M.make_kill_switch_gateway_ack_msg("ADM", "GW2", True)
        )
        assert topic == "risk.kill_switch_gateway_ack.ADM"
        assert payload["target_gateway_id"] == "GW2"


class TestTheNoteThatCouldNotBeSent:
    """``risk.kill_switch`` grew a ``note``; the engine had always read one.

    ``_handle_kill_switch`` did ``note = str(payload.get("note", ""))`` and
    published it to the admin monitor, but the builder had no such parameter
    and none of the four producers sent one — so ``kill_switch.self`` was the
    single admin action whose note was permanently blank, while its two
    siblings recorded a real one. Design section 22.2.
    """

    def test_the_builder_accepts_one_now(self) -> None:
        _topic, payload = M.decode(
            M.make_kill_switch_msg("GW1", note="risk limit breach")
        )
        assert payload["note"] == "risk limit breach"

    def test_it_is_absent_when_not_supplied(self) -> None:
        """Adding the field must not put a key on the wire nobody chose."""
        _topic, payload = M.decode(M.make_kill_switch_msg("GW1"))
        assert "note" not in payload

    def test_the_handler_still_reads_it(self) -> None:
        import inspect

        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine._handle_kill_switch)
        assert 'payload.get("note", "")' in source

    def test_all_three_kill_switches_can_carry_one(self) -> None:
        for frames in (
            M.make_kill_switch_msg("GW1", note="n"),
            M.make_kill_switch_gateway_msg("ADM", "GW2", note="n"),
            M.make_kill_switch_global_msg("ADM", note="n"),
        ):
            assert M.decode(frames)[1]["note"] == "n"


class TestAdoptionDidNotMakeAMalformedCommandSilent:
    """The §21.2 audit, applied to this family before adoption rather than after.

    ``_gateway_status`` builds ``f"Gateway not configured: {gw_id}"`` from the
    inbound gateway_id, and that lands in an ack whose ``reason`` the spec
    bounds at 512. Unlike pm-index, the engine survives the resulting
    MessageValidationError — ``_dispatch_pull_message`` wraps every branch —
    but ``_reject_after_error`` returns early for anything outside
    ``_ORDER_TOPICS``, so the caller would get **no ack at all** and wait for a
    timeout where before it got a real answer.
    """

    def test_an_over_long_reason_is_rejected_by_the_spec(self) -> None:
        with pytest.raises(MessageValidationError, match="max_len"):
            G.make_kill_switch_ack(gateway_id="GW1", accepted=False, reason="X" * 600)

    def test_an_over_long_gateway_id_is_rejected_by_the_spec(self) -> None:
        with pytest.raises(MessageValidationError, match="max_len"):
            G.make_kill_switch_ack(gateway_id="G" * 100, accepted=False)

    def test_the_handlers_clamp_what_they_echo_back(self) -> None:
        from edumatcher.engine.main import _MAX_WIRE_ID_LEN, _clamp_wire_id

        assert _clamp_wire_id("x" * 5000) == "X" * _MAX_WIRE_ID_LEN
        assert _clamp_wire_id("gw1") == "GW1"

    def test_a_hostile_gateway_id_still_produces_a_valid_ack(self) -> None:
        from edumatcher.engine.main import _clamp_wire_id

        gid = _clamp_wire_id("G" * 5000)
        frames = M.make_kill_switch_ack_msg(
            gid, False, f"Gateway not configured: {gid}"
        )
        assert frames[0] == b"risk.kill_switch_ack." + b"G" * 32

    def test_every_kill_switch_handler_reads_its_ids_through_the_clamp(self) -> None:
        """A grep, because the risk is a handler added later that forgets."""
        import inspect

        from edumatcher.engine.main import Engine

        for name in (
            "_handle_kill_switch",
            "_handle_kill_switch_gateway",
            "_handle_kill_switch_global",
        ):
            source = inspect.getsource(getattr(Engine, name))
            assert "_clamp_wire_id(payload.get(" in source, name
            assert 'str(payload.get("gateway_id", "")).upper()' not in source, name


class TestTheEmitterQuotesLikeBlack:
    """``kill_switch.symbol``'s doc is the first spec text containing a quote.

    Black prefers double quotes but switches to single ones when that avoids a
    backslash, and the emitter reproduces black rather than running it (risk
    R9). It escaped instead, so the committed binding was not black-clean —
    caught by ``test_generated_files_are_black_clean``, not by anything in the
    generator's own tests.
    """

    def test_a_doc_containing_a_double_quote_is_single_quoted(self) -> None:
        from edumatcher.msgen.generators.python import _pystr

        assert _pystr('says "hi"') == "'says \"hi\"'"

    def test_a_plain_doc_stays_double_quoted(self) -> None:
        from edumatcher.msgen.generators.python import _pystr

        assert _pystr("plain") == '"plain"'

    def test_a_doc_with_both_quote_kinds_escapes_the_double(self) -> None:
        from edumatcher.msgen.generators.python import _pystr

        assert _pystr('it\'s "both"') == '"it\'s \\"both\\""'

    def test_the_committed_binding_carries_the_quoted_doc(self) -> None:
        docs = [f["doc"] for f in G.describe_kill_switch() if f["name"] == "symbol"]
        assert docs == ['Scope to one instrument; "" cancels across all of them.']


class TestTheFamilyIsOnlyHalfSpecified:
    """5.3a declares six of sixteen topics, and the report can mislead.

    ``pm-msgen grep-literals`` counts literals of *declared* topics, so a
    half-specified family reports "0 literals - migrated" while ten topics of
    it are still hard-coded. That is literally true and easy to misread, which
    is why ``risk`` stays out of ``MIGRATED`` in test_msgen_literals.py until
    5.3b lands.
    """

    def test_six_topics_are_declared(self) -> None:
        assert len(G.FAMILY_TOPICS) == 6

    def test_the_instrument_scoped_half_is_not_here_yet(self) -> None:
        declared = set(G.FAMILY_TOPICS)
        for absent in (
            "risk.symbol_halt",
            "risk.symbol_resume",
            "risk.cancel_symbol",
            "risk.circuit_breaker_halt_all",
            "risk.circuit_breaker_resume_all",
        ):
            assert absent not in declared

    def test_risk_is_not_yet_claimed_as_migrated(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "tests/test_msgen_literals.py"
        ).read_text(encoding="utf-8")
        assert 'MIGRATED = ("trade", "order", "index")' in source


class TestTheTopicHelpers:
    def test_the_acks_are_parameterised(self) -> None:
        assert G.topic_kill_switch_ack("GW1") == "risk.kill_switch_ack.GW1"
        assert G.match_kill_switch_ack("risk.kill_switch_ack.GW1") == "GW1"
        assert G.match_kill_switch_ack("risk.kill_switch_ack.GW1.x") is None

    def test_the_prefix_is_what_subscribers_use(self) -> None:
        assert G.PREFIX_KILL_SWITCH_ACK == "risk.kill_switch_ack."

    def test_the_submissions_are_plain_topics(self) -> None:
        assert G.TOPIC_KILL_SWITCH == "risk.kill_switch"
        assert G.TOPIC_KILL_SWITCH_GATEWAY == "risk.kill_switch_gateway"
        assert G.TOPIC_KILL_SWITCH_GLOBAL == "risk.kill_switch_global"

    def test_the_global_ack_prefix_does_not_swallow_the_gateway_one(self) -> None:
        """Two ack topics share a prefix up to the word that separates them."""
        assert not G.PREFIX_KILL_SWITCH_GATEWAY_ACK.startswith(
            G.PREFIX_KILL_SWITCH_GLOBAL_ACK
        )
        assert G.match_kill_switch_ack("risk.kill_switch_global_ack.ADM") is None

    def test_describe_reports_the_declared_units(self) -> None:
        units = {f["name"]: f.get("unit") for f in G.describe_kill_switch_global_ack()}
        assert units["cancelled_orders"] == "dimensionless"
        assert units["affected_gateways"] == "dimensionless"


def test_the_generated_module_has_no_unchecked_builders_missing() -> None:
    """Every message here is flat, so every one keeps its hot-path twin."""
    for name in (
        "make_kill_switch_unchecked",
        "make_kill_switch_ack_unchecked",
        "make_kill_switch_gateway_unchecked",
        "make_kill_switch_gateway_ack_unchecked",
        "make_kill_switch_global_unchecked",
        "make_kill_switch_global_ack_unchecked",
    ):
        assert hasattr(G, name), name


def test_the_unchecked_twins_agree_byte_for_byte() -> None:
    kw: dict[str, Any] = {
        "gateway_id": "ADM",
        "accepted": True,
        "reason": "",
        "cancelled_orders": 9,
        "cancelled_quotes": 4,
        "affected_gateways": 3,
        "command_id": "C1",
    }
    assert G.make_kill_switch_global_ack_unchecked(
        **kw
    ) == G.make_kill_switch_global_ack(**kw)
