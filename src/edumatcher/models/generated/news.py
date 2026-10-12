# GENERATED FROM spec/messages/news.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``news`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/news.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
../../../../docs/books/architecture-and-development/part-4-developing/040-message-
generation.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "news"
FAMILY_VERSION = 1


TOPIC_NEWS_EVENT = "news.event"
_TOPIC_NEWS_EVENT_BYTES = "news.event".encode()
_NEWS_EVENT_SCOPE_VALUES = ("SYMBOL", "SECTOR", "MARKET")
NewsEventScope = Literal["SYMBOL", "SECTOR", "MARKET"]
_NEWS_EVENT_KIND_VALUES = (
    "EARNINGS",
    "GUIDANCE",
    "MNA",
    "REGULATORY",
    "PRODUCT",
    "LEGAL",
    "MANAGEMENT",
    "MACRO",
)
NewsEventKind = Literal[
    "EARNINGS",
    "GUIDANCE",
    "MNA",
    "REGULATORY",
    "PRODUCT",
    "LEGAL",
    "MANAGEMENT",
    "MACRO",
]
_NEWS_EVENT_STATUS_VALUES = ("RUMOUR", "CONFIRMED", "RETRACTED")
NewsEventStatus = Literal["RUMOUR", "CONFIRMED", "RETRACTED"]


_NEWS_EVENT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "ts_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "",
    },
    {
        "name": "scope",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _NEWS_EVENT_SCOPE_VALUES,
    },
    {
        "name": "targets",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Symbols (SYMBOL) or sector names (SECTOR); empty for MARKET.",
    },
    {
        "name": "kind",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _NEWS_EVENT_KIND_VALUES,
    },
    {
        "name": "status",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _NEWS_EVENT_STATUS_VALUES,
    },
    {
        "name": "headline",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 200},
    },
    {
        "name": "sentiment",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "Tone of the news, -1 (bad) to 1 (good); not its size.",
        "constraints": {"ge": -1, "le": 1},
    },
    {
        "name": "credibility",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "How believable a rumour is; absent on confirmed news.",
        "constraints": {"ge": 0, "le": 1},
    },
    {
        "name": "related_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The rumour a CONFIRMED or RETRACTED event resolves.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """pm-market-sim to everyone: one headline, or a change in what an earlier one is
    known to be (a rumour confirmed or retracted).

    A rumour comes first with status RUMOUR and a credibility; when it resolves, a
    second event with a new id carries status CONFIRMED or RETRACTED and points back
    with `related_id`. A confirmation is when the value moves; a retraction moves
    nothing. Published on pm-market-sim's PUB socket; the API gateway relays it to every
    key and pm-ticker shows it.
    """

    id: str
    ts_ns: int  # unit: epoch_nanos
    scope: NewsEventScope
    targets: list[str]
    kind: NewsEventKind
    status: NewsEventStatus
    headline: str
    sentiment: float  # unit: dimensionless
    credibility: float | None = None  # unit: dimensionless
    related_id: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 32:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 32"
            )
        if self.scope not in _NEWS_EVENT_SCOPE_VALUES:
            raise MessageValidationError(
                f"scope: {self.scope!r} is not one of {_NEWS_EVENT_SCOPE_VALUES!r}"
            )
        if self.kind not in _NEWS_EVENT_KIND_VALUES:
            raise MessageValidationError(
                f"kind: {self.kind!r} is not one of {_NEWS_EVENT_KIND_VALUES!r}"
            )
        if self.status not in _NEWS_EVENT_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_NEWS_EVENT_STATUS_VALUES!r}"
            )
        if len(self.headline) > 200:
            raise MessageValidationError(
                f"headline: length {len(self.headline)} exceeds max_len 200"
            )
        if self.sentiment < -1:
            raise MessageValidationError(f"sentiment: {self.sentiment!r} must be >= -1")
        if self.sentiment > 1:
            raise MessageValidationError(f"sentiment: {self.sentiment!r} must be <= 1")
        if self.credibility is not None:
            if self.credibility < 0:
                raise MessageValidationError(
                    f"credibility: {self.credibility!r} must be >= 0"
                )
            if self.credibility > 1:
                raise MessageValidationError(
                    f"credibility: {self.credibility!r} must be <= 1"
                )
        if len(self.related_id) > 32:
            raise MessageValidationError(
                f"related_id: length {len(self.related_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "NewsEvent":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            ts_ns=int(p["ts_ns"]),
            scope=cast(NewsEventScope, str(p["scope"])),
            targets=[str(item) for item in p["targets"]],
            kind=cast(NewsEventKind, str(p["kind"])),
            status=cast(NewsEventStatus, str(p["status"])),
            headline=str(p["headline"]),
            sentiment=float(p["sentiment"]),
            credibility=(
                None if p.get("credibility") is None else float(p["credibility"])
            ),
            related_id=str(p.get("related_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "id": self.id,
            "ts_ns": self.ts_ns,
            "scope": self.scope,
            "targets": self.targets,
            "kind": self.kind,
            "status": self.status,
            "headline": self.headline,
            "sentiment": self.sentiment,
            "related_id": self.related_id,
        }
        if self.credibility is not None:
            payload["credibility"] = self.credibility
        return payload


def is_news_event(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_NEWS_EVENT


def make_news_event(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = NewsEvent.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_NEWS_EVENT, obj.to_dict())


def make_news_event_unchecked(
    *,
    id: str,
    ts_ns: int,
    scope: NewsEventScope,
    targets: list[str],
    kind: NewsEventKind,
    status: NewsEventStatus,
    headline: str,
    sentiment: float,
    credibility: float | None = None,
    related_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_news_event``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "id": str(id),
        "ts_ns": int(ts_ns),
        "scope": str(scope),
        "targets": [str(item) for item in targets],
        "kind": str(kind),
        "status": str(status),
        "headline": str(headline),
        "sentiment": float(sentiment),
        "related_id": str(related_id),
    }
    if credibility is not None:
        payload["credibility"] = float(credibility)
    return [
        _TOPIC_NEWS_EVENT_BYTES,
        _msg.dumps(payload),
    ]


def parse_news_event(frames: list[bytes]) -> "NewsEvent":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = NewsEvent.from_dict(payload)
    obj.validate()
    return obj


def describe_news_event() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _NEWS_EVENT_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (TOPIC_NEWS_EVENT,)
