"""Event -> Fact: units, clocks and topics resolved (design sections 4, 5.3).

A Fact is an audit line with its ambiguities removed and **nothing added**.
Three ambiguities, each a live trap in the current schema:

*Ticks versus display money.* ``order.new.price_ticks`` is in engine ticks
while ``order.ack.price`` and ``trade.executed.price`` are display money. A
narrator that printed a tick price verbatim would report a buy limit at
7 569.00 for a stock trading at 75.69, and the reader would believe it. Two
things stop that. The field name says the unit, so the two can no longer be
confused by eye; and every message carrying a tick price carries the
``tick_decimals`` those ticks are at, so converting is a dict lookup rather
than a search. Which fields are tick-scaled is read from the generated spec
registry, so a new one cannot be missed.

*Three clocks.* The bracketed prefix is ``pm-audit``'s receipt clock;
``order.new.timestamp`` is the **client's** and is explicitly not what the book
uses for priority; ``trade.executed.ts_ns`` is the engine's. Normalising the
unit does not make them comparable, so they are kept apart and never merged
into one column.

*Topic wildcards.* ``order.ack.TRADER01`` is the ``order.ack`` message with an
actor, and resolving that is a spec lookup, not string surgery --
:func:`edumatcher.audit.query.split_topic`, shared with ``pm-audit-cli``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from edumatcher.audit.query import (
    AuditEntry,
    lookup_topic,
    parse_ts,
    split_topic,
)
from edumatcher.audit.replay.anomalies import (
    SEVERITY_WARN,
    TICK_SCALE_UNKNOWN,
    UNKNOWN_TOPIC,
    Anomaly,
)
from edumatcher.models.generated.order import TOPIC_ORDER_NEW

#: Clocks a Fact can carry. Kept as separate labels rather than one normalised
#: column precisely because normalising the *unit* does not make two clocks
#: comparable (design section 5.3.2).
CLOCK_ENGINE = "engine"
CLOCK_CLIENT = "client"

#: The one field in the whole spec that is a client's clock reading. Everything
#: else with an epoch unit is stamped by a process inside the exchange.
#: ``order.new.timestamp``'s own doc says it is not what the book uses for
#: priority -- ``arrival_seq`` is.
_CLIENT_CLOCK_FIELDS = frozenset({(TOPIC_ORDER_NEW, "ts_ns")})

_NANOS = "epoch_nanos"
_SECONDS = "epoch_seconds"
_TICKS = "ticks"
_DISPLAY = "display_price"

#: Provenance strings for a resolved price, shown by ``--show-units``.
_ALREADY_DISPLAY = "already display money"
_FROM_MESSAGE = "the message's own tick_decimals"


@dataclass(frozen=True, slots=True)
class Price:
    """One price field, converted to display money or explicitly refused.

    ``display`` is None only when the scale could not be resolved. The raw
    value is kept either way, so a refusal can still be printed -- as ticks,
    labelled as ticks.
    """

    name: str
    raw: float
    display: float | None
    tick_decimals: int | None
    source: str

    @property
    def resolved(self) -> bool:
        return self.display is not None

    def render(self) -> str:
        """The value as it may be printed, never scaled without a source."""
        if self.display is None:
            return f"{self.raw:g} ticks"
        return f"{self.display:.{self.tick_decimals or 0}f}"

    def provenance(self) -> str:
        """The ``--show-units`` annotation: how this number came to be."""
        if self.display is None:
            return "ticks, scale unknown"
        if self.source == _ALREADY_DISPLAY:
            return _ALREADY_DISPLAY
        return f"ticks->display, tick_decimals={self.tick_decimals}"


@dataclass(frozen=True, slots=True)
class FactTime:
    """One time field, normalised to an aware UTC datetime, clock named.

    A Fact's ``times`` says *what a field means*, not *when the event
    happened*: ``circuit_breaker.halt.resume_at_ns`` is a future time and
    ``index.history_request.from_ts_ns`` is a query bound. Both are epoch nanos
    and both normalise correctly; neither is the event's own clock reading.
    """

    name: str
    clock: str
    when: datetime


@dataclass(frozen=True, slots=True)
class Fact:
    """One normalised audit line."""

    #: Topic with the wildcard resolved: ``order.ack.TRADER01`` -> ``order.ack``.
    kind: str
    #: The wildcard's value, when the topic has one: a gateway id or a symbol.
    actor: str | None
    #: The topic exactly as recorded, for tracing back.
    topic: str
    #: ``pm-audit``'s receipt clock -- the only clock present on every line.
    receipt_ts: datetime
    #: The receipt timestamp as recorded, which is what the reader can grep for.
    receipt_raw: str
    symbol: str | None
    payload: Mapping[str, Any]
    prices: Mapping[str, Price]
    times: Mapping[str, FactTime]
    #: Envelope (design section 13). ``causation_id`` None on a fact that *has*
    #: an envelope is a declared origin, not a missing link -- keeping that
    #: distinction is what stops the tool inventing causes for scheduler ticks.
    msg_id: str | None
    causation_id: str | None
    correlation_id: str | None
    #: Per-topic sequence, dense, so a gap in it proves loss.
    topic_seq: int | None
    #: Position in the stream as read. The tie-break that makes the canonical
    #: sort total and stable (design section 5.2.2); ``line_no`` cannot serve,
    #: because it restarts at every rotated file.
    ordinal: int
    file: str | None
    line_no: int
    #: False when the topic has no entry in the generated registry.
    known: bool
    #: True when this fact arrived after its reorder window had closed and was
    #: therefore emitted where it landed rather than where it belongs. Set by
    #: the ordering pass; never true on a healthy log, so it is itself a
    #: finding (design section 5.2.3).
    late: bool = False
    anomalies: tuple[Anomaly, ...] = ()

    @property
    def has_envelope(self) -> bool:
        return self.msg_id is not None

    @property
    def source(self) -> str:
        """``audit.log:118423``, the ``--show-source`` annotation."""
        if not self.file:
            return ""
        return f"{Path(self.file).name}:{self.line_no}"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _to_utc(nanos_or_seconds: float, unit: str) -> datetime | None:
    seconds = (
        nanos_or_seconds / 1_000_000_000 if unit == _NANOS else float(nanos_or_seconds)
    )
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        # A corrupt or absurd epoch value. The tool is reached for *when* the
        # system is misbehaving, so this drops the field rather than the line.
        return None


def _resolve_prices(
    symbol: str | None,
    payload: Mapping[str, Any],
    spec_fields: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Price], list[str]]:
    """Convert every declared price to display money.

    The scale comes off the message itself. Every message carrying a tick
    price also carries the `tick_decimals` those ticks are at -- the same
    discipline `ts_ns` applies to time, and for the same reason: a number
    whose unit has to be fetched from somewhere else is a number that can be
    read wrong.

    It was not always so. This resolved the scale through a five-rung ladder
    ending in refusal, fed by a pre-pass over the whole log, because the only
    messages that declared a scale were `book`, `trade.executed` and the
    reference-data replies -- and in a *window* of the trail the snapshot that
    declared it is usually at session start, hours outside the window being
    read. The ladder, the pre-pass and the refusal are all gone; what is left
    is a dict lookup.
    """
    prices: dict[str, Price] = {}
    refused: list[str] = []
    declared = payload.get("tick_decimals")
    decimals = (
        declared
        if isinstance(declared, int) and not isinstance(declared, bool)
        else None
    )

    for spec in spec_fields:
        unit = spec.get("unit")
        if unit not in (_TICKS, _DISPLAY):
            continue
        name = str(spec["name"])
        raw = payload.get(name)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            continue
        if unit == _DISPLAY:
            prices[name] = Price(
                name=name,
                raw=float(raw),
                display=float(raw),
                tick_decimals=decimals,
                source=_ALREADY_DISPLAY,
            )
            continue
        if decimals is None:
            # The message declares a tick price and no scale for it. That is a
            # spec violation, not a gap to paper over: reported, and left in
            # ticks rather than guessed at.
            prices[name] = Price(
                name=name, raw=float(raw), display=None, tick_decimals=None, source=""
            )
            refused.append(name)
            continue
        prices[name] = Price(
            name=name,
            raw=float(raw),
            display=float(raw) / (10**decimals),
            tick_decimals=decimals,
            source=_FROM_MESSAGE,
        )
    return prices, refused


def _resolve_times(
    kind: str,
    payload: Mapping[str, Any],
    spec_fields: tuple[Mapping[str, Any], ...],
) -> dict[str, FactTime]:
    times: dict[str, FactTime] = {}
    for spec in spec_fields:
        unit = spec.get("unit")
        if unit not in (_NANOS, _SECONDS):
            continue
        name = str(spec["name"])
        raw = payload.get(name)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            continue
        when = _to_utc(raw, str(unit))
        if when is None:
            continue
        clock = CLOCK_CLIENT if (kind, name) in _CLIENT_CLOCK_FIELDS else CLOCK_ENGINE
        times[name] = FactTime(name=name, clock=clock, when=when)
    return times


def to_fact(entry: AuditEntry, ordinal: int) -> Fact:
    """Normalise one :class:`AuditEntry`.

    Never raises on a malformed payload: this tool is what someone reaches for
    when the system is already misbehaving, so anything it cannot make sense of
    becomes an anomaly on the Fact rather than a traceback.
    """
    kind, actor = split_topic(entry.topic)
    spec = lookup_topic(entry.topic)
    found = []
    if spec is None:
        found.append(
            Anomaly(
                code=UNKNOWN_TOPIC,
                severity=SEVERITY_WARN,
                detail=f"topic {entry.topic!r} is in no message family",
                receipt_ts=entry.timestamp,
                file=entry.file,
                line_no=entry.line_no,
            )
        )
        spec_fields: tuple[Mapping[str, Any], ...] = ()
    else:
        spec_fields = tuple(spec["fields"])

    payload = entry.payload
    symbol = entry.symbol
    if symbol is None and spec is not None and spec["params"] == ("symbol",):
        # `book.AAPL` and `depth.AAPL` name the symbol in the topic, and the
        # payload repeats it -- but a truncated payload need not.
        symbol = actor

    prices, refused = _resolve_prices(symbol, payload, spec_fields)
    if refused:
        found.append(
            Anomaly(
                code=TICK_SCALE_UNKNOWN,
                severity=SEVERITY_WARN,
                detail=(
                    f"{kind} carries tick prices but no tick_decimals; "
                    f"{', '.join(refused)} left in ticks"
                ),
                receipt_ts=entry.timestamp,
                file=entry.file,
                line_no=entry.line_no,
            )
        )

    try:
        receipt = parse_ts(entry.timestamp)
    except ValueError:
        # _LINE_RE matched, so there was something in the bracket; it just is
        # not a timestamp. Sorting has to put it somewhere, and the epoch is
        # the one choice that cannot be mistaken for a real reading.
        receipt = datetime.fromtimestamp(0, tz=timezone.utc)

    return Fact(
        kind=kind,
        actor=actor,
        topic=entry.topic,
        receipt_ts=receipt,
        receipt_raw=entry.timestamp,
        symbol=symbol,
        payload=payload,
        prices=prices,
        times=_resolve_times(kind, payload, spec_fields),
        msg_id=entry.msg_id,
        causation_id=entry.causation_id,
        correlation_id=entry.correlation_id,
        topic_seq=entry.seq,
        ordinal=ordinal,
        file=entry.file,
        line_no=entry.line_no,
        known=spec is not None,
        anomalies=tuple(found),
    )


def normalise(entries: Iterable[AuditEntry]) -> Iterator[Fact]:
    """Normalise a stream of entries, numbering them in read order."""
    for ordinal, entry in enumerate(entries):
        yield to_fact(entry, ordinal)
