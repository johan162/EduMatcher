"""Phase 6.2: the third surface.

Design section 1 named three places a message is described — the publisher, the
subscriber, and the documentation — and said none of them is checked against
the others. The first two have been generated since 5.1. This file is the gate
on the third.

The coverage assertion is the one that matters. Every previous phase's
documentation defect (sections 26.6, 27.3, 27.6, 28.3) was a *statement* that
had gone false, and regenerating fixes that class outright. The class it does
not fix by itself is a message nobody documents at all — the hand-written page
described 67 of 106 — so that is asserted directly rather than assumed to
follow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from edumatcher.msgen.generators import markdown as md
from edumatcher.msgen.spec import PUBLISHERS, SpecError, load_all, load_family
from edumatcher.msgen.spec import load_transports

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"
REFERENCE = REPO_ROOT / "docs" / "user-guide" / "270-message-reference.md"
PREAMBLE = REPO_ROOT / "docs" / "user-guide" / "270-preamble.md"


@pytest.fixture(scope="module")
def families() -> list:
    _registry, fams = load_all(SPEC_ROOT)
    return fams


@pytest.fixture(scope="module")
def page() -> str:
    return REFERENCE.read_text(encoding="utf-8")


class TestTheAppendixDocumentsEveryMessage:
    """The gap generating it closes, stated as a number.

    The hand-written page had 67 `###` sections for 106 specified messages. A
    reference that silently omits a third of the system is worse than one that
    is merely out of date, because nothing about reading it reveals the
    omission.
    """

    def test_every_topic_has_a_section(self, families: list, page: str) -> None:
        missing = [
            m.topic
            for f in families
            for m in f.messages
            if m.topic and f"### `{m.topic}`" not in page
        ]
        assert missing == []

    def test_it_covers_more_than_the_page_it_replaced(self, families: list) -> None:
        """106, where the hand-written file managed 67."""
        total = sum(len(f.messages) for f in families)
        assert total == 106, total

    def test_every_record_type_has_a_section(self, families: list, page: str) -> None:
        missing = [
            t.name for f in families for t in f.types if f"#### `{t.name}`" not in page
        ]
        assert missing == []


class TestPublishedByIsAClosedSet:
    """Prose became an enum. Design section 30.2.

    The hand-written page said things like "pm-alf-console, pm-admin,
    pm-viewer, bots, or the API gateway, via PUSH :5555" — five names and a
    port, none of them checkable and one of them (`pm-viewer`) a process that
    does not exist.
    """

    def test_every_message_declares_a_publisher(self, families: list) -> None:
        undeclared = [
            f"{f.family}.{m.name}"
            for f in families
            for m in f.messages
            if not (m.doc or {}).get("published_by")
        ]
        assert undeclared == []

    def test_every_declared_publisher_is_in_the_vocabulary(
        self, families: list
    ) -> None:
        unknown = {
            who
            for f in families
            for m in f.messages
            for who in (m.doc or {}).get("published_by", ())
            if who not in PUBLISHERS
        }
        assert unknown == set()

    def test_the_loader_rejects_an_unknown_publisher(self, tmp_path: Path) -> None:
        """Section 23.1: the check has to have disagreed with something."""
        spec = tmp_path / "fake.yaml"
        spec.write_text(
            """
family: fake
version: 1
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc:
      motivation: "fixture"
      published_by: [pm_viewer]
    fields: [{ name: x, type: string }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            encoding="utf-8",
        )
        transports = load_transports(SPEC_ROOT / "transports.yaml")
        with pytest.raises(SpecError, match="not a known publisher"):
            load_family(spec, transports)

    def test_the_loader_requires_one(self, tmp_path: Path) -> None:
        spec = tmp_path / "fake.yaml"
        spec.write_text(
            """
family: fake
version: 1
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc:
      motivation: "fixture"
    fields: [{ name: x, type: string }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            encoding="utf-8",
        )
        transports = load_transports(SPEC_ROOT / "transports.yaml")
        with pytest.raises(SpecError, match="doc.published_by is required"):
            load_family(spec, transports)


class TestTheHandWrittenHalfIsCopiedThrough:
    """The preamble is prose the spec cannot state, and is not generated.

    A documentation generator that starts writing narrative is one that starts
    inventing, which is the failure this tool exists to remove rather than
    relocate.
    """

    def test_the_preamble_appears_verbatim(self, page: str) -> None:
        preamble = PREAMBLE.read_text(encoding="utf-8").rstrip("\n")
        assert preamble in page

    def test_the_generated_page_says_it_is_generated(self, page: str) -> None:
        assert page.startswith("<!--")
        assert "GENERATED FILE - DO NOT EDIT" in page

    def test_the_preamble_does_not(self) -> None:
        """It is the one half a human should still edit."""
        assert "DO NOT EDIT" not in PREAMBLE.read_text(encoding="utf-8")


class TestRenderingIsDeterministic:
    """Same property `pm-msgen check` needs from every other artifact."""

    def test_two_renders_are_identical(self, families: list) -> None:
        preamble = PREAMBLE.read_text(encoding="utf-8")
        assert md.render_reference(families, preamble) == md.render_reference(
            families, preamble
        )

    def test_the_committed_page_matches_the_spec(
        self, families: list, page: str
    ) -> None:
        preamble = PREAMBLE.read_text(encoding="utf-8")
        assert md.render_reference(families, preamble) == page

    def test_the_generated_body_never_emits_a_triple_newline(self, page: str) -> None:
        """Optional blocks vary per message; the blank runs must not.

        Asserted on the body alone. An earlier draft normalised the *whole*
        page, which meant the generator silently reformatted the hand-written
        preamble on every run — so this assertion holding over the full file
        would be evidence of the bug rather than of its absence.
        """
        body = page.split("## Topic index", 1)[1]
        assert "\n\n\n" not in body

    def test_the_preamble_keeps_its_own_blank_lines(self, page: str) -> None:
        """The half a human owns is passed through byte for byte."""
        preamble = PREAMBLE.read_text(encoding="utf-8")
        assert "\n\n\n" in preamble, "fixture assumes the preamble has a blank run"
        assert preamble.rstrip("\n") in page


class TestThePresenceColumnSaysWhichRegime:
    """Four regimes, four phrases — design section B.7.0.

    Presence is the thing the hand-written page was worst at: it wrote
    "optional" for all four, so a reader could not tell an absent key from a
    null one without reading the producer.
    """

    @pytest.mark.parametrize(
        "phrase",
        ["required", "omitted when unset", "omitted when empty", "`null` when unset"],
    )
    def test_each_regime_appears(self, phrase: str, page: str) -> None:
        assert f"| {phrase} |" in page

    def test_units_reach_the_page(self, page: str) -> None:
        """`unit` exists to be reviewable, which means it has to be visible."""
        for unit in ("display_price", "ticks", "shares", "duration_nanos"):
            assert f"unit `{unit}`" in page


class TestTheTopicIndex:
    def test_it_lists_every_topic_once(self, families: list, page: str) -> None:
        index = page.split("## Topic index", 1)[1].split("## Family", 1)[0]
        rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \|", index, re.M)
        topics = [t for t, _f in rows]
        expected = sorted(
            m.topic or f"{m.name} (no bus topic)" for f in families for m in f.messages
        )
        assert topics == expected
        assert len(topics) == len(set(topics))
