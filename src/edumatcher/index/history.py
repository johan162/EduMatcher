from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Record types written to the JSONL file. This file is an append-only
# structural/audit log — it is NOT the home for level-update history.
# Every index.update tick (including end-of-day closes) is instead
# recorded by pm-stats in the index_level_snapshots / index_daily_stats
# SQLite tables, which are built for efficient time-range queries.
# See docs/user-guide/150-index.md and docs/user-guide/140-statistics-and-reporting.md.
STRUCTURAL_RECORD_TYPES: frozenset[str] = frozenset(
    {"INIT", "CORP_ACTION", "DELIST", "ADD_CONSTITUENT"}
)


class IndexHistory:
    """Append-only JSONL manager for structural index audit records.

    Holds only structural/corporate-action events (index creation,
    splits, dividends, share issuance, delistings, constituent
    additions) — never per-tick level updates. Level and end-of-day
    history now lives exclusively in pm-stats' SQLite tables.
    """

    def __init__(self, history_file: str) -> None:
        self._path = Path(history_file)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        log.debug(
            "history append path=%s type=%s index_id=%s",
            self._path,
            record.get("type", "?"),
            record.get("index_id", "?"),
        )

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "IndexHistory":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = (exc_type, exc, tb)
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Never raise during GC finalization.
            pass

    def query(
        self,
        from_ts: float,
        to_ts: float,
        types: set[str],
        max_records: int = 10_000,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        if to_ts < from_ts:
            raise ValueError("to_ts must be >= from_ts")
        if max_records <= 0:
            raise ValueError("max_records must be > 0")

        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        warnings.append("ignored malformed history line")
                        continue

                    rec_type = rec.get("type")
                    ts = rec.get("timestamp")
                    if not isinstance(rec_type, str):
                        warnings.append("ignored record with invalid type")
                        continue
                    if rec_type not in types:
                        if rec_type not in STRUCTURAL_RECORD_TYPES:
                            warnings.append(f"ignored unknown record type: {rec_type}")
                        continue
                    try:
                        ts_f = float(ts)
                    except (TypeError, ValueError):
                        warnings.append("ignored record with invalid timestamp")
                        continue

                    if from_ts <= ts_f <= to_ts:
                        results.append(rec)
                        if len(results) >= max_records:
                            break
        except FileNotFoundError:
            return [], []

        log.debug(
            "history query path=%s from_ts=%.3f to_ts=%.3f types=%s max_records=%d returned=%d warnings=%d",
            self._path,
            from_ts,
            to_ts,
            sorted(types),
            max_records,
            len(results),
            len(warnings),
        )
        return results, warnings
