"""The vocabulary (task AR-4.1).

The coverage test is the point of this file. Everything else the lexicon does
is a dictionary lookup; what it has to *guarantee* is that the spec cannot grow
an enum value the tool then renders as nothing, and the only way to guarantee
that is to enumerate the spec rather than the lexicon.

Two failure modes are asserted against directly, because both are worse than a
missing gloss: crashing on an unknown value, which makes the tool useless
exactly when the new value is what you are investigating, and rendering it as
an empty string, which leaves a sentence that still reads like a sentence.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from edumatcher.audit.replay.lexicon import (
    PHRASES,
    PREP_BY,
    PREP_FROM,
    PREP_WITH,
    VERB_CROSSED,
    VERB_HIT,
    VERB_LIFTED,
    VERB_TOOK,
    fill_verb,
    is_known,
    phrase,
)
from edumatcher.models.generated.registry import TOPIC_REGISTRY


def spec_enums() -> dict[str, set[str]]:
    """Every ``(field, value)`` the message spec declares, merged by field.

    Read off the generated registry rather than listed, so a value added to
    ``spec/messages/`` and regenerated turns up here without an edit -- which
    is the whole mechanism by which the coverage test can fail.
    """
    found: dict[str, set[str]] = defaultdict(set)
    for spec in TOPIC_REGISTRY.values():
        for field in spec["fields"]:
            if field["type"] == "enum" and field.get("values"):
                found[field["name"]].update(field["values"])
    return dict(found)


ENUMS = spec_enums()
PAIRS = sorted((field, value) for field, values in ENUMS.items() for value in values)


class TestCoverage:
    def test_the_spec_declares_enums_at_all(self) -> None:
        """Guards the guard: an empty inventory would make every test below
        pass by describing nothing."""
        assert len(PAIRS) > 100

    @pytest.mark.parametrize("field,value", PAIRS, ids=lambda p: str(p))
    def test_every_spec_enum_value_has_a_gloss(self, field: str, value: str) -> None:
        assert is_known(field, value), (
            f"{field}={value!r} is declared in spec/messages/ but has no "
            f"lexicon entry. Add one to PHRASES[{field!r}]."
        )

    def test_the_lexicon_glosses_nothing_the_spec_does_not_declare(self) -> None:
        """A stale entry is a value that was removed from the wire.

        Harmless to render, but it is the trail of a message shape that no
        longer exists, and EduMatcher does not keep those around.
        """
        stale = {
            (field, value)
            for field, values in PHRASES.items()
            for value in values
            if value not in ENUMS.get(field, set())
        }
        assert stale == set(), f"glossed but no longer in the spec: {sorted(stale)}"


class TestAnUnmappedValue:
    def test_prints_verbatim_in_backticks(self) -> None:
        assert phrase("side", "SIDEWAYS") == "`SIDEWAYS`"

    def test_an_unknown_field_is_not_a_crash_either(self) -> None:
        assert phrase("no_such_field", "VALUE") == "`VALUE`"

    def test_is_never_the_empty_string(self) -> None:
        """The failure that would leave a sentence still looking like one."""
        assert phrase("cancel_reason", "") == "``"
        assert is_known("cancel_reason", "") is False


class TestTheFillVerbs:
    """Section 8.2: getting these right is most of what makes it read like
    a person wrote it -- and one of them is a correctness issue, not style."""

    def test_an_aggressor_took(self) -> None:
        assert fill_verb("TAKER", "BUY", False) == (VERB_TOOK, PREP_FROM)

    def test_a_resting_bid_was_hit(self) -> None:
        """Market convention: a seller hits a bid."""
        assert fill_verb("MAKER", "BUY", False) == (VERB_HIT, PREP_BY)

    def test_a_resting_offer_was_lifted(self) -> None:
        """And a buyer lifts an offer."""
        assert fill_verb("MAKER", "SELL", False) == (VERB_LIFTED, PREP_BY)

    def test_an_uncross_names_no_aggressor(self) -> None:
        """The one that is correctness rather than style.

        The engine flags *both* sides of an auction print MAKER, so a rule
        reading the role alone would narrate an uncross as a passive fill and
        imply a taker on the other side that the engine says does not exist.
        """
        assert fill_verb("MAKER", "BUY", True) == (VERB_CROSSED, PREP_WITH)
        assert fill_verb("TAKER", "SELL", True) == (VERB_CROSSED, PREP_WITH)

    def test_a_missing_role_does_not_invent_one(self) -> None:
        """`liquidity_flag` is nullable in the spec."""
        assert fill_verb(None, "BUY", False) == (VERB_CROSSED, PREP_WITH)

    def test_the_aggressor_side_gloss_never_names_a_taker_in_an_auction(
        self,
    ) -> None:
        assert "nobody" in phrase("aggressor_side", "AUCTION")
        assert "took" not in phrase("aggressor_side", "AUCTION")


class TestTheGlossesReadAsWritten:
    """Spot checks on the phrasing the templates depend on.

    Glosses carry their own article where the sentence needs one -- "cancelled
    by a kill switch" -- because the article belongs to the phrase and not to
    the template. A gloss that lost its article would still render, just
    wrongly, so a handful are pinned.
    """

    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("cancel_reason", "KILL_SWITCH", "a kill switch"),
            ("cancel_reason", "QUOTE_LEG_FILLED", "the other leg of its quote filling"),
            ("reject_code", "INSTRUMENT_HALTED", "the instrument being halted"),
            ("halt_source", "CB", "the circuit breaker"),
            ("side", "BUY", "buy"),
            ("status", "PARTIAL", "partially filled"),
            ("order_type", "IOC", "immediate-or-cancel"),
        ],
    )
    def test_gloss(self, field: str, value: str, expected: str) -> None:
        assert phrase(field, value) == expected

    def test_no_gloss_is_empty_or_padded(self) -> None:
        for field, values in PHRASES.items():
            for value, text in values.items():
                assert text and text == text.strip(), f"{field}={value}"
