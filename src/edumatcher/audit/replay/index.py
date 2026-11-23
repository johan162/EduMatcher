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
on this repo's own logs puts the resume point at ordinal 0. So the build is
simply run again: about 6 000 lines/s, which is minutes for a session's log
and over an hour for a simulation day of ~27 million lines -- which is why
only ``story`` and ``index`` use the index, and every report reads the log.

**A build is atomic.** It writes a scratch file beside the index and moves it
into place with :func:`os.replace` once complete, so a reader sees the old
index or the new one, never a half one; two builds at once each finish (the
last one wins); and an interrupted build leaves the old index as it was. The
finished file is in rollback-journal mode, not WAL: nothing writes to it once
it is in place, and a ``-wal``/``-shm`` pair would belong to the file name,
not to the file, so it would outlive the replace.

**Links are resolved in SQL, not in memory.** The resolver names a link's two
ends by message id; the table wants episode ids. Holding the mapping in a dict
would put back the per-line growth section 7.1's retirement exists to remove,
so every fact's ref is a column and the join happens once, at the end, over an
index.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable, Mapping
from urllib.parse import quote

from edumatcher.audit.replay.derived import derive
from edumatcher.audit.replay.episodes import Episode
from edumatcher.audit.replay.links import ref
from edumatcher.audit.replay.ordering import pack_sort_key, pack_sort_key_tuple
from edumatcher.audit.replay.state import StateModel

#: The shape of the tables below. Bumped when a column is added or retyped.
#: Bumped to 2 when ``anomalies`` gained ``file`` and ``line_no``: a finding
#: read back out of an index built before that has no source location, and a
#: column that is populated on one path and empty on the other is worse than
#: no column. There is no migration -- :func:`check_versions` refuses the old
#: index and ``ensure_index`` rebuilds it, which is the whole of the policy.
#: Version 3 added ``eseq``; version 4 added ``publisher_run`` for reset-aware
#: canonical ordering; version 5 added ``idx_sl_to``, without which every
#: ``story`` hop read the whole ``stated_links`` table.
SCHEMA_VERSION = 5

#: What the rows *mean*: the link rules of section 5.1, the episode claim
#: rules of section 4, and :func:`~edumatcher.audit.replay.ordering.pack_sort_key`.
#: An index built under a different value is refused, not read.
#: Bumped to 2 when the canonical sort key dropped ``msg_id``: a ULID's
#: random tail was ordering same-millisecond facts from different
#: publishers at random. Every stored ``sort_key`` from version 1 means
#: something different, so an old index has to be rebuilt.
#: Bumped to 3 for phase 8's nine new codes: an index built under 2 is
#: missing findings its rows do not say are missing, which is the one way a
#: stale index can be worse than no index.
#: Bumped to 4 for publisher-wide ``eseq`` gap/discontinuity findings.
#: Bumped to 5 when ``eseq`` became the canonical order within a publisher run.
RULES_VERSION = 5

META_SCHEMA_VERSION = "schema_version"
META_RULES_VERSION = "rules_version"
#: The detection settings the index was built under. Not a version: the
#: rules did not change, the options given to them did, and an index built
#: without --strict simply does not contain the findings --strict asks for.
META_DETECTION = "detection"
META_SOURCE_FILES = "source_files"
META_SOURCE_FINGERPRINT = "source_fingerprint"
META_BUILT_AT = "built_at"
META_COVERED_FROM = "covered_from"
META_COVERED_TO = "covered_to"

#: Episodes per transaction. Large enough that the per-statement overhead
#: disappears, small enough that the rows buffered in memory stay small.
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
    eseq           INTEGER,
    publisher_run  INTEGER NOT NULL DEFAULT 0,
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
-- `story` reads the links pointing at the refs it shows, over idx_sl_to.
CREATE TABLE IF NOT EXISTS stated_links (
    from_ref    TEXT NOT NULL,
    to_ref      TEXT NOT NULL,
    relation    TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    PRIMARY KEY (from_ref, to_ref, relation)
);

-- `file`/`line_no` for the reason `Anomaly` carries them: a finding a reader
-- cannot go and look at is a finding they cannot act on. The path is stored
-- as it was given, exactly as `episode_events.file` stores it; shortening it
-- for display is `Fact.source`'s job.
CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id  INTEGER PRIMARY KEY,
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    episode_id  INTEGER REFERENCES episodes(episode_id),
    sort_key    TEXT NOT NULL,
    receipt_ts  TEXT NOT NULL,
    detail      TEXT NOT NULL,
    file        TEXT,
    line_no     INTEGER NOT NULL DEFAULT 0
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
CREATE INDEX IF NOT EXISTS idx_sl_to         ON stated_links(to_ref);
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
    "causation_id, correlation_id, topic_seq, eseq, publisher_run, payload) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_STATED_SQL = (
    "INSERT OR REPLACE INTO stated_links "
    "(from_ref, to_ref, relation, confidence, evidence) VALUES (?, ?, ?, ?, ?)"
)
_ANOMALY_SQL = (
    "INSERT INTO anomalies (code, severity, episode_id, sort_key, receipt_ts, "
    "detail, file, line_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
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


class NotAnIndexError(RuntimeError):
    """The file ``--db`` names exists and is not an episode index.

    Refused, never replaced: an index can be rebuilt from the log, the file a
    mistyped ``--db`` names (``clearing.db``, someone's notes) cannot.
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


def open_index(db_path: Path) -> sqlite3.Connection:
    """Open an existing episode index for writing, or create an empty one.

    Refuses (:class:`NotAnIndexError`) a file that is not an episode index.
    The builder does not use this -- :func:`build` writes a scratch file and
    replaces the index whole -- so what is left is opening an index to
    inspect or adjust its metadata.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        _require_index(db_path)
    conn = sqlite3.connect(str(db_path))
    initialize_schema(conn)
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the current replay-index schema on an open SQLite connection."""
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()


def _readonly_uri(db_path: Path) -> str:
    """A ``mode=ro`` URI that survives ``?``, ``#`` and ``%`` in the path."""
    return f"file:{quote(str(db_path.resolve()))}?mode=ro"


def _require_index(db_path: Path) -> None:
    """Raise :class:`NotAnIndexError` unless *db_path* is an episode index.

    An index is a SQLite file with a ``replay_meta`` table, whatever version
    it declares: an index of an older shape is still ours to replace. Asked
    of the schema rather than of a row, so a file with no version row (one
    built before metadata was written) is an index too.
    """
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    try:
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'replay_meta'"
        ).fetchone()
    except sqlite3.DatabaseError:
        found = None
    finally:
        conn.close()
    if found is None:
        raise NotAnIndexError(
            f"{db_path} is not an episode index; refusing to read or replace "
            f"it. Point --db at the index file (default name "
            f"audit_replay.db)."
        )


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open an existing index for queries, refusing a stale one."""
    if not db_path.exists():
        raise FileNotFoundError(f"Episode index not found: {db_path}")
    _require_index(db_path)
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
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
    """Writes episodes as they retire, one transaction per batch.

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
                    fact.eseq,
                    fact.publisher_run,
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
                    anomaly.file,
                    anomaly.line_no,
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
                anomaly.file,
                anomaly.line_no,
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
    return pack_sort_key_tuple(
        episode.closed_sort_key
        or (
            0,
            1,
            0,
            episode.opened_ts,
            0,
        )
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
    batch_size: int = DEFAULT_BATCH,
    detection: str = "",
) -> int:
    """Write *episodes* into a fresh index at *db_path*, returning how many.

    Refuses (:class:`NotAnIndexError`) before reading anything when
    *db_path* exists and is not an episode index. The rows go to a scratch
    file beside it, which replaces the index only once complete (the module
    docstring says why); on any failure, Ctrl-C included, the scratch file is
    removed and the old index is untouched.

    The scratch file is written with no journal and no fsync: until the
    replace it is nobody's, and a crash simply leaves a file the next build's
    name does not collide with.
    """
    if db_path.exists():
        _require_index(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    scratch = db_path.with_name(f"{db_path.name}.building-{os.getpid()}")
    scratch.unlink(missing_ok=True)
    try:
        conn = sqlite3.connect(str(scratch))
        try:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            initialize_schema(conn)
            writer = IndexWriter(conn, state, batch_size=batch_size)
            for episode in episodes:
                writer.write(episode)
            writer.finish(source_files)
            write_meta(conn, META_DETECTION, detection)
            conn.commit()
        finally:
            conn.close()
        # Siblings of a WAL-mode index of an older build: they belong to the
        # name, so left behind they would be applied to the new file.
        for sibling in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            sibling.unlink(missing_ok=True)
        os.replace(scratch, db_path)
        return writer.episodes
    except BaseException:
        scratch.unlink(missing_ok=True)
        raise


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
