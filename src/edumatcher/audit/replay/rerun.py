"""Re-execute an audit trail's commands through a fresh engine.

The engine echoes every inbound command into the audit before it acts on it
(``Engine._echo_command``; queries and heartbeats excepted), so the audit is
also the engine's complete input. One pass rebuilds an ``Engine`` from the
run's compiled config (``system.startup`` carries it), seeds it as at startup,
feeds it each echoed command in audit order, and compares what it publishes
with what the live engine published for that command (its ``chain``):

- Hidden inputs: every state-changing message the live engine published
  belongs to a command, to startup, or to a timer the audit names. The
  timers are the engine's own, which no command carries:

  * a circuit breaker's reopen or ACE extension is one chain ending in
    ``circuit_breaker.resume/extend.<SYM>`` (``BREAKER_TIMER``);
  * a gateway that stopped sending heartbeats is one chain opening with
    ``system.gateway_bye.<GW>`` whose reason is ``heartbeat_timeout``
    (``HEARTBEAT_TIMER``).

  Both are reproduced by firing the timer and compared like a command.
  Anything else the live engine published with no command behind it came
  from an input the audit does not hold; the re-run cannot reproduce it.
- Outputs: the outputs agree, message for message. Engine-generated ids
  (quote, OCO and seed legs) and trade ids are bound live <-> re-run at first
  sight. A difference is non-determinism, a hidden input, or a behaviour
  change in the engine since the run (the result names both versions):
  re-run with the run's engine version for a determinism verdict.
- Final book: the re-run's resting book at the end is the live engine's
  persisted book (``gtc_orders.json``), when that file is there.

After a first difference a symbol's two books differ, and every later
command on it may differ too. Differences are counted per *episode*, which
ends when the re-run's book and last price equal the next live
``book.<SYM>`` snapshot (armed stops are not in a snapshot, so an episode
can end early and recur).

The engine is driven through the handlers its receive loop calls, minus the
sockets, with its clock and persistence files patched (``unittest.mock``).
Only an audit that reaches back to the engine's start, holds one engine run,
and carries its config can be re-run; otherwise :class:`Unavailable` says why.
"""

# The re-run drives the engine the way its receive loop does, minus the
# sockets -- through the handlers the loop itself calls.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest import mock

from edumatcher.audit.rawlines import (
    STARTUP,
    Unavailable,
    audit_files,
    iso_ns,
    lines,
    run_config_text,
    startup_message,
)
import edumatcher.engine.main as engine_main
import edumatcher.models.clock as models_clock
from edumatcher.cli_version import source_commit
from edumatcher.config_artifact import decode as decode_artifact
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.models.clock import reset_clock_for_tests
from edumatcher.models.generated.auction import (
    PREFIX_AUCTION_INDICATIVE,
    PREFIX_AUCTION_RESULT,
)
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT, PREFIX_DEPTH
from edumatcher.models.generated.circuit_breaker import (
    PREFIX_CIRCUIT_BREAKER_EXTEND,
    PREFIX_CIRCUIT_BREAKER_RESUME,
)
from edumatcher.models.generated.order import (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_FILL,
)
from edumatcher.models.generated.quote import PREFIX_QUOTE_ACK, PREFIX_QUOTE_STATUS
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.structure import PREFIX_OCO_ACK
from edumatcher.models.generated.system import (
    PREFIX_GATEWAY_BYE,
    TOPIC_GATEWAY_HEARTBEAT,
    TOPIC_STARTUP,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.message import decode
from edumatcher.models.trade import (
    current_run_seq,
    reset_trade_ids_for_tests,
    set_run_seq,
)

Sample = dict[str, object]

#: No generated constant names a whole family, only its topics; these are
#: derived from one of its topics rather than spelled as literals.
_SYSTEM_FAMILY = TOPIC_STARTUP.partition(".")[0] + "."
_OCO_FAMILY = PREFIX_OCO_ACK.partition(".")[0] + "."

#: Output topics left out of the comparison: market data and replies.
_SKIP = (
    PREFIX_BOOK_SNAPSHOT,
    PREFIX_DEPTH,
    PREFIX_AUCTION_INDICATIVE,
    _SYSTEM_FAMILY,
)
#: Messages that change or report order state; outside a command they mean
#: a hidden input (E1).
_STATE = (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_FILL,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    TOPIC_TRADE_EXECUTED,
    PREFIX_QUOTE_ACK,
    PREFIX_QUOTE_STATUS,
    _OCO_FAMILY,
    PREFIX_AUCTION_RESULT,
    TOPIC_SESSION_STATE,
)
#: Clock readings, never equal between runs.
_TIME_KEYS = frozenset({"ts_ns", "ts", "removed_at_ns", "resume_at_ns"})
#: The pseudo-command for a circuit breaker's timer firing on one symbol.
BREAKER_TIMER = "circuit_breaker.timer"
_TIMER_ENDS = (PREFIX_CIRCUIT_BREAKER_RESUME, PREFIX_CIRCUIT_BREAKER_EXTEND)
#: The pseudo-command for the engine disconnecting a gateway that stopped
#: sending heartbeats (``Engine._expire_silent_gateways``).
HEARTBEAT_TIMER = "gateway.heartbeat_timeout"
_HEARTBEAT_REASON = "heartbeat_timeout"
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


class LiveClock:
    """Stands in for ``time`` in :mod:`edumatcher.models.clock`, the source
    of the engine's timestamps (``now_ns``), so a re-run engine reads the
    live engine's clock. The circuit breaker's reference window holds the
    last minutes' trades by these readings; on the re-run's own clock the
    run's hours pass in minutes, the window holds other trades, and halts
    differ (2026-10-29 run: 24 halts).

    It reads the engine's start, then each input's first live trade time
    (``follow``). Audit line times are the audit's receive times and may pass
    the engine's next trade; between trades the engine decides nothing by
    the clock (a breaker reopens by its timer input, BREAKER_TIMER)."""

    def __init__(self, ns: int) -> None:
        self.ns = ns

    def time_ns(self) -> int:
        return self.ns

    def follow(self, live: Live) -> None:
        """Move to the time the live engine traded at for the input that
        published *live*, if it traded."""
        for topic, p in live:
            if topic == TOPIC_TRADE_EXECUTED:
                self.ns = int(p["ts_ns"])
                return


@contextmanager
def live_clock(files: list[Path]) -> Generator[LiveClock]:
    """Within it every engine reads a LiveClock, set to the engine's start
    (the audit's first line)."""
    first = next(lines(files), None)
    clock = LiveClock(iso_ns(first.ts) if first is not None else 0)
    reset_clock_for_tests()
    with mock.patch.object(models_clock, "time", clock):
        yield clock


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
        if rerun[i][0].startswith(PREFIX_ORDER_CANCELLED) and j - i > 1:
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


@dataclass(frozen=True)
class Step:
    """One input the re-run has just fed the engine, for an observer.

    ``rerun`` is what the fresh engine published for it, ``live`` what the live
    engine did; ``engine`` is the fresh engine *after* the input, so an observer
    reads the book the live engine had at that moment.  ``ids`` binds the
    re-run's engine-made ids to the live ones, ``diverged`` says whether the two
    engines are known to disagree on a symbol (an observer's reading of that
    symbol is then the re-run's, not necessarily the live engine's).
    """

    ts: str
    topic: str
    payload: dict[str, Any]
    rerun: list[tuple[str, dict[str, Any]]]
    live: list[tuple[str, dict[str, Any]]]
    engine: engine_main.Engine
    ids: _Ids
    diverged: frozenset[str]


class Rerun:
    """One pass of the audit's commands through a fresh engine."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.counts: Counter[str] = Counter()
        self.samples: dict[str, list[Sample]] = {"E1": [], "E2": [], "E4": []}
        self.commands: Counter[str] = Counter()
        self.diverged: dict[str, int] = {}  # symbol → commands in the episode
        self.consequences = 0
        self.reordered = 0
        self.kinds: Counter[str] = Counter()  # episodes by first difference
        self.ids = _Ids()
        #: Called after every input with a :class:`Step` (the queue view).
        self.observers: list[Callable[[Step], None]] = []
        #: The audit time of the input being handled.
        self.ts = ""
        #: Whether the persisted book was there to compare with.
        self.book_checked = False

    def note(self) -> str:
        """The versions and episode tallies that qualify an outputs verdict."""
        run_version, rerun_version = self.versions
        note = (
            f"run made with {run_version}, re-run with {rerun_version}; "
            f"{self.consequences} later commands on a diverged symbol not counted; "
            f"{len(self.diverged)} symbols still diverged at the end; "
            f"{self.reordered} cancel batches in another order (X11)"
        )
        if self.kinds:
            note += "; episodes by first difference: " + ", ".join(
                f"{k} {n}" for k, n in self.kinds.most_common(5)
            )
        return note

    def flag(self, cid: str, **sample: object) -> None:
        self.counts[cid] += 1
        if len(self.samples[cid]) < _KEEP:
            self.samples[cid].append(sample)

    def run(self) -> None:
        files = audit_files(self.data_dir)
        if not files:
            raise Unavailable("no audit trail in the data dir")
        compiled = decode_artifact(run_config_text(files))
        self.versions = (compiled.meta.compiler_version, _engine_version())
        reset_trade_ids_for_tests()
        # The engine's run sequence persists across starts and prefixes every
        # trade id: the run being re-run began at the number it announced.
        set_run_seq(int(str(startup_message(files).get("run_seq", 1))))
        sink = _Sink()
        with live_clock(files) as clock:
            with tempfile.TemporaryDirectory() as empty:
                self.engine = fresh_engine(compiled.engine, sink, Path(empty))
            for topic, chain, payload, live, ts in inputs(files):
                self.ts = ts
                if topic == "startup":
                    self.step("startup", "", {}, sink.take(), live)
                    continue
                if topic is None:
                    for t, body in live:
                        if t.startswith(_STATE):
                            self.flag("E1", topic=t, chain=chain, body=json.dumps(body)[:200])  # fmt: skip
                    continue
                if topic.startswith(PREFIX_BOOK_SNAPSHOT):
                    self.snapshot(payload)
                    continue
                clock.follow(live)
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
        if self.observers:
            seen = Step(
                self.ts,
                topic,
                payload,
                rerun,
                live,
                self.engine,
                self.ids,
                frozenset(self.diverged),
            )
            for observer in self.observers:
                observer(seen)
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
        path = self.data_dir / "gtc_orders.json"
        self.book_checked = path.is_file()
        if not self.book_checked:
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
    unit: tuple[str, Live, str, dict[str, Any] | None] | None = None

    def unit_input(unit: tuple[str, Live, str, dict[str, Any] | None]) -> Input:
        chain, msgs, ts, silent = unit
        if silent is not None:
            return HEARTBEAT_TIMER, chain, silent, msgs, ts
        end = msgs[-1][0]
        if end.startswith(_TIMER_ENDS):
            return BREAKER_TIMER, chain, {"symbol": end.rsplit(".", 1)[1]}, msgs, ts
        return None, chain, {}, msgs, ts

    for ln in lines(files):
        if first:
            first = False
            if ln.topic != STARTUP:
                raise Unavailable(
                    "the audit does not reach back to the engine's start "
                    f"(first line: {ln.topic}); its input is incomplete"
                )
            continue
        if ln.topic == STARTUP:
            raise Unavailable("the engine restarted during the run")
        if ln.topic in commands and startup is not None:
            yield "startup", "", {}, startup, ln.ts
            startup = None
        if ln.topic in commands or ln.topic.startswith(PREFIX_BOOK_SNAPSHOT):
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
        if (
            ln.topic.startswith(PREFIX_GATEWAY_BYE)
            and startup is None
            and (command is None or ln.chain != command[1])
        ):
            body = json.loads(ln.body)
            if body.get("reason") == _HEARTBEAT_REASON:
                # The engine disconnecting a silent gateway: its bye and the
                # cancels that follow are one unit, with no command behind it.
                if command is not None:
                    yield command[0], command[1], command[2], live, command[3]
                    command = None
                if unit is not None:
                    yield unit_input(unit)
                unit = (
                    ln.chain,
                    [],
                    ln.ts,
                    {"gateway_id": body["gateway_id"], "reason": _HEARTBEAT_REASON},
                )
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
            unit = (ln.chain, [], ln.ts, None)
        unit[1].append((ln.topic, json.loads(ln.body)))
    if startup is not None:
        yield "startup", "", {}, startup, ""
    if command is not None:
        yield command[0], command[1], command[2], live, command[3]
    if unit is not None:
        yield unit_input(unit)


def apply(engine: engine_main.Engine, topic: str, payload: dict[str, Any]) -> None:
    """Feed *engine* one input: a command, or a breaker timer firing."""
    if topic == HEARTBEAT_TIMER:
        engine._handle_gateway_disconnect(payload)
        return
    if topic != BREAKER_TIMER:
        engine._dispatch_pull_message(topic, payload)
        return
    cb = engine._circuit_breakers.get(payload["symbol"])
    if cb is not None and cb.halted:
        # Due now, and only this one: on the live clock another breaker may
        # be due as well, and the live engine fired each as its own input.
        others = [(b, b.resume_at_ns) for b in engine._circuit_breakers.values() if b is not cb]  # fmt: skip
        for b, _ in others:
            b.resume_at_ns = None
        cb.resume_at_ns = 0  # the engine decides: reopen or extend
        engine._flush_circuit_breakers()
        for b, at in others:
            b.resume_at_ns = at


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


def rerun(data_dir: Path) -> Rerun:
    """Re-run the audit trail in *data_dir* (``audit.log`` and ``audit/``)."""
    r = Rerun(data_dir)
    r.run()
    return r
