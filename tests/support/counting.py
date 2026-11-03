from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Generic, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")


class CallCounter(Generic[P, R]):
    def __init__(self, func: Callable[P, R]) -> None:
        self.func = func
        self.calls = 0

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        self.calls += 1
        return self.func(*args, **kwargs)


class IterationCounter(Generic[T]):
    def __init__(self, values: Iterable[T]) -> None:
        self.values = values
        self.iterations = 0

    def __iter__(self) -> Iterator[T]:
        for value in self.values:
            self.iterations += 1
            yield value


def assert_query_plan_has_no_temp_btree(
    conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()
) -> None:
    """Reject SQLite plans that sort/group into a temporary B-tree."""
    plan = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    assert not any("USE TEMP B-TREE" in str(row[3]).upper() for row in plan), plan
