"""E — the run's commands, re-run through a fresh engine.

The engine echoes every inbound command into the audit before it acts on it
(``Engine._echo_command``; queries and heartbeats excepted), so the audit is
also the engine's complete input. One pass rebuilds an ``Engine`` from the
run's compiled config, seeds it as at startup, feeds it each echoed command
in audit order, and compares what it publishes with what the live engine
published for that command (its ``chain``):

- E1: every state-changing message the live engine published belongs to a
  command (or to startup). One that does not came from an input the audit
  does not hold -- a silent-gateway expiry, a timer -- and the re-run cannot
  reproduce it. The one timer the audit does name is the circuit breaker's:
  its reopen or ACE extension is one chain (S28) ending in
  ``circuit_breaker.resume/extend.<SYM>``, which the re-run reproduces by
  firing that symbol's timer (``BREAKER_TIMER``) and compares like a command.
- E2: the outputs agree, message for message. Engine-generated ids (quote,
  OCO and seed legs) and trade ids are bound live ↔ re-run at first sight. A
  difference is non-determinism, a hidden input, or a behaviour change in
  the engine since the run (the report names both versions): re-run with
  the run's engine version for a determinism verdict.
- E4: the re-run's resting book at the end is the live engine's persisted
  book (``gtc_orders.json``).

After a first difference a symbol's two books differ, and every later
command on it may differ too. E2 counts each such *episode* once, and ends
it when the re-run's book and last price equal the next live
``book.<SYM>`` snapshot (armed stops are not in a snapshot, so an episode
can end early and recur).
"""

# The re-run drives the engine the way its receive loop does, minus the
# sockets -- through the handlers the loop itself calls.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, tzinfo
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest import mock

from sim_forensics.audit import STARTUP, audit_files, lines, run_config_text
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

import edumatcher.engine.main as engine_main
from edumatcher.cli_version import source_commit
from edumatcher.config_artifact import decode as decode_artifact
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.models.generated.system import TOPIC_GATEWAY_HEARTBEAT
from edumatcher.models.message import decode
from edumatcher.models.trade import (
    current_run_seq,
    reset_trade_ids_for_tests,
    set_run_seq,
)

#: Output topics left out of the comparison: market data and replies.
_SKIP = ("book.", "depth.", "auction.indicative.", "system.", "diagnostic")
#: Messages that change or report order state; outside a command they mean
#: a hidden input (E1).
_STATE = (
    "order.ack.",
    "order.fill.",
    "order.cancelled.",
    "order.expired.",
    "trade.executed",
    "quote.ack.",
    "quote.status.",
    "oco.",
    "auction.result.",
    "session.state",
)
#: Clock readings, never equal between runs.
_TIME_KEYS = frozenset({"ts_ns", "ts", "removed_at_ns", "resume_at_ns"})
#: The pseudo-command for a circuit breaker's timer firing on one symbol.
BREAKER_TIMER = "circuit_breaker.timer"
_TIMER_ENDS = ("circuit_breaker.resume.", "circuit_breaker.extend.")
_ORDER_ID = re.compile(r"^[0-9a-f]{32}$")
_TRADE_ID = re.compile(r"^\d{6}-\d{9}$")
#: An order id's 8-character prefix, as messages quote it in reason text.
_ID_PREFIX = re.compile(r"\b[0-9a-f]{8}\b")
_KEEP = 50


class _Sink:
    """Stands in for the engine's PUB socket (and PULL: never read)."""

    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def send_with_envelope(self, frames: list[bytes], envelope: bytes) -> None:
        pass

    def set_cause(self, envelope: object | None) -> None:
        pass

    def clear_cause(self) -> None:
        pass

    def begin_unit(self) -> None:
        pass

    def end_unit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def take(self) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for frames in self.sent:
            topic, payload = decode(frames)
            if not topic.startswith(_SKIP):
                out.append((topic, payload))
        self.sent.clear()
        return out


class _Ids:
    """Live ↔ re-run identities, bound where both runs first name one."""

    def __init__(self) -> None:
        self.to_live: dict[str, str] = {}
        self.to_rerun: dict[str, str] = {}
        self.prefix: dict[str, str] = {}

    def same(self, rerun: str, live: str) -> bool:
        if rerun == live and rerun not in self.to_live:
            return True
        bound = self.to_live.get(rerun)
        if bound is not None:
            return bound == live
        if live in self.to_rerun:
            return False
        self.to_live[rerun], self.to_rerun[live] = live, rerun
        self.prefix[rerun[:8]] = live[:8]
        return True

    def text(self, rerun: str) -> str:
        return _ID_PREFIX.sub(lambda m: self.prefix.get(m.group(), m.group()), rerun)

    def inbound(self, obj: Any) -> Any:
        """A live command, in the re-run's ids."""
        if isinstance(obj, dict):
            return {k: self.inbound(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.inbound(v) for v in obj]
        if isinstance(obj, str):
            return self.to_rerun.get(obj, obj)
        return obj


def _diff(ids: _Ids, rerun: Any, live: Any, path: str) -> list[str]:
    if isinstance(rerun, dict) and isinstance(live, dict):
        out: list[str] = []
        for key in sorted(set(rerun) | set(live)):
            if key in _TIME_KEYS:
                continue
            if key not in live or key not in rerun:
                only = "re-run" if key not in live else "live"
                out.append(f"{path}.{key} only in the {only}")
                continue
            out += _diff(ids, rerun[key], live[key], f"{path}.{key}")
        return out
    if isinstance(rerun, list) and isinstance(live, list):
        if len(rerun) != len(live):
            return [f"{path}: {len(rerun)} items, live {len(live)}"]
        return [
            d
            for i, (a, b) in enumerate(zip(rerun, live))
            for d in _diff(ids, a, b, f"{path}[{i}]")
        ]
    if isinstance(rerun, str) and isinstance(live, str):
        if (_ORDER_ID.match(rerun) and _ORDER_ID.match(live)) or (
            _TRADE_ID.match(rerun) and _TRADE_ID.match(live)
        ):
            return [] if ids.same(rerun, live) else [f"{path}: {rerun} is not {live}"]
        return [] if ids.text(rerun) == live else [f"{path}: {rerun!r} != {live!r}"]
    if rerun != live:
        return [f"{path}: {rerun!r} != {live!r}"]
    return []


def _compare(
    ids: _Ids,
    rerun: list[tuple[str, dict[str, Any]]],
    live: list[tuple[str, dict[str, Any]]],
) -> tuple[list[str], bool]:
    """Differences between the two output lists, and whether a batch of
    cancels came in another order (X11: not a difference)."""
    if [t for t, _ in rerun] != [t for t, _ in live]:
        return [
            f"topics: re-run {[t for t, _ in rerun]}, live {[t for t, _ in live]}"
        ], False
    reordered = False
    # A run of order.cancelled for one gateway follows set iteration order.
    i = 0
    while i < len(rerun):
        j = i
        while j < len(rerun) and rerun[j][0] == rerun[i][0]:
            j += 1
        if rerun[i][0].startswith("order.cancelled.") and j - i > 1:
            aligned = _align(ids, rerun[i:j], live[i:j])
            if aligned is not None:
                reordered |= aligned != rerun[i:j]
                rerun[i:j] = aligned
        i = j
    out = [d for (t, a), (_, b) in zip(rerun, live) for d in _diff(ids, a, b, t)]
    return out, reordered


def _align(
    ids: _Ids,
    rerun: list[tuple[str, dict[str, Any]]],
    live: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]] | None:
    """*rerun* in *live*'s order: each already-bound order id at the place
    live has it, the unbound ones in the remaining places as they came.
    None when a bound id is not in *live* (a real difference)."""
    where = {str(p.get("order_id")): k for k, (_, p) in enumerate(live)}
    out: list[tuple[str, dict[str, Any]] | None] = [None] * len(live)
    unbound = []
    for msg in rerun:
        oid = str(msg[1].get("order_id"))
        if oid in ids.to_live:
            k = where.get(ids.to_live[oid])
            if k is None or out[k] is not None:
                return None
            out[k] = msg
        else:
            unbound.append(msg)
    free = iter(unbound)
    return [m if m is not None else next(free) for m in out]


def _kind(diff: str) -> str:
    """A difference without its values, gateway or list positions."""
    if diff.startswith("topics:"):
        return "different messages"
    kind = re.sub(r"\[\d+\]", "[]", diff.split(":", 1)[0])
    return re.sub(r"^([a-z_.]+?)\.[A-Z][A-Z0-9-]*\.", r"\1.*.", kind)


def _symbols(*outputs: list[tuple[str, dict[str, Any]]]) -> set[str]:
    return {str(p["symbol"]) for out in outputs for _, p in out if p.get("symbol")}


class _Rerun:
    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.counts: Counter[str] = Counter()
        self.samples: dict[str, list[Sample]] = {"E1": [], "E2": [], "E4": []}
        self.commands: Counter[str] = Counter()
        self.diverged: dict[str, int] = {}  # symbol → commands in the episode
        self.consequences = 0
        self.reordered = 0
        self.kinds: Counter[str] = Counter()  # episodes by first difference
        self.ids = _Ids()

    def flag(self, cid: str, **sample: object) -> None:
        self.counts[cid] += 1
        if len(self.samples[cid]) < _KEEP:
            self.samples[cid].append(sample)

    def run(self) -> None:
        data = self.ds.data_dir
        files = audit_files(data)
        if not files:
            raise Skipped("no audit.log in the data dir")
        compiled = decode_artifact(run_config_text(files))
        self.versions = (compiled.meta.compiler_version, _engine_version())
        reset_trade_ids_for_tests()
        set_run_seq(1)
        sink = _Sink()
        with tempfile.TemporaryDirectory() as empty:
            self.engine = fresh_engine(compiled.engine, sink, Path(empty))
        for topic, chain, payload, live, _ts in inputs(files):
            if topic == "startup":
                self.step("startup", "", {}, sink.take(), live)
                continue
            if topic is None:
                for t, body in live:
                    if t.startswith(_STATE):
                        self.flag("E1", topic=t, chain=chain, body=json.dumps(body)[:200])  # fmt: skip
                continue
            if topic.startswith("book."):
                self.snapshot(payload)
                continue
            self.dispatch(sink, topic, chain, payload, live)
        self.final_book()

    def dispatch(
        self,
        sink: _Sink,
        topic: str,
        chain: str,
        payload: dict[str, Any],
        live: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.commands[topic] += 1
        apply(self.engine, topic, self.ids.inbound(payload))
        self.step(topic, chain, payload, sink.take(), live)

    def step(
        self,
        topic: str,
        chain: str,
        payload: dict[str, Any],
        rerun: list[tuple[str, dict[str, Any]]],
        live: list[tuple[str, dict[str, Any]]],
    ) -> None:
        diffs, reordered = _compare(self.ids, rerun, live)
        self.reordered += reordered
        if not diffs:
            return
        symbols = _symbols(rerun, live) or {str(payload.get("symbol", ""))}
        new = sorted(s for s in symbols if s not in self.diverged)
        for s in symbols:
            self.diverged[s] = self.diverged.get(s, 0) + 1
        if not new:
            self.consequences += 1
            return
        self.kinds[_kind(diffs[0])] += 1
        self.flag("E2", command=topic, chain=chain, symbols=new, diffs=diffs[:4])

    def snapshot(self, p: dict[str, Any]) -> None:
        sym = p["symbol"]
        if sym not in self.diverged:
            return
        book = self.engine.books.get(sym)
        if book is None:
            return
        # Armed stops are not in a snapshot: an episode can end while one
        # still differs, and then recur as a new episode.
        mine = book.snapshot()
        if all(mine[k] == p.get(k) for k in ("bids", "asks", "last_price")):
            del self.diverged[sym]

    def final_book(self) -> None:
        path = self.ds.data_dir / "gtc_orders.json"
        if not path.is_file():
            return
        persisted = {
            str(o["id"]): int(o.get("remaining_qty", 0))
            for o in json.loads(path.read_text())
        }
        resting = {
            self.ids.to_live.get(o.id, o.id): o.remaining_qty
            for book in self.engine.books.values()
            for o in book.resting_orders()
        }
        for oid in sorted(persisted.keys() | resting.keys()):
            if persisted.get(oid) != resting.get(oid):
                self.flag(
                    "E4",
                    order_id=oid,
                    persisted=persisted.get(oid),
                    rerun=resting.get(oid),
                )


Live = list[tuple[str, dict[str, Any]]]


Input = tuple[str | None, str, dict[str, Any], Live, str]


def inputs(files: list[Path]) -> Iterator[Input]:
    """The engine's inputs in the audit, in order, each with what the live
    engine published for it: (topic, chain, payload, outputs, audit time) per echoed
    command or breaker timer (BREAKER_TIMER, payload {"symbol"}); first
    ("startup", "", {}, what startup published); a ``book.<SYM>`` snapshot
    as (topic, "", snapshot, []); and messages no input explains as
    (None, chain, {}, those messages)."""
    commands = _command_topics()
    first = True
    startup: Live | None = []
    command: tuple[str, str, dict[str, Any], str] | None = None
    live: Live = []
    unit: tuple[str, Live, str] | None = None

    def unit_input(unit: tuple[str, Live, str]) -> Input:
        chain, msgs, ts = unit
        end = msgs[-1][0]
        if end.startswith(_TIMER_ENDS):
            return BREAKER_TIMER, chain, {"symbol": end.rsplit(".", 1)[1]}, msgs, ts
        return None, chain, {}, msgs, ts

    for ln in lines(files):
        if first:
            first = False
            if ln.topic != STARTUP:
                raise Skipped(
                    "the audit does not reach back to the engine's start "
                    f"(first line: {ln.topic}); its input is incomplete"
                )
            continue
        if ln.topic == STARTUP:
            raise Skipped("the engine restarted during the run")
        if ln.topic in commands and startup is not None:
            yield "startup", "", {}, startup, ln.ts
            startup = None
        if ln.topic in commands or ln.topic.startswith("book."):
            if command is not None:
                yield command[0], command[1], command[2], live, command[3]
                command = None
            if unit is not None:
                yield unit_input(unit)
                unit = None
            if ln.topic in commands:
                command, live = (ln.topic, ln.chain, json.loads(ln.body), ln.ts), []
            else:
                yield ln.topic, "", json.loads(ln.body), [], ln.ts
            continue
        if ln.topic.startswith(_SKIP):
            continue
        if startup is not None:
            startup.append((ln.topic, json.loads(ln.body)))
            continue
        if command is not None and ln.chain == command[1]:
            live.append((ln.topic, json.loads(ln.body)))
            continue
        # Outside the current command: what it published is complete (the
        # engine finishes one input before the next), and a new unit begins.
        if command is not None:
            yield command[0], command[1], command[2], live, command[3]
            command = None
        if unit is not None and unit[0] != ln.chain:
            yield unit_input(unit)
            unit = None
        if unit is None:
            unit = (ln.chain, [], ln.ts)
        unit[1].append((ln.topic, json.loads(ln.body)))
    if startup is not None:
        yield "startup", "", {}, startup, ""
    if command is not None:
        yield command[0], command[1], command[2], live, command[3]
    if unit is not None:
        yield unit_input(unit)


def apply(engine: engine_main.Engine, topic: str, payload: dict[str, Any]) -> None:
    """Feed *engine* one input: a command, or a breaker timer firing."""
    if topic != BREAKER_TIMER:
        engine._dispatch_pull_message(topic, payload)
        return
    cb = engine._circuit_breakers.get(payload["symbol"])
    if cb is not None and cb.halted:
        cb.resume_at_ns = 0  # due now; the engine decides: reopen or extend
        engine._flush_circuit_breakers()


def fresh_engine(
    config: EngineConfig, sink: _Sink, state_dir: Path, today: date | None = None
) -> engine_main.Engine:
    """An engine started as ``Engine.run`` starts one (``Engine._startup``)
    on *config*, publishing into *sink*, restoring from the persistence files
    in *state_dir* (none there: an empty book). *today* stands in for the
    wall-clock date the restore judges DAY orders by."""

    class _Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "_Clock":
            moment = datetime.now(tz)
            return cls.combine(today or moment.date(), moment.timetz())

    with (
        mock.patch.object(engine_main, "_deployed_config", lambda: (config, "")),
        mock.patch.object(engine_main, "make_puller", lambda _: _Sink()),
        mock.patch.object(engine_main, "make_publisher", lambda _: sink),
        mock.patch.object(engine_main, "GTC_ORDERS_FILE", state_dir / "gtc_orders.json"),  # fmt: skip
        mock.patch.object(engine_main, "GTC_COMBOS_FILE", state_dir / "gtc_combos.json"),  # fmt: skip
        mock.patch.object(engine_main, "BOOK_STATS_FILE", state_dir / "book_stats.json"),  # fmt: skip
        mock.patch.object(engine_main, "datetime", _Clock),
    ):
        engine = engine_main.Engine(config_path=None)
        engine._startup(current_run_seq() or 0)
    return engine


def _engine_version() -> str:
    """The re-running engine's version, and its source commit if it runs
    from a git checkout (the package version stays put between releases)."""
    commit = source_commit()
    return (
        version("edumatcher")
        if commit == "unknown"
        else f"{version('edumatcher')} ({commit})"
    )


def _command_topics() -> frozenset[str]:
    """What ``Engine._dispatch_pull_message`` routes and ``_echo_command``
    records: every TOPIC_* but queries and heartbeats."""
    return frozenset(
        v
        for k, v in vars(engine_main).items()
        if k.startswith("TOPIC_")
        and isinstance(v, str)
        and not v.endswith(engine_main.Engine._QUERY_SUFFIX)
        and v != TOPIC_GATEWAY_HEARTBEAT
    )


def _rerun(ds: Dataset) -> _Rerun:
    cached = ds.cache.get("rerun")
    if isinstance(cached, Skipped):
        raise cached
    if isinstance(cached, _Rerun):
        return cached
    r = _Rerun(ds)
    try:
        r.run()
    except Skipped as exc:
        ds.cache["rerun"] = exc
        raise
    ds.cache["rerun"] = r
    return r


@check(
    "E1",
    "replay",
    "Every state change the engine published answers a command in the audit",
    needs=(),
)
def hidden_inputs(ds: Dataset) -> Outcome:
    r = _rerun(ds)
    total = sum(r.commands.values())
    top = ", ".join(f"{t} {n}" for t, n in r.commands.most_common(6))
    return Outcome(r.counts["E1"], r.samples["E1"], f"{total} commands ({top}, …)")


@check(
    "E2",
    "replay",
    "A fresh engine fed the audit's commands publishes what the live engine did",
    needs=(),
)
def same_outputs(ds: Dataset) -> Outcome:
    r = _rerun(ds)
    run_version, rerun_version = r.versions
    note = (
        f"run made with {run_version}, re-run with {rerun_version}; "
        f"{r.consequences} later commands on a diverged symbol not counted; "
        f"{len(r.diverged)} symbols still diverged at the end; "
        f"{r.reordered} cancel batches in another order (X11)"
    )
    if r.kinds:
        note += "; episodes by first difference: " + ", ".join(
            f"{k} {n}" for k, n in r.kinds.most_common(5)
        )
    return Outcome(r.counts["E2"], r.samples["E2"], note)


@check(
    "E4",
    "replay",
    "The re-run's final resting book is the engine's persisted book",
    needs=(),
)
def final_book(ds: Dataset) -> Outcome:
    r = _rerun(ds)
    return Outcome(r.counts["E4"], r.samples["E4"])
