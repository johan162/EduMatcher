"""The round-trip property (task AR-4.5) — the most important test here.

**Nothing may vanish silently.** For any window, every event in the audit trail
must end up in exactly one of three states:

1. **narrated** -- it produced a line;
2. **withheld** -- this detail level does not show its kind, and
   :func:`~edumatcher.audit.replay.render_text.suppressed` says so;
3. **an orphan** -- the tool could not attach it, said so, and counted it.

A narrative that quietly drops events is worse than no narrative, because it
will be believed. So this is asserted per event rather than by counting: a
count can balance while two different events swap places.

The events come from ``pm-audit-cli``'s own reader, not from the replay
pipeline, so the two tools are compared rather than one being used to check
itself.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPLAY_FIXTURES, replay_logs

from edumatcher.audit.query import AuditEntry, iter_entries
from edumatcher.audit.replay import templates
from edumatcher.audit.replay.episodes import KIND_ORPHAN, Episode, assemble
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.audit.replay.render_text import (
    Options,
    Renderer,
    suppressed,
)
from edumatcher.audit.replay.state import StateModel

FIXTURES = REPLAY_FIXTURES
LOGS = replay_logs()
LEVELS = (0, 1, 2, 3, 4)

#: How much session to generate. Big enough to be a different kind of input
#: from the hand-written fixtures -- many symbols, many gateways, orders
#: interleaved rather than one at a time -- and small enough that running it at
#: three detail levels stays under a second.
SESSION_ROUNDS = 400
SYMBOLS = ("AAPL", "MSFT", "TSLA", "NVDA")
TRADERS = ("TRADER01", "TRADER02", "MM01", "MM02")

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid(millis: int, counter: int) -> str:
    """A ULID whose timestamp matches its line, built without randomness.

    Deterministic so a failure is reproducible: a generated session that
    differs run to run turns a real defect into a flake.
    """
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


def write_session(path: Path) -> Path:
    """A generated trading session: the input AR-4.5 actually asks for.

    The plan says "run over a full captured session". The capture it meant
    lives under ``deployment/docker/data/``, which is gitignored as "runtime
    state -- never committed", so on any fresh checkout the test skipped and
    the property went unverified. Generating one removes the dependency, runs
    everywhere, and cannot enshrine a wire format the system has stopped
    speaking.

    What it deliberately contains, beyond what the fixtures cover:

    * four symbols and four gateways interleaved, so episodes overlap rather
      than running one at a time;
    * market data between the business events, which every level below 3
      must report as *withheld* rather than drop;
    * envelope-less lines, which must come out as orphans and be counted.
    """
    base = 1_788_859_800_000
    lines: list[str] = []
    counter = 0

    def emit(offset_ms: int, topic: str, payload: dict[str, Any], **meta: str) -> str:
        nonlocal counter
        counter += 1
        when = base + offset_ms
        stamp = datetime.fromtimestamp(when / 1000, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
        msg = _ulid(when, counter)
        frame = f"seq={counter} msg={msg}"
        if "cause" in meta:
            frame += f" cause={meta['cause']}"
        frame += f" chain={meta.get('chain', meta.get('cause', msg))}"
        lines.append(f"[{stamp}] [{topic}] [{frame}] {json.dumps(payload)}")
        return msg

    for index, gateway in enumerate(TRADERS):
        emit(
            index,
            f"system.gateway_auth.{gateway}",
            {"gateway_id": gateway, "accepted": True, "description": "", "reason": ""},
        )

    for round_no in range(SESSION_ROUNDS):
        at = 10 + round_no * 5
        symbol = SYMBOLS[round_no % len(SYMBOLS)]
        buyer = TRADERS[round_no % len(TRADERS)]
        seller = TRADERS[(round_no + 1) % len(TRADERS)]
        buy_id = f"{round_no:028x}bbbb"
        sell_id = f"{round_no:028x}ssss"
        price_ticks = 7500 + round_no % 50
        price = price_ticks / 100

        submitted = emit(
            at,
            "order.new",
            {
                "id": buy_id,
                "symbol": symbol,
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "quantity": 100,
                "remaining_qty": 100,
                "gateway_id": buyer,
                "tick_decimals": 2,
                "ts_ns": (base + at) * 1_000_000,
                "status": "NEW",
                "price_ticks": price_ticks,
                "arrival_seq": round_no,
            },
        )
        emit(
            at + 1,
            f"order.ack.{buyer}",
            {
                "gateway_id": buyer,
                "order_id": buy_id,
                "accepted": True,
                "reason": "",
                "symbol": symbol,
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": price,
            },
            cause=submitted,
            chain=submitted,
        )
        if round_no % 3 == 0:
            # Market data between the business events: withheld, never dropped.
            emit(
                at + 2,
                f"book.{symbol}",
                {
                    "symbol": symbol,
                    "tick_decimals": 2,
                    "ts_ns": (base + at) * 1_000_000,
                    "bids": [{"price": price, "qty": 100, "count": 1}],
                    "asks": [],
                    "last_price": price,
                },
            )
        if round_no % 4 == 3:
            # No envelope at all: must be reported as an orphan and counted.
            # No envelope, and a kind no episode rule claims: must come out
            # as an orphan and be counted. Market data would not do -- it is
            # withheld before it is ever offered an episode, so a session
            # whose only unattached lines were book snapshots would never
            # exercise the third verdict at all.
            counter += 1
            stamp = datetime.fromtimestamp(
                (base + at + 3) / 1000, tz=timezone.utc
            ).isoformat(timespec="milliseconds")
            lines.append(
                f"[{stamp}] [book.snapshot_request] " + json.dumps({"symbol": symbol})
            )
            continue
        trade_id = f"000001-{round_no:09d}"
        printed = emit(
            at + 3,
            "trade.executed",
            {
                "id": trade_id,
                "run_seq": 1,
                "symbol": symbol,
                "buy_order_id": buy_id,
                "sell_order_id": sell_id,
                "buy_gateway_id": buyer,
                "sell_gateway_id": seller,
                "price": price,
                "quantity": 100,
                "aggressor_side": "BUY",
                "ts_ns": (base + at) * 1_000_000,
                "tick_decimals": 2,
            },
            cause=submitted,
            chain=submitted,
        )
        emit(
            at + 4,
            f"order.fill.{buyer}",
            {
                "gateway_id": buyer,
                "order_id": buy_id,
                "fill_qty": 100,
                "fill_price": price,
                "remaining_qty": 0,
                "status": "FILLED",
                "symbol": symbol,
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": price,
                "trade_ids": [trade_id],
                "liquidity_flag": "TAKER",
            },
            cause=printed,
            chain=submitted,
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def generated_session(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_session(tmp_path_factory.mktemp("session") / "audit.log")


def reconstruct_log(log: Path) -> tuple[list[Episode], StateModel]:
    run, steps = reconstruct(iter_entries([log]))
    return list(assemble(steps, run.state, run.links)), run.state


def audit_events(log: Path) -> list[AuditEntry]:
    """What ``pm-audit-cli`` would return for this window."""
    return list(iter_entries([log]))


def account_for(log: Path, level: int) -> dict[tuple[str | None, int], str]:
    """Where every event of *log* ended up, keyed by its line.

    Returns one of ``narrated``, ``withheld`` or ``orphan`` per event, or
    raises if an event reached none of them -- which is the failure this whole
    module exists to catch.

    At level 0 almost everything reads as ``withheld``, and that is accurate
    rather than a quirk: level 0 narrates *episodes*, so no individual fact
    produces a line of its own. The property being asserted there is still the
    one that matters -- every event is accounted for, none has vanished -- but
    the interesting narrated/withheld split lives at level 1 and above.
    """
    episodes, state = reconstruct_log(log)
    renderer = Renderer(episodes, state, Options(level=level))
    verdicts: dict[tuple[str | None, int], str] = {}
    for episode in episodes:
        for event in episode.events:
            where = (event.fact.file, event.fact.line_no)
            assert where not in verdicts, f"{where} landed in two episodes"
            if suppressed(event.fact, max(level, templates.LEVEL_DEFAULT)):
                verdicts[where] = "withheld"
            elif episode.kind == KIND_ORPHAN:
                verdicts[where] = "orphan"
            else:
                rendered = renderer.line(episode, event)
                verdicts[where] = "narrated" if rendered is not None else "withheld"
    return verdicts


class TestNothingVanishes:
    @pytest.mark.parametrize("log", LOGS, ids=lambda p: p.stem[:2])
    @pytest.mark.parametrize("level", LEVELS)
    def test_every_event_is_narrated_withheld_or_an_orphan(
        self, log: Path, level: int
    ) -> None:
        events = audit_events(log)
        verdicts = account_for(log, level)
        for entry in events:
            where = (entry.file, entry.line_no)
            assert where in verdicts, (
                f"{log.name}:{entry.line_no} [{entry.topic}] reached no episode "
                f"at all -- it was neither narrated, withheld nor reported"
            )
            assert verdicts[where] in ("narrated", "withheld", "orphan")

    @pytest.mark.parametrize("log", LOGS, ids=lambda p: p.stem[:2])
    def test_the_accounting_covers_every_line_exactly_once(self, log: Path) -> None:
        events = audit_events(log)
        verdicts = account_for(log, 1)
        assert len(verdicts) == len(events)

    @pytest.mark.parametrize("level", LEVELS)
    def test_the_property_holds_over_a_whole_session(
        self, level: int, generated_session: Path
    ) -> None:
        """AR-4.5 asks for a full session, not only hand-written fixtures.

        This used to read a capture under ``deployment/docker/data/``, which
        is gitignored as runtime state -- so it skipped on every fresh
        checkout and the property was never actually verified anywhere but
        the machine that happened to have run the container.
        """
        events = audit_events(generated_session)
        assert len(events) > 1000, "the generated session is too small to mean much"
        verdicts = account_for(generated_session, level)
        missing = [
            f"{e.line_no} [{e.topic}]"
            for e in events
            if (e.file, e.line_no) not in verdicts
        ]
        assert not missing, f"vanished: {missing}"

    def test_the_session_exercises_all_three_verdicts(
        self, generated_session: Path
    ) -> None:
        """Otherwise the test above could pass by narrating everything.

        A session with no withheld market data and no orphans would verify
        only the easy third of the property.
        """
        assert set(account_for(generated_session, 1).values()) == {
            "narrated",
            "withheld",
            "orphan",
        }


class TestWithheldIsAStatementNotAnAbsence:
    def test_a_withheld_kind_can_be_asked_about(self) -> None:
        """The distinction the property rests on.

        "Not shown at this level" has to be something the tool will say, or a
        reader cannot tell it apart from "not there".
        """
        book = next(
            event.fact
            for episode, _state in [reconstruct_log(LOGS[0])]
            for e in episode
            for event in e.events
            if event.fact.kind == "book"
        )

        assert suppressed(book, 1) is True
        assert suppressed(book, 3) is False

    def test_raising_the_level_only_ever_reveals(self) -> None:
        for log in LOGS:
            narrated = [
                sum(
                    1
                    for verdict in account_for(log, level).values()
                    if verdict == "narrated"
                )
                for level in LEVELS
            ]
            assert narrated[1] <= narrated[2], log.name

    def test_everything_withheld_is_withheld_for_a_declared_reason(self) -> None:
        """Not a magic count: every withheld line names a kind the level table
        holds back, and nothing else is ever withheld."""
        log = FIXTURES / "01_simple_limit_partial_fill.log"
        by_line = {
            (entry.file, entry.line_no): entry.topic for entry in audit_events(log)
        }
        verdicts = account_for(log, 1)
        withheld = [by_line[where] for where, v in verdicts.items() if v == "withheld"]
        assert withheld, "fixture 01 carries market data; something should be held"
        for topic in withheld:
            kind, _, _rest = topic.partition(".")
            assert any(
                topic.startswith(held) or held.startswith(kind)
                for held in templates.MIN_LEVEL
            ), topic


class TestAnOrphanIsCounted:
    def test_an_unattachable_event_is_reported_not_swallowed(self) -> None:
        """Section 7.2: the tool's failure to explain something is
        information the reader needs."""
        episodes, _state = reconstruct_log(FIXTURES / "03_archived_no_envelope.log")
        orphans = [e for e in episodes if e.kind == KIND_ORPHAN]
        anomalies = [
            anomaly.code
            for episode in episodes
            for event in episode.events
            for anomaly in event.step.anomalies
        ]
        assert orphans or "ORPHAN_EVENT" in anomalies


class TestTheTopLevelWithholdsNothing:
    """AR-5.3's checkpoint: at ``-vvv`` the property becomes strict equality.

    Below level 4 the property is "narrated, withheld or orphan". At level 4
    there is no third state left: market data has arrived, the unclassified
    events have arrived, and every event in the file produces a line. That is
    the strongest form the property can take, and it is the one that proves
    the levels below it are withholding rather than losing.
    """

    @pytest.mark.parametrize("log", LOGS, ids=lambda p: p.stem[:2])
    def test_every_event_produces_a_line(self, log: Path) -> None:
        episodes, state = reconstruct_log(log)
        renderer = Renderer(episodes, state, Options(level=templates.LEVEL_RAW))
        lines = [
            (episode, event, renderer.line(episode, event))
            for episode in episodes
            for event in episode.events
        ]
        withheld = [
            f"{e.fact.file}:{e.fact.line_no} [{e.fact.topic}]"
            for _episode, e, rendered in lines
            if rendered is None
        ]

        assert withheld == [], f"{log.name}: withheld at the top level"
        assert len(lines) == len(audit_events(log))

    def test_it_holds_over_a_whole_session(self, generated_session: Path) -> None:
        episodes, state = reconstruct_log(generated_session)
        renderer = Renderer(episodes, state, Options(level=templates.LEVEL_RAW))
        narrated = sum(
            1
            for episode in episodes
            for event in episode.events
            if renderer.line(episode, event) is not None
        )

        assert narrated == len(audit_events(generated_session))

    def test_and_does_not_hold_one_level_down(self) -> None:
        """Otherwise the test above would prove nothing about the levels it is
        contrasted with: a tool that narrated everything at every level would
        pass it."""
        log = FIXTURES / "01_simple_limit_partial_fill.log"
        verdicts = account_for(log, templates.LEVEL_DEFAULT)

        assert "withheld" in verdicts.values()
