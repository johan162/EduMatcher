"""The Audit GUI's read routes: ``/api/v1/audit`` (ADMIN only).

Evidence collections are configured on the server and named by id; a client
pins one as a snapshot and reads everything through that snapshot, so pages,
stories and findings never drift onto later evidence (design §7.2). Nothing
here writes to the audit trail or accepts a path.

The work is :mod:`edumatcher.audit.service.session`'s, on a worker thread.
Failures are never empty successes: an unknown id is 404, missing or changed
evidence 503 (``AUDIT_SOURCE_UNAVAILABLE``), and an analysis the evidence
cannot support 409 (``CAPABILITY_UNAVAILABLE``), each with a stable
``reason``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any, Literal, NoReturn, TypeVar

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.responses import (
    AuditCollections,
    AuditEventPage,
    AuditFindingPage,
    AuditHeatmap,
    AuditLifelines,
    AuditSnapshot,
    AuditSnapshotRequest,
    AuditStory,
)
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.api_gateway.sessions import Session, auth, require_admin
from edumatcher.audit.service.capabilities import Capability, Reason
from edumatcher.audit.service.findings import BEHAVIOUR, LANES
from edumatcher.audit.service.market import MAX_BINS
from edumatcher.audit.service.session import (
    AmbiguousRun,
    AuditService,
    CapabilityUnavailable,
    EmptyWindow,
    EventFilter,
    SnapshotUnavailable,
    UnknownCollection,
    UnknownEntity,
    require_behaviour_lane,
)
from edumatcher.audit.service.snapshot import SnapshotDescriptor
from edumatcher.audit.replay.views import at_least

router = APIRouter(prefix="/api/v1/audit", tags=["audit"], route_class=ContractRoute)

_T = TypeVar("_T")

#: Page sizes (design §8.1).
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000

_SnapshotId = Annotated[
    str,
    Query(
        min_length=1,
        max_length=64,
        description="The snapshot every read is pinned to (`POST /audit/snapshots`).",
    ),
]
_Limit = Annotated[
    int,
    Query(ge=1, le=_MAX_LIMIT, description=f"Rows per page (1-{_MAX_LIMIT})."),
]
_After = Annotated[
    str | None,
    Query(
        max_length=200,
        description="The previous page's `next_cursor`, with the same snapshot "
        "and filters.",
    ),
]
_Symbol = Annotated[
    str | None,
    Query(min_length=1, max_length=64, description="Records of this symbol."),
]
_MarketSymbol = Annotated[
    str, Path(min_length=1, max_length=64, description="The symbol.")
]
_From = Annotated[
    int | None,
    Query(
        alias="from",
        ge=0,
        description="Window start, epoch nanoseconds on the receipt clock "
        "(default: the snapshot's first record).",
    ),
]
_To = Annotated[
    int | None,
    Query(
        ge=0,
        description="Window end, exclusive (default: just after the snapshot's "
        "last record).",
    ),
]


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _service(request: Request) -> AuditService:
    service: AuditService = request.app.state.audit
    return service


def _error(code: int, body: dict[str, Any]) -> HTTPException:
    return HTTPException(status_code=code, detail={"error": body})


def _snapshot_error(exc: SnapshotUnavailable) -> HTTPException:
    if exc.reason is Reason.UNKNOWN_SNAPSHOT:
        return _error(404, {"code": "UNKNOWN_SNAPSHOT", "message": str(exc)})
    return _error(
        503,
        {
            "code": "AUDIT_SOURCE_UNAVAILABLE",
            "message": str(exc),
            "reason": exc.reason.value,
        },
    )


def _capability_error(exc: CapabilityUnavailable) -> HTTPException:
    return _error(
        409,
        {
            "code": "CAPABILITY_UNAVAILABLE",
            "message": str(exc),
            "reason": exc.reason.value,
        },
    )


async def _in_snapshot(work: Callable[[], _T]) -> _T:
    """*work*, which reads a snapshot's records, on a worker thread: an
    unknown snapshot is 404, missing or changed evidence 503."""
    try:
        return await asyncio.to_thread(work)
    except SnapshotUnavailable as exc:
        raise _snapshot_error(exc) from exc


async def _analysing(work: Callable[[], _T]) -> _T:
    """:func:`_in_snapshot`, for an analysis the evidence may not support:
    409 with the capability's reason."""
    try:
        return await _in_snapshot(work)
    except CapabilityUnavailable as exc:
        raise _capability_error(exc) from exc


def _invalid(field: str, message: str) -> NoReturn:
    raise _error(
        status.HTTP_400_BAD_REQUEST,
        {"code": "VALIDATION", "message": message, "field": field},
    )


def _encode_cursor(snapshot_id: str, digest: str, position: int) -> str:
    raw = json.dumps([snapshot_id, digest, position]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, snapshot_id: str, digest: str) -> int:
    """The position *cursor* continues from; ``400`` when it was issued for
    another snapshot or other filters, or is not a cursor at all."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        sid, dig, position = json.loads(raw)
    except binascii.Error, UnicodeDecodeError, ValueError, TypeError:
        _invalid("after", "Invalid cursor; pass back `next_cursor`")
    if sid != snapshot_id or dig != digest or not isinstance(position, int):
        _invalid("after", "This cursor belongs to another snapshot or other filters")
    if position < 0:
        _invalid("after", "Invalid cursor; pass back `next_cursor`")
    return position


def _snapshot_body(d: SnapshotDescriptor) -> dict[str, Any]:
    return {
        "snapshot_id": d.snapshot_id,
        "collection_id": d.collection_id,
        "created_at": d.created_at,
        "entries": d.entries,
        "first_ts": d.first_ts,
        "last_ts": d.last_ts,
        "files": [{**asdict(f), "torn_bytes": f.torn_bytes} for f in d.files],
        "runs": [asdict(r) for r in d.runs],
        "capabilities": {
            cap.value: {
                "available": s.available,
                "reason": s.reason.value if s.reason else None,
                "detail": s.detail,
            }
            for cap, s in d.capabilities.items()
        },
        "manifest": asdict(d.manifest),
        "symbols": [asdict(s) for s in d.symbols],
        "days": [asdict(day) for day in d.days],
        "forensics": (
            {
                **asdict(d.forensics),
                "inputs_match": d.forensics.inputs_match,
            }
            if d.forensics
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/collections",
    response_model=AuditCollections,
    summary="Audit evidence collections",
    responses=docs.merge(
        docs.ok(docs.AUDIT_COLLECTIONS, "The configured collections, by id."),
        docs.errors(*docs.TRADING_KEY, "ROLE_DENIED"),
    ),
)
async def audit_collections(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """The evidence collections this gateway is configured to read, by id.

    Paths stay on the server: a client names a collection by its id.
    `available` is false, with `reason`, when its directory cannot be read.
    """
    await require_admin(request, session)
    service = _service(request)

    def work() -> list[dict[str, Any]]:
        rows = []
        for collection in service.collections.values():
            available, reason, files = service.availability(collection)
            rows.append(
                {
                    "id": collection.id,
                    "available": available,
                    "reason": reason.value if reason else None,
                    "files": files,
                }
            )
        return rows

    rows = await asyncio.to_thread(work)
    return {"collections": rows, "count": len(rows)}


@router.post(
    "/snapshots",
    response_model=AuditSnapshot,
    status_code=status.HTTP_201_CREATED,
    summary="Pin a collection as a snapshot",
    responses=docs.merge(
        docs.ok(docs.AUDIT_SNAPSHOT, "The snapshot's descriptor.", 201),
        docs.errors(
            *docs.TRADING_KEY,
            "ROLE_DENIED",
            "VALIDATION",
            "UNKNOWN_COLLECTION",
            "AUDIT_SOURCE_UNAVAILABLE",
        ),
    ),
)
async def create_audit_snapshot(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: Annotated[AuditSnapshotRequest, Body()],
) -> dict[str, Any]:
    """Pin a collection as it is now: every file's size and hash, the active
    file's complete lines, the runs and what the evidence can support.

    Pinning an unchanged collection again returns the same snapshot. R0 pins
    synchronously; a large trail takes seconds (about 90,000 records/s).
    """
    await require_admin(request, session)
    service = _service(request)
    try:
        descriptor = await asyncio.to_thread(service.create, body.collection_id)
    except UnknownCollection as exc:
        raise _error(404, {"code": "UNKNOWN_COLLECTION", "message": str(exc)}) from exc
    except SnapshotUnavailable as exc:
        raise _error(
            503,
            {
                "code": "AUDIT_SOURCE_UNAVAILABLE",
                "message": str(exc),
                "reason": exc.reason.value,
            },
        ) from exc
    return _snapshot_body(descriptor)


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=AuditSnapshot,
    summary="Snapshot descriptor and capabilities",
    responses=docs.merge(
        docs.ok(docs.AUDIT_SNAPSHOT, "The snapshot's descriptor."),
        docs.errors(*docs.TRADING_KEY, "ROLE_DENIED", "VALIDATION", "UNKNOWN_SNAPSHOT"),
    ),
)
async def audit_snapshot(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    snapshot_id: Annotated[
        str, Path(max_length=64, description="The snapshot, as `POST` returned it.")
    ],
) -> dict[str, Any]:
    """What a snapshot pinned (files, sizes, hashes, cutoffs, runs, extent)
    and, per analysis, whether its evidence supports it and why not."""
    await require_admin(request, session)
    service = _service(request)
    try:
        descriptor = await asyncio.to_thread(service.descriptor, snapshot_id)
    except SnapshotUnavailable as exc:
        raise _error(404, {"code": "UNKNOWN_SNAPSHOT", "message": str(exc)}) from exc
    return _snapshot_body(descriptor)


@router.get(
    "/events",
    response_model=AuditEventPage,
    summary="Audit records, canonically ordered",
    responses=docs.merge(
        docs.ok(docs.AUDIT_EVENTS, "One page of records, in canonical order."),
        docs.errors(
            *docs.TRADING_KEY,
            "ROLE_DENIED",
            "VALIDATION",
            "UNKNOWN_SNAPSHOT",
            "AUDIT_SOURCE_UNAVAILABLE",
        ),
    ),
)
async def audit_events(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    snapshot_id: _SnapshotId,
    topic: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=64,
            description="Topic prefix, e.g. `trade.executed`.",
        ),
    ] = None,
    symbol: _Symbol = None,
    gateway: Annotated[
        str | None,
        Query(min_length=1, max_length=32, description="Records of this gateway."),
    ] = None,
    order_id: Annotated[
        str | None,
        Query(min_length=1, max_length=64, description="Records naming this order."),
    ] = None,
    limit: _Limit = _DEFAULT_LIMIT,
    after: _After = None,
) -> dict[str, Any]:
    """The snapshot's records in canonical order (engine run, then its
    sequence), each with both clocks' raw values, every price with its
    recorded scale, and the file and line it was read from.

    Nanosecond times are decimal strings. Paging is by `next_cursor`, which
    is valid only for the same snapshot and filters.
    """
    await require_admin(request, session)
    service = _service(request)
    flt = EventFilter(topic, symbol, gateway, order_id)
    start = _decode_cursor(after, snapshot_id, flt.digest()) if after else 0

    def work() -> tuple[list[dict[str, Any]], int | None]:
        return service.session(snapshot_id).events(flt, start, limit)

    rows, resume = await _in_snapshot(work)
    return {
        "snapshot_id": snapshot_id,
        "events": rows,
        "count": len(rows),
        "has_more": resume is not None,
        "next_cursor": (
            _encode_cursor(snapshot_id, flt.digest(), resume)
            if resume is not None
            else None
        ),
    }


@router.get(
    "/stories/{entity_kind}/{entity_id}",
    response_model=AuditStory,
    summary="An entity's story",
    responses=docs.merge(
        docs.ok(docs.AUDIT_STORY, "The episodes, beats, links and findings."),
        docs.errors(
            *docs.TRADING_KEY,
            "ROLE_DENIED",
            "VALIDATION",
            "UNKNOWN_SNAPSHOT",
            "UNKNOWN_ENTITY",
            "AMBIGUOUS_RUN",
            "CAPABILITY_UNAVAILABLE",
            "AUDIT_SOURCE_UNAVAILABLE",
        ),
    ),
)
async def audit_story(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    entity_kind: Annotated[
        Literal["order", "trade", "quote", "oco", "combo", "command"],
        Path(description="What the id names."),
    ],
    entity_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=64,
            description="Order, trade, quote, OCO or combo id, or command id; "
            "an unambiguous prefix is accepted.",
        ),
    ],
    snapshot_id: _SnapshotId,
    run_id: Annotated[
        int | None,
        Query(
            ge=0,
            description="The engine run (`run` of `/events`), when the id "
            "appears in several.",
        ),
    ] = None,
    depth: Annotated[
        int, Query(ge=0, le=3, description="Links to follow from the entity (0-3).")
    ] = 2,
) -> dict[str, Any]:
    """pm-audit-replay's story of one order, trade, quote, OCO, combo or
    command: its episodes and those within `depth` links, each fact narrated,
    each link with its confidence (`RECORDED` ... `HEURISTIC`), and the
    findings on them in their lanes.

    A story never crosses into another engine run: an id a restart reused is
    `409 AMBIGUOUS_RUN` until `run_id` names one.
    """
    await require_admin(request, session)
    service = _service(request)

    def work() -> dict[str, list[dict[str, Any]]]:
        return service.session(snapshot_id).story(entity_kind, entity_id, run_id, depth)

    try:
        story = await _analysing(work)
    except UnknownEntity as exc:
        raise _error(404, {"code": "UNKNOWN_ENTITY", "message": str(exc)}) from exc
    except AmbiguousRun as exc:
        raise _error(
            409, {"code": "AMBIGUOUS_RUN", "message": str(exc), "runs": exc.runs}
        ) from exc
    return {
        "snapshot_id": snapshot_id,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "run_id": run_id,
        "depth": depth,
        **story,
    }


@router.get(
    "/findings",
    response_model=AuditFindingPage,
    summary="Findings by lane",
    responses=docs.merge(
        docs.ok(docs.AUDIT_FINDINGS, "One page of findings, worst first."),
        docs.errors(
            *docs.TRADING_KEY,
            "ROLE_DENIED",
            "VALIDATION",
            "UNKNOWN_SNAPSHOT",
            "CAPABILITY_UNAVAILABLE",
            "AUDIT_SOURCE_UNAVAILABLE",
        ),
    ),
)
async def audit_findings(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    snapshot_id: _SnapshotId,
    lane: Annotated[
        Literal["evidence", "consistency", "operations", "behaviour"] | None,
        Query(description="Only this lane."),
    ] = None,
    severity: Annotated[
        Literal["info", "warn", "error"],
        Query(description="At this severity or worse."),
    ] = "info",
    code: Annotated[
        str | None, Query(min_length=1, max_length=64, description="Only this code.")
    ] = None,
    limit: _Limit = _DEFAULT_LIMIT,
    after: _After = None,
) -> dict[str, Any]:
    """The replay's findings in separate lanes (design §4.1): `evidence`
    (the trail is incomplete here), `consistency` (recorded facts break an
    exchange invariant), `operations` (participants, configuration,
    infrastructure). The `behaviour` lane is R2's and is reported as not
    available, never as empty. Codes and severities are the replay's own;
    window-edge findings keep their `info` severity.

    An attached `pm-sim-forensics` report whose audit inputs match the
    snapshot adds its FAIL (`error`), ERROR (`warn`) and SKIPPED (`info`)
    checks to the consistency lane as `code: SIM_FORENSICS` rows with the
    check, its samples and data scope; PASS and INFO are only counted in
    `forensics.statuses`. A report on other inputs is not merged
    (`forensics.reason: DIFFERENT_INPUTS`).
    """
    await require_admin(request, session)
    service = _service(request)
    digest = json.dumps([lane, severity, code])
    start = _decode_cursor(after, snapshot_id, digest) if after else 0

    def work() -> (
        tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]
    ):
        if lane == BEHAVIOUR:
            require_behaviour_lane()
        replay = service.session(snapshot_id)
        everything = replay.findings()
        attached = replay.descriptor.capabilities[Capability.FORENSICS]
        report = replay.descriptor.forensics
        summary = {
            "available": attached.available,
            "reason": attached.reason.value if attached.reason else None,
            "detail": attached.detail,
            "statuses": report.statuses if report else None,
        }
        lanes: dict[str, dict[str, Any]] = {
            name: {"available": True, "reason": None, "count": 0}
            for name in LANES
            if name != BEHAVIOUR
        }
        lanes[BEHAVIOUR] = {
            "available": False,
            "reason": Reason.NOT_IN_RELEASE.value,
            "count": None,
        }
        floor = at_least(severity)
        chosen = []
        for row in everything:
            lanes[row["lane"]]["count"] += 1
            if (
                (lane is None or row["lane"] == lane)
                and (code is None or row["code"] == code)
                and at_least(row["severity"]) <= floor
            ):
                chosen.append(row)
        return chosen, lanes, summary

    chosen, lanes, summary = await _analysing(work)
    page = chosen[start : start + limit]
    more = start + limit < len(chosen)
    return {
        "snapshot_id": snapshot_id,
        "lanes": lanes,
        "forensics": summary,
        "findings": page,
        "count": len(page),
        "has_more": more,
        "next_cursor": (
            _encode_cursor(snapshot_id, digest, start + limit) if more else None
        ),
    }


def _unknown_symbol(exc: UnknownEntity) -> HTTPException:
    return _error(404, {"code": "UNKNOWN_ENTITY", "message": str(exc)})


@router.get(
    "/market/{symbol}/heatmap",
    response_model=AuditHeatmap,
    summary="Depth heatmap",
    responses=docs.merge(
        docs.ok(docs.AUDIT_HEATMAP, "Displayed depth per price level and time bin."),
        docs.errors(
            *docs.TRADING_KEY,
            "ROLE_DENIED",
            "VALIDATION",
            "UNKNOWN_SNAPSHOT",
            "UNKNOWN_ENTITY",
            "CAPABILITY_UNAVAILABLE",
            "AUDIT_SOURCE_UNAVAILABLE",
        ),
    ),
)
async def audit_heatmap(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: _MarketSymbol,
    snapshot_id: _SnapshotId,
    start: _From = None,
    to: _To = None,
    bins: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_BINS,
            description=f"Time bins wanted (1-{MAX_BINS}); never finer than the "
            "median observation interval.",
        ),
    ] = 300,
) -> dict[str, Any]:
    """Displayed quantity per price level (integer ticks) and time bin, from
    the recorded `book.<symbol>` observations only.

    An observation is valid until the next one, a phase change, an uncross
    of the symbol, lost records or the end of its engine run, and is never
    interpolated. A cell
    weights each observation by the time it covered in the bin. `masks`
    marks lost records (`gap`: no cells) and halts (`halt`: the observed
    book keeps its cells). `cadence` is measured over the whole snapshot.
    `phases` starts from the engine's STARTUP checkpoint. Times are on the
    receipt clock.
    """
    await require_admin(request, session)
    service = _service(request)

    def work() -> dict[str, Any]:
        return service.session(snapshot_id).heatmap(symbol, start, to, bins)

    try:
        body = await _analysing(work)
    except UnknownEntity as exc:
        raise _unknown_symbol(exc) from exc
    except EmptyWindow as exc:
        _invalid("to", str(exc))
    return {"snapshot_id": snapshot_id, "symbol": symbol, **body}


@router.get(
    "/market/{symbol}/lifelines",
    response_model=AuditLifelines,
    summary="Order lifelines",
    responses=docs.merge(
        docs.ok(docs.AUDIT_LIFELINES, "Each order's life on the book, in segments."),
        docs.errors(
            *docs.TRADING_KEY,
            "ROLE_DENIED",
            "VALIDATION",
            "UNKNOWN_SNAPSHOT",
            "UNKNOWN_ENTITY",
            "AUDIT_SOURCE_UNAVAILABLE",
        ),
    ),
)
async def audit_lifelines(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: _MarketSymbol,
    snapshot_id: _SnapshotId,
    start: _From = None,
    to: _To = None,
    gateway: Annotated[
        str | None,
        Query(min_length=1, max_length=32, description="Only this gateway's orders."),
    ] = None,
) -> dict[str, Any]:
    """Every order and quote leg of the symbol, per engine run, from its
    admission to its end (`filled`, `cancel.owner`, `cancel.system` with
    the engine's reason, `expired`, `open`, or `censored` where the window
    ends first), clipped to the window.

    Each segment is one price, displayed quantity and state; an amendment,
    fill, iceberg refill or stop trigger starts a new one. Over
    `segment_cap` segments the response holds per-level aggregates instead
    (`aggregated: true`). Times are on the receipt clock.
    """
    await require_admin(request, session)
    service = _service(request)

    def work() -> dict[str, Any]:
        return service.session(snapshot_id).lifelines(symbol, start, to, gateway)

    try:
        body = await _in_snapshot(work)
    except UnknownEntity as exc:
        raise _unknown_symbol(exc) from exc
    except EmptyWindow as exc:
        _invalid("to", str(exc))
    return {"snapshot_id": snapshot_id, "symbol": symbol, **body}
