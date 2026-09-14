"""The episode index: section 6.2's SQLite schema, and the writer that fills it.

A **separate** database from ``pm-audit-cli``'s ``audit_index.db``, because the
two have different lifecycles. The event index is append-only and cheap to
extend; this one is a derived artifact, rebuilt whenever the reconstruction
rules change. Mixing them would make a lexicon tweak invalidate the event
index.

``rules_version`` is the safety catch. Bump it whenever the link rules, the
lexicon or the sort-key packing change, and a stale index is refused with a
message naming what changed rather than rendering subtly wrong prose from it.
A tool that silently reads an index built under different rules is worse than
one with no index at all, because the prose looks exactly the same either way.

**There is no incremental build.** A resume would have to restore the state
model, the link resolver and the open episodes, because all three carry
context across a chunk boundary; without them an episode spanning the boundary
splits in two. Resuming instead from the oldest still-open episode avoids that
and buys nothing -- a ``gateway`` span stays open for the whole session, which
on this repo's own logs puts the resume point at ordinal 0. Measured at
~6 300 lines/s a full rebuild is 2.7 minutes for a million-line day, so the
build is simply run again, and ``rebuild=False`` upserts on stable keys so
running it twice costs nothing but time.

**Links are resolved in SQL, not in memory.** The resolver names a link's two
ends by message id; the table wants episode ids. Holding the mapping in a dict
would put back the per-line growth section 7.1's retirement exists to remove,
so every fact's ref is a column and the join happens once, at the end, over an
index.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable, Mapping

from edumatcher.audit.replay.derived import derive
from edumatcher.audit.replay.episodes import Episode
from edumatcher.audit.replay.links import ref
from edumatcher.audit.replay.ordering import pack_sort_key
from edumatcher.audit.replay.state import StateModel

#: The shape of the tables below. Bumped when a column is added or retyped.
SCHEMA_VERSION = 1

#: What the rows *mean*: the link rules of section 5.1, the episode claim
#: rules of section 4, and :func:`~edumatcher.audit.replay.ordering.pack_sort_key`.
#: An index built under a different value is refused, not read.
RULES_VERSION = 1

META_SCHEMA_VERSION = "schema_version"
META_RULES_VERSION = "rules_version"
META_SOURCE_FILES = "source_files"
META_SOURCE_FINGERPRINT = "source_fingerprint"
META_BUILT_AT = "built_at"
META_COVERED_FROM = "covered_from"
META_COVERED_TO = "covered_to"

#: Rows per transaction. Large enough that the per-statement overhead
#: disappears, small enough that a build interrupted halfway has not buffered
#: a session's worth of work it is about to lose.
DEFAULT_BATCH = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id      INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    anchor_key      TEXT NOT NULL,
    correlation_id  TEXT,
    root_msg_id     TEXT,
    run_seq         INTEGER,
    symbol          TEXT,
    actor           TEXT,
    opened_sort_key TEXT NOT NULL,
    closed_sort_key TEXT,
    opened_ts       TEXT NOT NULL,
    closed_ts       TEXT,
    outcome         TEXT,
    summary         TEXT NOT NULL,
    facts_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_events (
    episode_id  INTEGER NOT NULL REFERENCES episodes(episode_id),
    seq_in_ep   INTEGER NOT NULL,
    ref         TEXT    NOT NULL,
    sort_key    TEXT    NOT NULL,
    receipt_ts  TEXT    NOT NULL,
    topic       TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    file        TEXT    NOT NULL,
    line_no     INTEGER NOT NULL,
    role        TEXT    NOT NULL,
    late        INTEGER NOT NULL DEFAULT 0,
    msg_id         TEXT,
    causation_id   TEXT,
    correlation_id TEXT,
    topic_seq      INTEGER,
    payload     TEXT    NOT NULL,
    PRIMARY KEY (episode_id, seq_in_ep)
);

CREATE TABLE IF NOT EXISTS links (
    from_episode  INTEGER NOT NULL REFERENCES episodes(episode_id),
    to_episode    INTEGER NOT NULL REFERENCES episodes(episode_id),
    relation      TEXT NOT NULL,
    confidence    TEXT NOT NULL,
    evidence      TEXT NOT NULL,
    PRIMARY KEY (from_episode, to_episode, relation)
);

-- Links exactly as the resolver stated them, addressed by ref rather than by
-- episode. `links` is this table projected onto episode pairs; two kinds of
-- row have no projection and live only here:
--   * a link whose two ends are in the SAME episode -- an ack and the
--     submission that caused it -- which the episode already expresses, and
--     which as a self-loop in `links` would be noise. `--explain` reads its
--     evidence and confidence from here.
--   * a link to a named CONDITION rather than a message
--     (`condition:KILL_SWITCH`): a thing that happened, not a thing that was
--     published, so it has no episode and cannot satisfy `links`'s foreign
--     key. Ask `WHERE to_ref = ? AND from_ref LIKE 'condition:%'`.
-- It is also what lets an incremental build attach an effect to a cause
-- written in an earlier chunk.
CREATE TABLE IF NOT EXISTS stated_links (
    from_ref    TEXT NOT NULL,
    to_ref      TEXT NOT NULL,
    relation    TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    PRIMARY KEY (from_ref, to_ref, relation)
);

CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id  INTEGER PRIMARY KEY,
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    episode_id  INTEGER REFERENCES episodes(episode_id),
    sort_key    TEXT NOT NULL,
    receipt_ts  TEXT NOT NULL,
    detail      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actors (
    gateway_id   TEXT PRIMARY KEY,
    description  TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    orders       INTEGER NOT NULL DEFAULT 0,
    trades       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ep_kind_key   ON episodes(kind, anchor_key);
CREATE INDEX IF NOT EXISTS idx_ep_sort       ON episodes(opened_sort_key);
CREATE INDEX IF NOT EXISTS idx_ep_symbol_ts  ON episodes(symbol, opened_ts);
CREATE INDEX IF NOT EXISTS idx_ep_actor_ts   ON episodes(actor, opened_ts);
CREATE INDEX IF NOT EXISTS idx_ee_sort       ON episode_events(sort_key);
-- The envelope's two questions, both keyed lookups rather than traversals.
CREATE INDEX IF NOT EXISTS idx_ee_ref        ON episode_events(ref);
CREATE INDEX IF NOT EXISTS idx_ee_msg        ON episode_events(msg_id);
CREATE INDEX IF NOT EXISTS idx_ee_cause      ON episode_events(causation_id);
CREATE INDEX IF NOT EXISTS idx_ee_chain      ON episode_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_ep_chain      ON episodes(correlation_id);
CREATE INDEX IF NOT EXISTS idx_links_to      ON links(to_episode);
CREATE INDEX IF NOT EXISTS idx_anom_code     ON anomalies(code, sort_key);
"""

_EPISODE_SQL = (
    "INSERT OR REPLACE INTO episodes (episode_id, kind, anchor_key, "
    "correlation_id, root_msg_id, run_seq, symbol, actor, opened_sort_key, "
    "closed_sort_key, opened_ts, closed_ts, outcome, summary, facts_json) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_EVENT_SQL = (
    "INSERT OR REPLACE INTO episode_events (episode_id, seq_in_ep, ref, "
    "sort_key, receipt_ts, topic, kind, file, line_no, role, late, msg_id, "
    "causation_id, correlation_id, topic_seq, payload) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_STATED_SQL = (
    "INSERT OR REPLACE INTO stated_links "
    "(from_ref, to_ref, relation, confidence, evidence) VALUES (?, ?, ?, ?, ?)"
)
_ANOMALY_SQL = (
    "INSERT INTO anomalies (code, severity, episode_id, sort_key, receipt_ts, "
    "detail) VALUES (?, ?, ?, ?, ?, ?)"
)

#: One join, over ``idx_ee_ref``. A link whose source is outside the index
#: resolves to nothing and is simply not a row -- which is the truthful
#: answer, and why the resolver's own ``CAUSE_NOT_FOUND`` is the finding
#: rather than this being one. A link within one episode is excluded for the
#: reason given on ``stated_links``.
_RESOLVE_SQL = """
INSERT OR REPLACE INTO links (from_episode, to_episode, relation, confidence, evidence)
SELECT src.episode_id, dst.episode_id, p.relation, p.confidence, p.evidence
  FROM stated_links AS p
  JOIN episode_events AS src ON src.ref = p.from_ref
  JOIN episode_events AS dst ON dst.ref = p.to_ref
 WHERE src.episode_id != dst.episode_id
"""


def fingerprint(paths: Iterable[Path]) -> str:
    """What the source logs looked like when the index was built.

    Size and modification time per file, which is enough to notice that a log
    has grown since -- the one thing dropping the incremental build (AR-3.4)
    would otherwise leave a reader to notice for themselves, by wondering why
    this afternoon's orders are missing.

    A file that has gone away fingerprints as absent rather than raising: the
    answer "this index no longer matches its sources" is the same either way.
    """
    parts = []
    for path in sorted(paths):
        try:
            info = path.stat()
            parts.append([str(path), info.st_size, info.st_mtime_ns])
        except OSError:
            parts.append([str(path), None, None])
    return json.dumps(parts)


class StaleIndexError(RuntimeError):
    """The index on disk was built under different rules or a different schema.

    Raised rather than papered over: the alternative is prose that reads
    exactly like correct prose and is not.
    """


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


@contextmanager
def reading(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Open the index for queries and close it again.

    ``sqlite3.Connection`` is itself a context manager, but its ``__exit__``
    commits or rolls back a transaction -- it does **not** close. Relying on
    it is the mistake that leaves the handle open, and since Python 3.14 an
    unclosed connection says so with a ``ResourceWarning`` pointing at
    whatever line the collector happened to run on.
    """
    conn = open_readonly(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def writing(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Open the index for writing and close it again."""
    conn = open_index(db_path)
    try:
        yield conn
    finally:
        conn.close()


def open_index(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the episode index, in WAL."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open an existing index for queries, refusing a stale one."""
    if not db_path.exists():
        raise FileNotFoundError(f"Episode index not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        check_versions(conn)
    except StaleIndexError:
        conn.close()
        raise
    return conn


def read_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM replay_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO replay_meta (key, value) VALUES (?, ?)", (key, value)
    )


def check_versions(conn: sqlite3.Connection) -> None:
    """Raise :class:`StaleIndexError` unless this index was built by this code."""
    for key, current in (
        (META_SCHEMA_VERSION, SCHEMA_VERSION),
        (META_RULES_VERSION, RULES_VERSION),
    ):
        stored = read_meta(conn, key)
        if stored is None:
            raise StaleIndexError(
                f"Episode index declares no {key}; rebuild it with --rebuild."
            )
        if stored != str(current):
            raise StaleIndexError(
                f"Episode index was built with {key}={stored}, this is "
                f"{current}. The reconstruction rules have changed since; "
                f"rebuild it with --rebuild."
            )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


class IndexWriter:
    """Writes episodes as they retire, in batches, inside one WAL transaction.

    Fed the same stream a renderer would read, so an indexed and an unindexed
    run see the same episodes in the same order -- which is what makes the
    golden fixtures cover both.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        state: StateModel,
        *,
        batch_size: int = DEFAULT_BATCH,
    ) -> None:
        self.conn = conn
        self.state = state
        self.batch_size = batch_size
        self.episodes = 0
        self._episodes: list[tuple[Any, ...]] = []
        self._events: list[tuple[Any, ...]] = []
        self._links: list[tuple[Any, ...]] = []
        self._anomalies: list[tuple[Any, ...]] = []
        #: Bounded by the number of gateways, not by the length of the log.
        self._actors: dict[str, list[Any]] = {}
        self._covered_from: str | None = None
        self._covered_to: str | None = None

    def write(self, episode: Episode) -> None:
        self.episodes += 1
        opened = episode.opened
        self._episodes.append(
            (
                episode.episode_id,
                episode.kind,
                episode.anchor_key,
                episode.correlation_id,
                episode.root_msg_id,
                episode.run_seq,
                episode.symbol,
                episode.actor,
                pack_sort_key(opened),
                (
                    _pack_closed(episode)
                    if episode.closed_sort_key is not None
                    else None
                ),
                episode.opened_ts.isoformat(),
                episode.closed_ts.isoformat() if episode.closed_ts else None,
                episode.outcome,
                summarise(episode),
                json.dumps(derive(episode).as_dict()),
            )
        )
        for event in episode.events:
            fact = event.fact
            key = pack_sort_key(fact)
            self._events.append(
                (
                    episode.episode_id,
                    event.seq_in_ep,
                    ref(fact),
                    key,
                    fact.receipt_raw,
                    fact.topic,
                    fact.kind,
                    fact.file or "",
                    fact.line_no,
                    event.role,
                    int(fact.late),
                    fact.msg_id,
                    fact.causation_id,
                    fact.correlation_id,
                    fact.topic_seq,
                    json.dumps(fact.payload),
                )
            )
            self._links.extend(
                (
                    link.source,
                    link.target,
                    link.relation,
                    link.confidence.value,
                    link.evidence,
                )
                for link in event.step.resolution.links
            )
            self._anomalies.extend(
                (
                    anomaly.code,
                    anomaly.severity,
                    episode.episode_id,
                    key,
                    anomaly.receipt_ts,
                    anomaly.detail,
                )
                for anomaly in event.step.anomalies
            )
            self._note_coverage(fact.receipt_raw)
        # Findings about the episode rather than about one of its facts, so
        # they have no fact to take a sort key from; the episode's own opening
        # key stands in, and each anomaly still carries its own receipt_ts.
        self._anomalies.extend(
            (
                anomaly.code,
                anomaly.severity,
                episode.episode_id,
                pack_sort_key(opened),
                anomaly.receipt_ts,
                anomaly.detail,
            )
            for anomaly in episode.anomalies
        )
        self._note_actor(episode)
        if len(self._episodes) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        """Commit what is buffered. Cheap to call; a no-op when empty."""
        if not (self._episodes or self._events or self._links or self._anomalies):
            return
        self.conn.executemany(_EPISODE_SQL, self._episodes)
        self.conn.executemany(_EVENT_SQL, self._events)
        self.conn.executemany(_STATED_SQL, self._links)
        self.conn.executemany(_ANOMALY_SQL, self._anomalies)
        self.conn.commit()
        self._episodes.clear()
        self._events.clear()
        self._links.clear()
        self._anomalies.clear()

    def finish(self, source_files: Iterable[Path]) -> None:
        """Flush, resolve the links to episode ids, and stamp the metadata.

        The fingerprint is taken *after* the read rather than before, so a log
        appended to mid-build fingerprints as the longer file and the next run
        rebuilds -- which is the safe direction to be wrong in.
        """
        self.flush()
        self.conn.execute(_RESOLVE_SQL)
        self._write_actors()
        write_meta(self.conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION))
        write_meta(self.conn, META_RULES_VERSION, str(RULES_VERSION))
        paths = list(source_files)
        write_meta(
            self.conn, META_SOURCE_FILES, json.dumps([str(path) for path in paths])
        )
        write_meta(self.conn, META_SOURCE_FINGERPRINT, fingerprint(paths))
        write_meta(
            self.conn,
            META_BUILT_AT,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        if self._covered_from is not None:
            write_meta(self.conn, META_COVERED_FROM, self._covered_from)
        if self._covered_to is not None:
            write_meta(self.conn, META_COVERED_TO, self._covered_to)
        self.conn.commit()

    # -- bookkeeping --------------------------------------------------------

    def _note_coverage(self, receipt_raw: str) -> None:
        """Track the window this build covers, in receipt order.

        Episodes come out as they retire rather than as they opened, so the
        bounds are taken over every fact rather than from the first and last
        episode -- which would be the first to *close* and the last to open.
        """
        if self._covered_from is None or receipt_raw < self._covered_from:
            self._covered_from = receipt_raw
        if self._covered_to is None or receipt_raw > self._covered_to:
            self._covered_to = receipt_raw

    def _note_actor(self, episode: Episode) -> None:
        actor = episode.actor
        if actor is None:
            return
        opened = episode.opened_ts.isoformat()
        closed = (episode.closed_ts or episode.opened_ts).isoformat()
        row = self._actors.get(actor)
        if row is None:
            gateway = self.state.gateways.get(actor)
            self._actors[actor] = [
                gateway.description if gateway else None,
                opened,
                closed,
                0,
                0,
            ]
            row = self._actors[actor]
        elif row[0] is None:
            # The description arrives on system.gateway_auth, which may be a
            # later episode than the first one this actor appears in.
            gateway = self.state.gateways.get(actor)
            row[0] = gateway.description if gateway else None
        row[1] = min(row[1], opened)
        row[2] = max(row[2], closed)
        if episode.kind == "order":
            row[3] += 1
        elif episode.kind == "trade":
            row[4] += 1

    def _write_actors(self) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO actors "
            "(gateway_id, description, first_seen, last_seen, orders, trades) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(gateway_id, *row) for gateway_id, row in sorted(self._actors.items())],
        )


def _pack_closed(episode: Episode) -> str:
    """The closing key, packed the same way the opening one is.

    Built from the stored tuple rather than from a Fact, because a session
    span is closed by a fact that belongs to the *next* episode (section 7.3)
    and this one never held it.
    """
    millis, msg_id, receipt, ordinal = episode.closed_sort_key or (
        0,
        "",
        episode.opened_ts,
        0,
    )
    return (
        f"{millis:013d}"
        f"\x1f{msg_id}"
        f"\x1f{receipt.isoformat(timespec='microseconds')}"
        f"\x1f{ordinal:012d}"
    )


def summarise(episode: Episode) -> str:
    """The one-line business summary section 6.2 stores pre-rendered.

    Deliberately flat: kind, anchor, outcome and the two things a reader scans
    a table for. The prose sentences of section 8.2 are the narrator's job and
    read from the episode, not from this column -- this is what ``episodes``
    prints as a row.
    """
    parts = [episode.kind, _short(episode.anchor_key)]
    if episode.symbol:
        parts.append(episode.symbol)
    if episode.actor:
        parts.append(episode.actor)
    parts.append(episode.outcome)
    return " ".join(parts)


def _short(anchor: str, length: int = 12) -> str:
    return anchor if len(anchor) <= length else f"{anchor[:length]}..."


def build(
    db_path: Path,
    episodes: Iterable[Episode],
    state: StateModel,
    source_files: Iterable[Path],
    *,
    rebuild: bool = False,
    batch_size: int = DEFAULT_BATCH,
) -> int:
    """Write *episodes* into the index at *db_path*, returning how many.

    ``rebuild`` empties the tables first. Without it the write is an upsert on
    stable keys, so building the same log twice is indistinguishable from
    building it once -- which is what lets the CLI build unconditionally when
    the index is absent or stale without having to reason about what is
    already there.
    """
    conn = open_index(db_path)
    try:
        if rebuild:
            clear(conn)
        writer = IndexWriter(conn, state, batch_size=batch_size)
        for episode in episodes:
            writer.write(episode)
        writer.finish(source_files)
        return writer.episodes
    finally:
        conn.close()


def clear(conn: sqlite3.Connection) -> None:
    """Empty every table. The index is derived, so this loses nothing."""
    for table in (
        "links",
        "stated_links",
        "anomalies",
        "episode_events",
        "episodes",
        "actors",
        "replay_meta",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def is_current(conn: sqlite3.Connection, source_files: Iterable[Path]) -> bool:
    """Whether this index still matches the logs it was built from.

    The versions are checked separately, by :func:`check_versions`, because
    the two failures want different words: rules changed under the index, or
    the log changed under the index.
    """
    return read_meta(conn, META_SOURCE_FINGERPRINT) == fingerprint(source_files)


def describe(conn: sqlite3.Connection) -> Mapping[str, str]:
    """Everything in ``replay_meta``, for ``--help``-style reporting."""
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM replay_meta")
    }
