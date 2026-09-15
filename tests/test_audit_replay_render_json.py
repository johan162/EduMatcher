"""The machine-readable narrative (task AR-6.1).

Section 11's promise is not that NDJSON exists; it is that NDJSON and the
prose are the same narrative in two shapes. A consumer that builds a dashboard
off the beats and a human reading `stream` have to be looking at one set of
facts, or the tool has quietly become two tools that disagree.

So the load-bearing test here is :class:`TestTheTwoFormatsCannotDrift`, which
compares the two outputs directly at every detail level on every fixture. The
rest pin the object shapes that a consumer would reasonably build against.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import REPLAY_FIXTURES

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay import render_json, templates, views
from edumatcher.audit.replay.episodes import Episode, assemble
from edumatcher.audit.replay.pipeline import Reconstruction, reconstruct
from edumatcher.audit.replay.render_text import (
    CONTINUATION,
    Options,
    Renderer,
    narrate,
)

FIXTURES = REPLAY_FIXTURES
ALL = (
    "01_simple_limit_partial_fill",
    "02_halted_reject_and_kill_switch",
    "03_archived_no_envelope",
    "04_quote_oco_combo",
    "05_session_and_index",
)
LEVELS = (
    templates.LEVEL_OUTCOMES,
    templates.LEVEL_DEFAULT,
    templates.LEVEL_DEFAULT + 1,
    templates.LEVEL_DEFAULT + 2,
    templates.LEVEL_DEFAULT + 3,
)


def run(name: str) -> tuple[list[Episode], Reconstruction]:
    reconstruction, steps = reconstruct(iter_entries([FIXTURES / f"{name}.log"]))
    return (
        list(assemble(steps, reconstruction.state, reconstruction.links)),
        reconstruction,
    )


def objects(name: str, level: int = templates.LEVEL_DEFAULT) -> list[dict[str, Any]]:
    episodes, reconstruction = run(name)
    return list(
        render_json.objects(episodes, reconstruction.state, Options(level=level))
    )


def of_type(objs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [obj for obj in objs if obj["type"] == kind]


# ---------------------------------------------------------------------------
# The property the whole format exists for
# ---------------------------------------------------------------------------


class TestTheTwoFormatsCannotDrift:
    @pytest.mark.parametrize("name", ALL)
    @pytest.mark.parametrize("level", LEVELS)
    def test_every_prose_sentence_is_one_beats_text(
        self, name: str, level: int
    ) -> None:
        """The text renderer *is* the ``text`` field.

        Compared in order and one for one, not as sets: a format that narrated
        the same sentences in a different order would be a different account
        of the same session, which is the failure this is here to catch.
        """
        episodes, reconstruction = run(name)
        options = Options(level=level)
        prose = narrate(episodes, reconstruction.state, options)
        objs = list(render_json.objects(episodes, reconstruction.state, options))

        if level <= templates.LEVEL_OUTCOMES:
            # Level 0 is a list of outcomes, and its sentence is the episode's
            # summary rather than a beat.
            sentences = [obj["summary"] for obj in of_type(objs, "episode")]
        else:
            sentences = [obj["text"] for obj in of_type(objs, "beat")]

        # From level 2 the prose grows annotation lines beneath a sentence --
        # a rejection's reason, the mechanics, the raw payload. Those are not
        # beats of their own; NDJSON carries what they say in `fields`,
        # `prices` and the anomaly objects. They are indented by CONTINUATION,
        # and a sentence line never is, because it opens with a clock.
        heads = [line for line in prose if not line.startswith(CONTINUATION)]

        assert len(heads) == len(sentences)
        for head, text in zip(heads, sentences):
            assert head.endswith(text)

    @pytest.mark.parametrize("name", ALL)
    def test_the_annotations_are_the_only_extra_prose_lines(self, name: str) -> None:
        """``--explain`` and friends add lines beneath a sentence, and those
        are annotations of a beat rather than beats of their own. The beat
        count must not move when they are switched on."""
        episodes, reconstruction = run(name)
        plain = render_json.objects(episodes, reconstruction.state, Options())
        annotated = render_json.objects(
            episodes,
            reconstruction.state,
            Options(explain=True, show_source=True, show_units=True),
        )

        assert len(of_type(list(plain), "beat")) == len(
            of_type(list(annotated), "beat")
        )

    @pytest.mark.parametrize("name", ALL)
    def test_a_suppressed_fact_is_absent_from_both_or_neither(self, name: str) -> None:
        """Detail level is one decision, taken once. At ``-vvv`` nothing is
        withheld, so the beats must account for every event in the window."""
        episodes, reconstruction = run(name)
        events = sum(len(episode.events) for episode in episodes)
        loud = objects(name, templates.LEVEL_DEFAULT + 3)

        assert len(of_type(loud, "beat")) == events


# ---------------------------------------------------------------------------
# The object shapes
# ---------------------------------------------------------------------------


class TestTheObjects:
    def test_ndjson_is_one_json_object_per_line(self) -> None:
        episodes, reconstruction = run(ALL[0])
        lines = render_json.ndjson(episodes, reconstruction.state, Options())

        assert lines
        for line in lines:
            assert "\n" not in line
            assert json.loads(line)["type"] in {
                "episode",
                "beat",
                "link",
                "anomaly",
            }

    def test_an_episode_is_announced_before_its_first_beat(self) -> None:
        """So a consumer can process the stream without buffering it."""
        seen: set[int] = set()
        for obj in objects(ALL[3]):
            if obj["type"] == "episode":
                seen.add(int(obj["id"]))
            elif obj["type"] == "beat":
                assert int(obj["episode"]) in seen

    def test_an_episode_is_announced_once(self) -> None:
        ids = [
            obj["id"]
            for obj in of_type(objects(ALL[3], templates.LEVEL_DEFAULT + 2), "episode")
        ]
        assert ids and len(ids) == len(set(ids))

    def test_a_beat_carries_its_envelope_and_its_source(self) -> None:
        beat = of_type(objects(ALL[0]), "beat")[0]

        assert beat["correlation_id"]
        assert beat["source"]["file"] and beat["source"]["line"] > 0
        assert beat["sort_key"]

    def test_fields_is_the_payload_whole(self) -> None:
        """Not a curated subset: a consumer that needs a field the prose does
        not mention must not have to go back to the log for it."""
        episodes, reconstruction = run(ALL[0])
        by_line = {
            event.fact.line_no: event.fact
            for episode in episodes
            for event in episode.events
        }
        for beat in of_type(
            list(
                render_json.objects(
                    episodes,
                    reconstruction.state,
                    Options(level=templates.LEVEL_DEFAULT + 3),
                )
            ),
            "beat",
        ):
            assert beat["fields"] == dict(by_line[beat["source"]["line"]].payload)

    def test_a_resolved_price_is_offered_in_display_money(self) -> None:
        """Section 5.3.1's work, handed over rather than left to be redone."""
        priced = [
            beat
            for beat in of_type(objects(ALL[0], templates.LEVEL_DEFAULT + 3), "beat")
            if beat["prices"]
        ]
        assert priced
        assert all(isinstance(v, float) for b in priced for v in b["prices"].values())

    def test_a_link_names_two_different_episodes(self) -> None:
        """``index.py``'s projection rule: an end outside the window is not an
        edge, and an edge inside one episode is the episode."""
        objs = objects(ALL[3], templates.LEVEL_DEFAULT + 2)
        ids = {obj["id"] for obj in of_type(objs, "episode")}
        links = of_type(objs, "link")

        assert links
        for link in links:
            assert link["from"] != link["to"]
            assert link["from"] in ids and link["to"] in ids
            assert link["confidence"]

    def test_every_finding_reaches_the_stream(self) -> None:
        """The same findings the ``anomalies`` view reports, on the same
        episodes -- one reconstruction, not two."""
        episodes, reconstruction = run(ALL[1])
        objs = list(
            render_json.objects(
                episodes, reconstruction.state, Options(level=templates.LEVEL_DEFAULT)
            )
        )
        announced = {obj["id"] for obj in of_type(objs, "episode")}
        narrated = {
            (obj["episode"], obj["code"], obj["detail"])
            for obj in of_type(objs, "anomaly")
        }
        expected = {
            (episode.episode_id, anomaly.code, anomaly.detail)
            for episode in episodes
            if episode.episode_id in announced
            for anomaly in views.findings(episode)
        }

        assert expected
        assert narrated == expected

    def test_the_summary_is_the_renderers_own(self) -> None:
        """Not a second phrasing of the same episode."""
        episodes, reconstruction = run(ALL[0])
        renderer = Renderer(episodes, reconstruction.state, Options())
        for obj in of_type(objects(ALL[0]), "episode"):
            episode = next(e for e in episodes if e.episode_id == obj["id"])
            assert obj["summary"] == renderer.summary(episode)


class TestTheDocument:
    def test_it_wraps_the_same_objects_with_a_header(self) -> None:
        episodes, reconstruction = run(ALL[0])
        options = Options()
        doc = json.loads(
            render_json.document(
                episodes,
                reconstruction.state,
                options,
                window={"from": None, "to": None},
                source_files=["audit.log"],
                rules_version=2,
            )
        )
        stream = list(render_json.objects(episodes, reconstruction.state, options))

        assert doc["objects"] == stream
        assert doc["rules_version"] == 2
        assert doc["source_files"] == ["audit.log"]
        assert doc["counts"]["beat"] == len(of_type(stream, "beat"))


class TestMarkdown:
    def test_every_sentence_is_a_beats_text(self) -> None:
        episodes, reconstruction = run(ALL[0])
        options = Options()
        lines = render_json.markdown(episodes, reconstruction.state, options)
        texts = {
            obj["text"]
            for obj in of_type(
                list(render_json.objects(episodes, reconstruction.state, options)),
                "beat",
            )
        }

        bullets = [line for line in lines if line.startswith("- ")]
        assert bullets
        for bullet in bullets:
            assert bullet.split("` ", 1)[1] in texts

    def test_it_has_a_heading_per_narrated_episode(self) -> None:
        episodes, reconstruction = run(ALL[0])
        options = Options()
        lines = render_json.markdown(episodes, reconstruction.state, options)
        announced = of_type(
            list(render_json.objects(episodes, reconstruction.state, options)),
            "episode",
        )

        assert len([line for line in lines if line.startswith("## ")]) == len(announced)
