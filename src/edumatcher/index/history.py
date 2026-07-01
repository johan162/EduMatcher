from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class IndexHistory:
    """Append-only JSONL manager for index history records."""

    def __init__(self, history_file: str) -> None:
        self._path = Path(history_file)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, separators=(",", ":")) + "\n")

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
                        if rec_type not in {
                            "LEVEL",
                            "EOD",
                            "CORP_ACTION",
                            "DELIST",
                            "ADD_CONSTITUENT",
                            "INIT",
                        }:
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

        return results, warnings
