"""The verification dataset, replayed through the engine (smoke test).

``tools/verify_matching.sh`` generates a random session, paper-trades it
through ``OrderBook`` directly, replays it through a live ``pm-engine`` over
ZMQ and compares the two books. That is a genuinely valuable check and it ran
approximately never -- by the time anyone reached for it, it had gone stale in
five separate ways and did not start at all.

So the same dataset runs here, every suite run. What is different is the
vehicle: the engine is built in-process on fake sockets
(:mod:`tests.engine_harness`) and driven by calling its handlers, so there is
no subprocess, no port to collide on and nothing to time out. What is the same
is everything that matters -- the real ``Engine``, its validation, its dispatch
and its books, against the paper trader's.

The dataset is the point. A hand-written test asserts the case its author
thought of; a thousand seeded orders with amendments and cancellations
interleaved against whatever happens to be resting asserts that the engine and
a straightforward reimplementation of matching agree about *all* of it. That
is what caught the iceberg sweep that never terminated.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.engine_harness import connect, make_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gen_verification_set as gen  # noqa: E402

#: Enough to interleave thousands of orders across four books and still finish
#: in about a second. The tool's own default is ten thousand, which the heavy
#: test below runs.
SMOKE_COUNT = 1000

#: ``parse_fix_line``'s default, and therefore the gateway every order in the
#: dataset belongs to.
GATEWAY = "PAPER01"


def replay(engine: Any, lines: list[str]) -> None:
    """Drive the dataset through the engine's own inbound handlers.

    The same three verbs ``replay_to_engine.py`` puts on the wire, minus the
    wire: ``_handle_new_order`` is what the PULL socket would have called.
    """
    for line in lines:
        parsed = gen._fields(line)
        if parsed is None:
            continue
        verb, kv = parsed
        if verb == "NEW":
            order = gen.parse_fix_line(line, gateway_id=GATEWAY)
            if order is not None:
                engine._handle_new_order(order.to_dict())
        elif verb == "AMEND":
            engine._handle_amend(
                {
                    "order_id": kv["ID"],
                    "gateway_id": GATEWAY,
                    "price": float(kv["PRICE"]) if "PRICE" in kv else None,
                    "qty": int(kv["QTY"]) if "QTY" in kv else None,
                }
            )
        elif verb == "CANCEL":
            engine._handle_cancel({"order_id": kv["ID"], "gateway_id": GATEWAY})


def engine_books(engine: Any) -> dict[str, dict[str, Any]]:
    return {
        symbol: gen._snapshot_for_result(engine.books[symbol])
        for symbol in gen.SYMBOLS
        if symbol in engine.books
    }


def run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, count: int
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    """Generate, paper-trade and replay. Returns (paper, engine, counts)."""
    dataset = gen.generate(random.Random(42), count)
    engine, _pub = make_engine(
        monkeypatch,
        tmp_path,
        symbols=tuple(gen.SYMBOLS),
        gateways=(GATEWAY,),
        sessions_enabled=False,
    )
    connect(engine, GATEWAY)
    replay(engine, dataset.mm_lines + dataset.test_lines)
    return dataset.result, engine_books(engine), dataset.counts


class TestTheEngineAgreesWithThePaperTrader:
    def test_every_book_matches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        paper, engine, _counts = run(monkeypatch, tmp_path, SMOKE_COUNT)

        assert engine == paper

    def test_the_dataset_is_worth_comparing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Two empty books also match.

        The comparison above is only as good as the session behind it, so this
        asserts the session actually happened: trades on every symbol, and the
        amendment share the generator promises.
        """
        paper, _engine, counts = run(monkeypatch, tmp_path, SMOKE_COUNT)

        assert counts["trades"] > SMOKE_COUNT // 4
        assert all(paper[symbol]["last_price"] is not None for symbol in gen.SYMBOLS)
        assert all(paper[symbol]["bids"] for symbol in gen.SYMBOLS)

        touched = counts["amend"] + counts["cancel"]
        assert 0.2 < touched / SMOKE_COUNT < 0.4, counts
        assert counts["cancel"] > 0 and counts["amend"] > 0

    def test_the_dataset_is_a_function_of_its_seed(self) -> None:
        """A session that differs run to run turns a real defect into a flake,
        and makes `--seed 42` in the tool's own help a lie."""
        first = gen.generate(random.Random(42), 200)
        second = gen.generate(random.Random(42), 200)

        assert first.test_lines == second.test_lines
        assert first.result == second.result

    @pytest.mark.heavy
    def test_every_book_matches_over_the_full_dataset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The size ``verify_matching.sh`` actually defaults to.

        Marked heavy -- pyproject deselects it -- because the point of the
        smoke test is that it runs on every commit, and the point of this one
        is depth. ``-m heavy`` gives you the ten thousand.
        """
        paper, engine, _counts = run(monkeypatch, tmp_path, gen.DEFAULT_COUNT)

        assert engine == paper
