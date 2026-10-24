"""The episode index reader answers a window of any size.

Regression test for X10 (docs-design/EduMatcher-Sim-Forensics-Workplan.md
§9): ``pm-audit-replay anomalies`` on one 256 MB rotated file of a sim run
failed with ``sqlite3.OperationalError: too many SQL variables`` -- the
reader bound every episode id of the window into a single ``IN (...)``,
beyond SQLite's limit (32 766). Here the limit is lowered on a small index
instead of writing a 256 MB log.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from edumatcher.audit.replay import reader
from edumatcher.audit.replay.episodes import Episode
from edumatcher.audit.replay.index import reading
from tests.test_audit_replay_index import KILL_SWITCH, build_from

LIMIT = 3


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "audit_replay.db"
    build_from(KILL_SWITCH, path)
    return path


@pytest.fixture
def small(db: Path) -> Iterator[sqlite3.Connection]:
    with reading(db) as conn:
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, LIMIT)
        yield conn


def shape(episodes: list[Episode]) -> list[tuple[int, int, int]]:
    """(id, events, anomalies) per episode, in the order returned."""
    return [
        (
            e.episode_id,
            len(e.events),
            sum(len(ev.step.anomalies) for ev in e.events),
        )
        for e in episodes
    ]


def test_x10_a_window_with_more_episodes_than_sql_variables(
    db: Path, small: sqlite3.Connection
) -> None:
    with reading(db) as conn:
        expected = reader.episodes_in_window(conn)
    assert len(expected) > 2 * LIMIT, "the fixture must exceed the lowered limit"
    assert shape(reader.episodes_in_window(small)) == shape(expected)


def test_x10_neighbours_of_more_episodes_than_sql_variables(
    db: Path, small: sqlite3.Connection
) -> None:
    with reading(db) as conn:
        ids = [e.episode_id for e in reader.episodes_in_window(conn)]
        expected = reader.neighbours(conn, ids, recorded_only=False)
    assert expected, "the fixture must have links"
    found = reader.neighbours(small, ids, recorded_only=False)
    assert {k: sorted(v, key=str) for k, v in found.items()} == {
        k: sorted(v, key=str) for k, v in expected.items()
    }
