"""The episode index (task AR-3.3).

Three things carry the weight here.

**The version guard actually refuses.** A stale index renders prose that looks
exactly like correct prose, so the failure mode of a guard that does not fire
is silent and total. Both versions are asserted, and so is the message.

**Links resolve in SQL, not in memory.** Holding a ref-to-episode map would
put back the per-line growth section 7.1's retirement removed. The join has
three outcomes -- resolved, same-episode, and a link to a condition rather
than a message -- and each gets a test.

**What goes in comes out.** Every fact in the log is a row in
``episode_events``, once, and the packed sort key orders them the way the
canonical key does.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.conftest import opened

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay.episodes import assemble
from edumatcher.audit.replay.index import (
    META_RULES_VERSION,
    META_SCHEMA_VERSION,
    RULES_VERSION,
    SCHEMA_VERSION,
    StaleIndexError,
    build,
    describe,
    open_index,
    reading,
    open_readonly,
    write_meta,
)
from edumatcher.audit.replay.ordering import in_canonical_order, pack_sort_key
from edumatcher.audit.replay.pipeline import reconstruct

FIXTURES = Path("tests/fixtures/replay")
SIMPLE = FIXTURES / "01_simple_limit_partial_fill.log"
KILL_SWITCH = FIXTURES / "02_halted_reject_and_kill_switch.log"
ARCHIVED = FIXTURES / "03_archived_no_envelope.log"


def build_from(
    log: Path, db: Path, *, rebuild: bool = False, batch_size: int = 500
) -> int:
    run, steps = reconstruct(iter_entries([log]))
    return build(
        db,
        assemble(steps, run.state, run.links),
        run.state,
        [log],
        rebuild=rebuild,
        batch_size=batch_size,
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "audit_replay.db"


# ---------------------------------------------------------------------------
# The version guard
# ---------------------------------------------------------------------------


class TestTheVersionGuard:
    def test_a_fresh_index_stamps_both_versions(self, db: Path) -> None:
        build_from(SIMPLE, db)
        with reading(db) as conn:
            meta = describe(conn)
        assert meta[META_SCHEMA_VERSION] == str(SCHEMA_VERSION)
        assert meta[META_RULES_VERSION] == str(RULES_VERSION)

    def test_an_index_built_under_other_rules_is_refused(self, db: Path) -> None:
        build_from(SIMPLE, db)
        conn = opened(open_index(db))
        write_meta(conn, META_RULES_VERSION, "0")
        conn.commit()
        conn.close()
        with pytest.raises(StaleIndexError, match="rules_version=0"):
            open_readonly(db)

    def test_an_index_built_under_another_schema_is_refused(self, db: Path) -> None:
        build_from(SIMPLE, db)
        conn = opened(open_index(db))
        write_meta(conn, META_SCHEMA_VERSION, "0")
        conn.commit()
        conn.close()
        with pytest.raises(StaleIndexError, match="rebuild it with --rebuild"):
            open_readonly(db)

    def test_an_index_that_declares_nothing_is_refused(self, db: Path) -> None:
        """An empty file with the right tables is not a usable index."""
        open_index(db).close()
        with pytest.raises(StaleIndexError, match="declares no schema_version"):
            open_readonly(db)

    def test_a_missing_index_is_not_a_stale_one(self, db: Path) -> None:
        with pytest.raises(FileNotFoundError):
            open_readonly(db)


# ---------------------------------------------------------------------------
# What goes in comes out
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_every_line_of_the_log_is_one_event_row(self, db: Path) -> None:
        for log in (SIMPLE, KILL_SWITCH, ARCHIVED):
            build_from(log, db, rebuild=True)
            conn = opened(open_readonly(db))
            rows = conn.execute("SELECT file, line_no FROM episode_events").fetchall()
            lines = [
                line
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert len(rows) == len(lines), log.name
            assert len({tuple(r) for r in rows}) == len(rows), f"{log.name}: dup"

    def test_every_event_belongs_to_an_episode_that_exists(self, db: Path) -> None:
        build_from(KILL_SWITCH, db)
        conn = opened(open_readonly(db))
        orphaned = conn.execute(
            "SELECT COUNT(*) FROM episode_events e "
            "WHERE NOT EXISTS (SELECT 1 FROM episodes p "
            "                  WHERE p.episode_id = e.episode_id)"
        ).fetchone()[0]
        assert orphaned == 0

    def test_the_covered_window_spans_the_whole_log(self, db: Path) -> None:
        """Episodes retire out of order, so the bounds are over facts."""
        build_from(SIMPLE, db)
        with reading(db) as conn:
            meta = describe(conn)
        raw = [
            line[1 : line.index("]")]
            for line in SIMPLE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert meta["covered_from"] == min(raw)
        assert meta["covered_to"] == max(raw)


class TestTheSortKey:
    def test_the_packed_key_orders_events_the_way_the_tuple_does(
        self, db: Path
    ) -> None:
        build_from(SIMPLE, db)
        conn = opened(open_readonly(db))
        by_key = [
            r["line_no"]
            for r in conn.execute(
                "SELECT line_no FROM episode_events ORDER BY sort_key"
            )
        ]
        run, steps = reconstruct(iter_entries([SIMPLE]))
        canonical = [f.line_no for f in in_canonical_order(s.fact for s in steps)]
        assert by_key == canonical

    def test_an_envelope_less_fact_sorts_before_an_enveloped_one(self) -> None:
        """The empty msg_id field, which is what `sort_key` relies on too."""
        run, steps = reconstruct(iter_entries([ARCHIVED]))
        facts = [s.fact for s in steps]
        packed = sorted(pack_sort_key(f) for f in facts)
        assert packed == [pack_sort_key(f) for f in in_canonical_order(facts)]


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


class TestLinks:
    def test_a_cross_episode_cause_becomes_a_link_row(self, db: Path) -> None:
        build_from(SIMPLE, db)
        conn = opened(open_readonly(db))
        rows = conn.execute(
            "SELECT src.kind, dst.kind, l.relation, l.confidence "
            "FROM links l "
            "JOIN episodes src ON src.episode_id = l.from_episode "
            "JOIN episodes dst ON dst.episode_id = l.to_episode"
        ).fetchall()
        assert ("order", "trade", "caused", "RECORDED") in {tuple(r) for r in rows}

    def test_a_link_inside_one_episode_is_not_a_self_loop(self, db: Path) -> None:
        """An ack and its submission are one episode; the row would be noise."""
        build_from(SIMPLE, db)
        conn = opened(open_readonly(db))
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM links WHERE from_episode = to_episode"
            ).fetchone()[0]
            == 0
        )
        # It is still stated, so --explain can show its evidence.
        assert conn.execute("SELECT COUNT(*) FROM stated_links").fetchone()[0] > 0

    def test_a_condition_link_is_kept_where_a_foreign_key_cannot_hold_it(
        self, db: Path
    ) -> None:
        build_from(KILL_SWITCH, db)
        conn = opened(open_readonly(db))
        reasons = {
            r["from_ref"]
            for r in conn.execute(
                "SELECT from_ref FROM stated_links WHERE from_ref LIKE 'condition:%'"
            )
        }
        assert "condition:KILL_SWITCH" in reasons

    def test_links_survive_an_envelope_less_log(self, db: Path) -> None:
        """The fallback tiers state refs as @ordinal; the join reads those too."""
        build_from(ARCHIVED, db)
        conn = opened(open_readonly(db))
        rows = {
            (r["a"], r["b"], r["relation"], r["evidence"])
            for r in conn.execute(
                "SELECT src.kind AS a, dst.kind AS b, l.relation, l.evidence "
                "FROM links l "
                "JOIN episodes src ON src.episode_id = l.from_episode "
                "JOIN episodes dst ON dst.episode_id = l.to_episode"
            )
        }
        assert ("order", "trade", "matched_with", "sell_order_id") in rows

    def test_a_trade_and_its_order_are_linked_from_both_ends(self, db: Path) -> None:
        """Two rows, not one: each end states it on its own evidence.

        `links` is a directed table and the two directions were established
        independently -- the trade names the order, and the fill names the
        trade -- so collapsing them would throw away one of the two reasons
        the tool has for believing the pair.
        """
        build_from(ARCHIVED, db)
        conn = opened(open_readonly(db))
        pairs = [
            (r["from_episode"], r["to_episode"], r["evidence"])
            for r in conn.execute(
                "SELECT from_episode, to_episode, evidence FROM links "
                "WHERE relation = 'matched_with'"
            )
        ]
        assert len(pairs) == 2
        assert {(a, b) for a, b, _ in pairs} == {(p[1], p[0]) for p in pairs}
        assert len({evidence for _, _, evidence in pairs}) == 2


# ---------------------------------------------------------------------------
# Episodes, anomalies, actors
# ---------------------------------------------------------------------------


class TestRows:
    def test_derived_facts_land_in_facts_json(self, db: Path) -> None:
        import json

        build_from(SIMPLE, db)
        conn = opened(open_readonly(db))
        row = conn.execute(
            "SELECT facts_json FROM episodes WHERE kind = 'trade'"
        ).fetchone()
        assert json.loads(row["facts_json"])["crossed_in_uncross"] is False

    def test_an_anomaly_is_anchored_to_the_episode_that_raised_it(
        self, db: Path
    ) -> None:
        build_from(KILL_SWITCH, db)
        conn = opened(open_readonly(db))
        row = conn.execute(
            "SELECT a.code, e.kind FROM anomalies a "
            "JOIN episodes e ON e.episode_id = a.episode_id"
        ).fetchone()
        assert (row["code"], row["kind"]) == ("EFFECT_COUNT_MISMATCH", "command")

    def test_a_symbol_wildcard_is_not_an_actor(self, db: Path) -> None:
        """`book.AAPL` is parameterised by symbol; AAPL is not a gateway."""
        build_from(SIMPLE, db)
        conn = opened(open_readonly(db))
        actors = {
            r["gateway_id"] for r in conn.execute("SELECT gateway_id FROM actors")
        }
        assert "AAPL" not in actors
        assert "TRADER01" in actors

    def test_an_actor_carries_the_description_that_names_it(self, db: Path) -> None:
        build_from(SIMPLE, db)
        conn = opened(open_readonly(db))
        row = conn.execute(
            "SELECT description, orders FROM actors WHERE gateway_id = 'TRADER01'"
        ).fetchone()
        assert row["description"] == "Nordic Equities desk"
        assert row["orders"] == 1


class TestRebuilding:
    """AR-3.4 was dropped, so rebuilding *is* the incremental story.

    What was to be asserted of a three-chunk build is asserted here instead,
    and at full strength: every row of every table, not a count. "Byte
    identical" was never achievable -- ``built_at`` differs between runs and
    SQLite's page allocation is not a property of this tool -- so the
    comparison is over rows, with that one meta key excluded.
    """

    def test_a_rebuild_is_row_identical_to_a_fresh_build(
        self, db: Path, tmp_path: Path
    ) -> None:
        fresh = tmp_path / "fresh.db"
        build_from(KILL_SWITCH, fresh)
        build_from(SIMPLE, db)
        build_from(KILL_SWITCH, db, rebuild=True)
        assert _rows(db) == _rows(fresh)

    def test_building_the_same_log_twice_is_indistinguishable_from_once(
        self, db: Path
    ) -> None:
        """Keys are stable, so a re-run upserts rather than doubling.

        This is what lets the CLI build whenever the index is absent or stale
        without first working out what is already in it.
        """
        build_from(SIMPLE, db)
        once = _rows(db)
        build_from(SIMPLE, db)
        assert _rows(db) == once

    def test_the_batch_size_changes_nothing_but_the_transactions(
        self, db: Path, tmp_path: Path
    ) -> None:
        one_at_a_time = tmp_path / "small.db"
        build_from(KILL_SWITCH, one_at_a_time, batch_size=1)
        build_from(KILL_SWITCH, db, batch_size=10_000)
        assert _rows(db) == _rows(one_at_a_time)

    def test_the_index_is_in_wal_mode(self, db: Path) -> None:
        build_from(SIMPLE, db)
        conn = sqlite3.connect(str(db))
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        conn.close()


_TABLES = (
    "episodes",
    "episode_events",
    "links",
    "stated_links",
    "anomalies",
    "actors",
)


def _rows(db: Path) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every table, sorted, with the build stamp excluded.

    ``anomaly_id`` is an autoincrement and so is dropped: two builds of one
    log raise the same anomalies, and numbering them from a different starting
    point is not a difference in what the index says.
    """
    conn = opened(open_readonly(db))
    snapshot: dict[str, list[tuple[object, ...]]] = {}
    for table in _TABLES:
        rows = [tuple(r) for r in conn.execute(f"SELECT * FROM {table}")]
        if table == "anomalies":
            rows = [r[1:] for r in rows]
        snapshot[table] = sorted(rows, key=repr)
    snapshot["replay_meta"] = sorted(
        (key, value) for key, value in describe(conn).items() if key != "built_at"
    )
    return snapshot
