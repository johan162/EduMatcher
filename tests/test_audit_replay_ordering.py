"""Canonical ordering, the reorder window, and sequence gaps (task AR-1.4).

Wrong here is quiet: a misordered narrative still reads plausibly, and nothing
downstream can detect it. Hence the property test at the end, which is the one
that actually guards the invariant rather than a hand-picked example of it.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest

from edumatcher.audit.replay.anomalies import LATE_ARRIVAL, SEQ_GAP
from edumatcher.audit.replay.facts import Fact
from edumatcher.audit.replay.ordering import (
    ReorderWindow,
    detect_seq_gaps,
    in_canonical_order,
    mint_millis,
    ordered,
    sort_key,
)
from edumatcher.models.envelope import new_ulid, ulid_millis

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_EPOCH = datetime(2026, 9, 8, 9, 31, 0, tzinfo=timezone.utc)


def ulid_at(millis: int, counter: int = 0) -> str:
    """A ULID with a chosen timestamp, so ordering can be asserted exactly."""
    out = []
    value = millis
    for _ in range(10):
        out.append(_B32[value & 0x1F])
        value >>= 5
    stamp = "".join(reversed(out))
    tail = []
    value = counter
    for _ in range(16):
        tail.append(_B32[value & 0x1F])
        value >>= 5
    return stamp + "".join(reversed(tail))


def make_fact(
    *,
    kind: str = "order.new",
    ordinal: int = 0,
    minted_ms: int | None = None,
    counter: int = 0,
    received_ms: int | None = None,
    topic: str | None = None,
    topic_seq: int | None = None,
    enveloped: bool = True,
) -> Fact:
    """A Fact with only the fields ordering looks at."""
    base = int(_EPOCH.timestamp() * 1000)
    minted = base if minted_ms is None else minted_ms
    received = minted if received_ms is None else received_ms
    receipt = datetime.fromtimestamp(received / 1000, tz=timezone.utc)
    return Fact(
        kind=kind,
        actor=None,
        topic=topic or kind,
        receipt_ts=receipt,
        receipt_raw=receipt.isoformat(),
        symbol="AAPL",
        payload={},
        prices={},
        times={},
        msg_id=ulid_at(minted, counter) if enveloped else None,
        causation_id=None,
        correlation_id=None,
        topic_seq=topic_seq,
        ordinal=ordinal,
        file="audit.log",
        line_no=ordinal + 1,
        known=True,
    )


class TestMintMillis:
    def test_reads_the_timestamp_out_of_a_real_ulid(self) -> None:
        ulid = new_ulid()
        assert mint_millis(make_fact(minted_ms=ulid_millis(ulid))) == ulid_millis(ulid)

    def test_falls_back_to_the_receipt_clock_with_no_envelope(self) -> None:
        fact = make_fact(enveloped=False, received_ms=1_757_323_862_118)
        assert mint_millis(fact) == 1_757_323_862_118

    def test_a_malformed_id_falls_back_rather_than_crashing(self) -> None:
        fact = replace(make_fact(received_ms=1_757_323_862_118), msg_id="not-a-ulid")
        assert mint_millis(fact) == 1_757_323_862_118


class TestSortKey:
    def test_an_inverted_ack_and_fill_sort_back_into_mint_order(self) -> None:
        """The ack was minted first and recorded second. File order is a lie;
        mint order is not."""
        base = int(_EPOCH.timestamp() * 1000)
        fill = make_fact(kind="order.fill", ordinal=0, minted_ms=base + 4)
        ack = make_fact(kind="order.ack", ordinal=1, minted_ms=base + 1)
        assert [f.kind for f in in_canonical_order([fill, ack])] == [
            "order.ack",
            "order.fill",
        ]

    def test_ids_minted_in_one_millisecond_keep_their_counter_order(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        second = make_fact(kind="b", ordinal=0, minted_ms=base, counter=2)
        first = make_fact(kind="a", ordinal=1, minted_ms=base, counter=1)
        assert [f.kind for f in in_canonical_order([second, first])] == ["a", "b"]

    def test_an_engine_restart_needs_no_run_partitioning(self) -> None:
        """A ULID's timestamp prefix carries ordering straight across a restart,
        so nothing has to know a restart happened."""
        base = int(_EPOCH.timestamp() * 1000)
        before = make_fact(kind="before", ordinal=0, minted_ms=base)
        restart = make_fact(
            kind="system.startup_recovery", ordinal=1, minted_ms=base + 50
        )
        after = make_fact(kind="after", ordinal=2, minted_ms=base + 90)
        shuffled = [after, before, restart]
        assert [f.kind for f in in_canonical_order(shuffled)] == [
            "before",
            "system.startup_recovery",
            "after",
        ]

    def test_envelope_less_facts_interleave_by_receipt_time(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        enveloped_early = make_fact(kind="enveloped-early", ordinal=0, minted_ms=base)
        bare_middle = make_fact(
            kind="bare-middle", ordinal=1, enveloped=False, received_ms=base + 10
        )
        enveloped_late = make_fact(
            kind="enveloped-late", ordinal=2, minted_ms=base + 20
        )
        assert [
            f.kind
            for f in in_canonical_order([enveloped_late, bare_middle, enveloped_early])
        ] == ["enveloped-early", "bare-middle", "enveloped-late"]

    def test_envelope_less_facts_sort_stably_among_themselves(self) -> None:
        """Same receipt millisecond, no ids to separate them: file order decides,
        and decides the same way every time."""
        base = int(_EPOCH.timestamp() * 1000)
        facts = [
            make_fact(kind=f"bare-{i}", ordinal=i, enveloped=False, received_ms=base)
            for i in range(5)
        ]
        for _ in range(10):
            shuffled = facts[:]
            random.shuffle(shuffled)
            assert [f.kind for f in in_canonical_order(shuffled)] == [
                f.kind for f in facts
            ]

    def test_the_key_is_total(self) -> None:
        """No two facts in one stream can compare equal: ordinal is unique."""
        facts = [make_fact(ordinal=i, minted_ms=1000) for i in range(20)]
        assert len({sort_key(f) for f in facts}) == 20


class TestReorderWindow:
    def test_a_short_inversion_is_repaired(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        fill = make_fact(kind="order.fill", ordinal=0, minted_ms=base + 4)
        ack = make_fact(kind="order.ack", ordinal=1, minted_ms=base + 1)
        out = list(ReorderWindow(max_facts=8, max_seconds=5).emit([fill, ack]))
        assert [f.kind for f in out] == ["order.ack", "order.fill"]
        assert not any(f.late for f in out)

    def test_a_fact_past_its_window_is_emitted_in_place_and_tagged(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        stream = [
            make_fact(kind=f"on-time-{i}", ordinal=i, minted_ms=base + 1000 * i)
            for i in range(6)
        ]
        stream.append(make_fact(kind="straggler", ordinal=99, minted_ms=base))
        out = list(ReorderWindow(max_facts=2, max_seconds=1).emit(stream))

        kinds = [f.kind for f in out]
        # "In place", not put back where it belongs: canonically it is first.
        assert kinds[0] == "on-time-0"
        assert kinds.index("straggler") > 1
        straggler = next(f for f in out if f.kind == "straggler")
        assert straggler.late is True
        assert [a.code for a in straggler.anomalies] == [LATE_ARRIVAL]
        assert "minted 3.000s earlier" in straggler.anomalies[0].detail
        assert len(out) == len(stream)

    def test_nothing_is_dropped(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        stream = [
            make_fact(kind=f"f{i}", ordinal=i, minted_ms=base + 100 * (20 - i))
            for i in range(20)
        ]
        out = list(ReorderWindow(max_facts=3, max_seconds=0.2).emit(stream))
        assert sorted(f.kind for f in out) == sorted(f.kind for f in stream)

    def test_the_count_bound_closes_the_window(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        # All within one receipt millisecond, so only the count bound can fire.
        stream = [
            make_fact(kind=f"f{i}", ordinal=i, minted_ms=base + i, received_ms=base)
            for i in range(10)
        ]
        out = list(ReorderWindow(max_facts=2, max_seconds=3600).emit(stream))
        assert len(out) == 10

    @pytest.mark.parametrize("bad", [{"max_facts": 0}, {"max_seconds": -1}])
    def test_a_nonsense_window_is_rejected(self, bad: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            ReorderWindow(**bad)


class TestSeqGaps:
    def test_a_gap_is_reported_not_silently_skipped(self) -> None:
        stream = [
            make_fact(
                topic="order.fill.TRADER01", ordinal=0, topic_seq=41, minted_ms=1
            ),
            make_fact(
                topic="order.fill.TRADER01", ordinal=1, topic_seq=45, minted_ms=2
            ),
        ]
        out = list(detect_seq_gaps(stream))
        assert [a.code for a in out[1].anomalies] == [SEQ_GAP]
        assert "41->45" in out[1].anomalies[0].detail
        assert "3 message(s) missing" in out[1].anomalies[0].detail

    def test_a_contiguous_run_reports_nothing(self) -> None:
        stream = [
            make_fact(topic="trade.executed", ordinal=i, topic_seq=i + 1, minted_ms=i)
            for i in range(20)
        ]
        assert all(f.anomalies == () for f in detect_seq_gaps(stream))

    def test_counters_are_independent_per_topic(self) -> None:
        """order.fill.TRADER01 and order.fill.MM01 each count from 1; merging
        them would manufacture a gap on every message to the other gateway."""
        stream = [
            make_fact(topic="order.fill.TRADER01", ordinal=0, topic_seq=1, minted_ms=1),
            make_fact(topic="order.fill.MM01", ordinal=1, topic_seq=1, minted_ms=2),
            make_fact(topic="order.fill.TRADER01", ordinal=2, topic_seq=2, minted_ms=3),
            make_fact(topic="order.fill.MM01", ordinal=3, topic_seq=2, minted_ms=4),
        ]
        assert all(f.anomalies == () for f in detect_seq_gaps(stream))

    def test_a_decrease_is_a_restart_not_a_gap(self) -> None:
        """Sequences are per process and restart at 1."""
        stream = [
            make_fact(topic="trade.executed", ordinal=0, topic_seq=98, minted_ms=1),
            make_fact(topic="trade.executed", ordinal=1, topic_seq=1, minted_ms=2),
            make_fact(topic="trade.executed", ordinal=2, topic_seq=2, minted_ms=3),
        ]
        assert all(f.anomalies == () for f in detect_seq_gaps(stream))

    def test_a_fact_with_no_sequence_is_left_alone(self) -> None:
        """An archived line carries no metadata section at all."""
        stream = [make_fact(ordinal=0, enveloped=False)]
        assert list(detect_seq_gaps(stream))[0].anomalies == ()


class TestOrderedPipeline:
    def test_reorders_and_reports_in_one_pass(self) -> None:
        base = int(_EPOCH.timestamp() * 1000)
        stream = [
            make_fact(
                kind="order.fill",
                topic="order.fill.TRADER01",
                ordinal=0,
                minted_ms=base + 4,
                topic_seq=45,
            ),
            make_fact(
                kind="order.ack",
                topic="order.ack.TRADER01",
                ordinal=1,
                minted_ms=base + 1,
                topic_seq=41,
            ),
        ]
        out = list(ordered(stream, max_facts=8, max_seconds=5))
        assert [f.kind for f in out] == ["order.ack", "order.fill"]
        assert all(f.anomalies == () for f in out)


class TestShuffleProperty:
    def test_a_shuffled_stream_re_sorts_to_the_original_over_1000_trials(self) -> None:
        """The invariant the whole tool rests on. One thousand trials because a
        single shuffle can pass by luck on a short stream."""
        base = int(_EPOCH.timestamp() * 1000)
        # A mixed stream: enveloped facts across several topics, a few minted
        # inside one millisecond, and envelope-less ones interleaved by receipt.
        original: list[Fact] = []
        ordinal = 0
        for step in range(40):
            minted = base + step * 3
            original.append(
                make_fact(kind=f"e{step}", ordinal=ordinal, minted_ms=minted, counter=0)
            )
            ordinal += 1
            if step % 5 == 0:
                original.append(
                    make_fact(
                        kind=f"same-ms-{step}",
                        ordinal=ordinal,
                        minted_ms=minted,
                        counter=1,
                    )
                )
                ordinal += 1
            if step % 7 == 0:
                original.append(
                    make_fact(
                        kind=f"bare{step}",
                        ordinal=ordinal,
                        enveloped=False,
                        received_ms=minted + 1,
                    )
                )
                ordinal += 1

        expected = [f.kind for f in in_canonical_order(original)]
        assert expected == [f.kind for f in original], "fixture must start in order"

        rng = random.Random(20260913)
        for _ in range(1000):
            shuffled = original[:]
            rng.shuffle(shuffled)
            assert [f.kind for f in in_canonical_order(shuffled)] == expected
