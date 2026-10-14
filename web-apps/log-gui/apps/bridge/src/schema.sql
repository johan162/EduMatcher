CREATE TABLE IF NOT EXISTS issue_acks (
    fingerprint        TEXT PRIMARY KEY,
    acked_at           TEXT NOT NULL,
    acked_by           TEXT NOT NULL,
    note               TEXT,
    acked_through_seq  INTEGER NOT NULL,
    level              TEXT NOT NULL,
    process            TEXT NOT NULL,
    logger             TEXT NOT NULL,
    sample_message     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_acks_at ON issue_acks(acked_at);

CREATE TABLE IF NOT EXISTS ack_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint  TEXT NOT NULL,
    action       TEXT NOT NULL,
    at           TEXT NOT NULL,
    by            TEXT NOT NULL,
    note         TEXT
);