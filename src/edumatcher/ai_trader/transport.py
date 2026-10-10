"""Order entry for the agents: one ALF session per agent through pm-alf-gwy.

A transport sends actions for many agents and turns their order lifecycle
lines into ``AgentEvent`` records. Market data never goes through it: the
worker reads that from the engine PUB feed itself, so every session logs on
with ``FEED=ORDERS`` and the gateway does not copy it every trade print.

The gateway converts display money to ticks, keeps each participant's
engine session alive (heartbeats) and disconnects it when the TCP session
ends, which applies the participant's ``disconnect_behaviour``.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Protocol

from edumatcher.ai_trader.actions import Action, CancelOrder, NewOco, NewOrder
from edumatcher.alf_client import protocol as alf
from edumatcher.alf_client.connection import AlfConnection, State

log = logging.getLogger(__name__)

#: request_tag prefix on cancels, so a refused cancel is told from a refused order.
CANCEL_RTAG_PREFIX = "CXL-"
CLIENT_NAME = "pm-ai-swarm"
RECONNECT_MIN = 1.0
RECONNECT_MAX = 10.0


@dataclass(frozen=True)
class AckEvent:
    order_id: str | None
    tag: str | None
    accepted: bool
    code: str | None
    reason: str
    request_tag: str | None


@dataclass(frozen=True)
class FillEvent:
    order_id: str | None
    tag: str | None
    symbol: str
    side: str
    fill_qty: int
    fill_price: float  # display money
    remaining: int | None


@dataclass(frozen=True)
class DoneEvent:
    order_id: str | None
    tag: str | None


@dataclass(frozen=True)
class OcoAckEvent:
    oco_tag: str
    accepted: bool
    leg_ids: tuple[str, str]
    reason: str


@dataclass(frozen=True)
class PositionsEvent:
    positions: dict[str, tuple[int, float]]  # symbol -> (net qty, avg cost display)


@dataclass(frozen=True)
class SessionEvent:
    """The agent's session came back after a loss: its open orders are gone
    (or untracked) and its position must be re-read."""

    up: bool


AgentEvent = (
    AckEvent | FillEvent | DoneEvent | OcoAckEvent | PositionsEvent | SessionEvent
)


class Transport(Protocol):
    def connect(self, gateway_ids: list[str], timeout: float) -> set[str]:
        """Log the participants on; return the ids that were accepted."""
        ...

    def send(self, gateway_id: str, action: Action, tick_decimals: int) -> bool: ...

    def request_positions(self, gateway_id: str) -> None: ...

    def heartbeat(self, gateway_ids: list[str]) -> None: ...

    def is_up(self, gateway_id: str) -> bool:
        """The participant's session is logged on and can take actions."""
        ...

    def fileno_map(self) -> dict[int, tuple[str, object]]:
        """File descriptors to wait on -> (participant id, connection).

        The connection tells a reconnect that got the same fd number back
        from one that did not; epoll silently drops a closed fd.
        """
        ...

    def poll_events(self, ready: list[str]) -> list[tuple[str, AgentEvent]]:
        """Events from the sessions of ``ready`` participants."""
        ...

    def maintain(self, now: float) -> list[tuple[str, AgentEvent]]:
        """Keep sessions alive and reconnect lost ones."""
        ...

    def disconnect(self, gateway_ids: list[str]) -> None: ...

    def close(self) -> None: ...


@dataclass
class _Session:
    conn: AlfConnection
    lost: bool = False
    retry_at: float = 0.0
    backoff: float = RECONNECT_MIN
    #: Multi-line POSITION reply being collected.
    positions: dict[str, tuple[int, float]] | None = None
    expected: int = 0


class AlfTransport:
    def __init__(self, host: str, port: int, seed: int = 0) -> None:
        self.host = host
        self.port = port
        self._sessions: dict[str, _Session] = {}
        self._rng = random.Random(seed)

    # --- lifecycle -----------------------------------------------------------
    def _open(self, gw: str, now: float) -> AlfConnection | None:
        conn = AlfConnection(
            self.host, self.port, gw, client=CLIENT_NAME, feed="ORDERS"
        )
        try:
            conn.open(now)
        except OSError as exc:
            log.warning(
                "[%s] cannot reach ALF gateway %s:%s: %s", gw, self.host, self.port, exc
            )
            return None
        return conn

    def connect(self, gateway_ids: list[str], timeout: float) -> set[str]:
        now = time.monotonic()
        pending: dict[str, AlfConnection] = {}
        for gw in gateway_ids:
            conn = self._open(gw, now)
            if conn is not None:
                pending[gw] = conn
        accepted: set[str] = set()
        deadline = time.monotonic() + timeout
        while pending and time.monotonic() < deadline:
            for gw, conn in list(pending.items()):
                conn.flush()
                for msg in conn.read():
                    if msg.msg_type == "ERR":
                        log.error(
                            "[%s] logon refused: %s %s",
                            gw,
                            msg.get("CODE"),
                            msg.get("DETAIL"),
                        )
                if conn.state == State.READY:
                    accepted.add(gw)
                    self._sessions[gw] = _Session(conn)
                    del pending[gw]
                elif not conn.is_open:
                    del pending[gw]
            time.sleep(0.01)
        for gw, conn in pending.items():
            log.error("[%s] no logon within %.0fs", gw, timeout)
            conn.close(say_bye=False)
        return accepted

    def disconnect(self, gateway_ids: list[str]) -> None:
        for gw in gateway_ids:
            s = self._sessions.get(gw)
            if s is not None:
                s.conn.close("client_exit")

    def close(self) -> None:
        self.disconnect(list(self._sessions))
        self._sessions.clear()

    def fileno_map(self) -> dict[int, tuple[str, object]]:
        return {
            s.conn.fileno(): (gw, s.conn)
            for gw, s in self._sessions.items()
            if s.conn.is_open
        }

    # --- outbound --------------------------------------------------------------
    def send(self, gateway_id: str, action: Action, tick_decimals: int) -> bool:
        s = self._sessions.get(gateway_id)
        if s is None or s.conn.state != State.READY:
            return False
        ok = s.conn.send(self._line(action, tick_decimals), time.monotonic())
        s.conn.flush()
        return ok

    def is_up(self, gateway_id: str) -> bool:
        s = self._sessions.get(gateway_id)
        return s is not None and s.conn.state == State.READY

    def request_positions(self, gateway_id: str) -> None:
        s = self._sessions.get(gateway_id)
        if s is not None and s.conn.state == State.READY:
            s.conn.send(alf.position_request(gateway_id), time.monotonic())
            s.conn.flush()

    def heartbeat(self, gateway_ids: list[str]) -> None:
        """The gateway heartbeats the engine for us; PINGs keep TCP alive."""
        now = time.monotonic()
        for gw in gateway_ids:
            s = self._sessions.get(gw)
            if s is not None:
                s.conn.tick(now)

    @staticmethod
    def _line(action: Action, decimals: int) -> bytes:
        if isinstance(action, NewOrder):
            return alf.new_order(
                tag=action.tag,
                symbol=action.symbol,
                side=action.side,
                order_type=action.order_type.value,
                tif=action.tif.value,
                qty=action.qty,
                tick_decimals=decimals,
                price_ticks=action.price_ticks,
                stop_price_ticks=action.stop_price_ticks,
                trail_offset_ticks=action.trail_offset_ticks,
                visible_qty=action.visible_qty,
            )
        if isinstance(action, CancelOrder):
            return alf.cancel(action.order_id, CANCEL_RTAG_PREFIX + action.tag)
        if isinstance(action, NewOco):
            legs = tuple(
                {
                    "side": leg.side,
                    "order_type": leg.order_type.value,
                    "price_ticks": leg.price_ticks,
                    "stop_price_ticks": leg.stop_price_ticks,
                }
                for leg in (action.leg1, action.leg2)
            )
            return alf.new_oco(
                oco_id=action.tag,
                symbol=action.symbol,
                qty=action.qty,
                tif=action.tif.value,
                tick_decimals=decimals,
                legs=(legs[0], legs[1]),
            )
        return alf.cancel_oco(action.tag)

    # --- inbound -----------------------------------------------------------------
    def poll_events(self, ready: list[str]) -> list[tuple[str, AgentEvent]]:
        out: list[tuple[str, AgentEvent]] = []
        for gw in ready:
            s = self._sessions.get(gw)
            if s is None:
                continue
            for msg in s.conn.read():
                event = self._to_event(s, msg)
                if event is not None:
                    out.append((gw, event))
        return out

    def maintain(self, now: float) -> list[tuple[str, AgentEvent]]:
        """Flush, notice lost sessions, reconnect them with jittered backoff."""
        out: list[tuple[str, AgentEvent]] = []
        for gw, s in self._sessions.items():
            conn = s.conn
            if conn.is_open:
                conn.flush()
                if conn.state == State.READY and s.lost:
                    s.lost = False
                    s.backoff = RECONNECT_MIN
                    log.info("[%s] ALF session restored", gw)
                    out.append((gw, SessionEvent(up=True)))
                continue
            if not s.lost:
                s.lost = True
                s.retry_at = now
                log.warning(
                    "[%s] ALF session lost (%s)", gw, conn.close_reason or "closed"
                )
            if now < s.retry_at:
                continue
            new = self._open(gw, now)
            s.backoff = min(RECONNECT_MAX, s.backoff * 2)
            # Jitter spreads a swarm's reconnects; the cap holds the promise
            # that a session is retried at least every RECONNECT_MAX seconds.
            s.retry_at = now + min(
                RECONNECT_MAX, s.backoff * (0.5 + self._rng.random())
            )
            if new is not None:
                s.conn = new
        return out

    @staticmethod
    def _to_event(s: _Session, m: alf.AlfMessage) -> AgentEvent | None:
        t = m.msg_type
        if t == "ACK":
            return AckEvent(
                order_id=m.get("ORDER_ID") or None,
                tag=m.get("TAG") or None,
                accepted=m.flag("ACCEPTED"),
                code=m.get("REJECT_CODE") or None,
                reason=m.get("REASON"),
                request_tag=m.get("RTAG") or None,
            )
        if t == "FILL":
            try:
                qty = int(m.get("FILL_QTY"))
                price = float(m.get("FILL_PRICE"))
                remaining: int | None = int(m.get("REMAINING"))
            except ValueError:
                return None
            return FillEvent(
                order_id=m.get("ORDER_ID") or None,
                tag=m.get("TAG") or None,
                symbol=m.get("SYMBOL").upper(),
                side=m.get("SIDE").upper(),
                fill_qty=qty,
                fill_price=price,
                remaining=remaining,
            )
        if t in ("CANCELLED", "EXPIRED"):
            return DoneEvent(m.get("ORDER_ID") or None, m.get("TAG") or None)
        if t == "OCO_ACK":
            return OcoAckEvent(
                oco_tag=m.get("OCO_ID"),
                accepted=m.flag("ACCEPTED"),
                leg_ids=(m.get("LEG1_ID"), m.get("LEG2_ID")),
                reason=m.get("REASON"),
            )
        if t == "OCO_CANCELLED":
            return DoneEvent(m.get("CANCELLED_ID") or None, None)
        if t == "ERR":
            # A command the gateway refused before it reached the engine.
            tag = m.get("TAG") or None
            if tag is None:
                log.warning("ALF error: %s %s", m.get("CODE"), m.get("DETAIL"))
                return None
            is_cancel = tag.startswith(CANCEL_RTAG_PREFIX)
            return AckEvent(
                order_id=None,
                tag=None if is_cancel else tag,
                accepted=False,
                code=m.get("REJECT_CODE") or m.get("CODE") or None,
                reason=m.get("DETAIL"),
                request_tag=tag if is_cancel else None,
            )
        if t == "POSITION":
            s.positions = {}
            s.expected = int(m.get("COUNT") or 0)
            return None
        if t == "POS_ENTRY" and s.positions is not None:
            try:
                s.positions[m.get("SYM").upper()] = (
                    int(m.get("NET_QTY")),
                    float(m.get("AVG_COST") or 0.0),
                )
            except ValueError:
                pass
            return None
        if t == "END" and m.get("TYPE") == "POSITION" and s.positions is not None:
            positions, s.positions = s.positions, None
            return PositionsEvent(positions)
        return None
