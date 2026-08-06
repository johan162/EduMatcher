"""Correlation ids for the two commands that had no natural identifier.

Orders correlate on `order_id`, combos on `combo_id`, halts on `symbol`. Mass
cancel and session transition had nothing — mass cancel was worked around with
a per-gateway lock that serialised concurrent requests, and session transition
was fire-and-forget with silent failure modes. Both are fixed with a
`command_id`; these tests pin the properties that made it worth doing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.events import new_command_id
from edumatcher.models.message import (
    decode,
    make_kill_switch_ack_msg,
    make_kill_switch_msg,
    make_session_transition_ack_msg,
    make_session_transition_msg,
)


def _payload(frames: list[bytes]) -> dict[str, Any]:
    return decode(frames)[1]


def _topic(frames: list[bytes]) -> str:
    return decode(frames)[0]


@pytest.fixture
def client() -> Iterator[EngineClient]:
    loop = asyncio.new_event_loop()
    try:
        with (
            patch(
                "edumatcher.api_gateway.engine_client.make_pusher",
                return_value=MagicMock(closed=False),
            ),
            patch(
                "edumatcher.api_gateway.engine_client.make_subscriber",
                return_value=MagicMock(),
            ),
        ):
            yield EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
    finally:
        loop.close()


def _engine():
    """An Engine with fake sockets — never binds a port."""
    from edumatcher.engine.main import Engine

    with (
        patch("edumatcher.engine.main.make_puller", return_value=MagicMock()),
        patch("edumatcher.engine.main.make_publisher", return_value=MagicMock()),
    ):
        return Engine()


def _published(engine) -> list[list[bytes]]:
    return [call[0][0] for call in engine.pub_sock.send_multipart.call_args_list]


# ---------------------------------------------------------------------------
# Wire format — additive
# ---------------------------------------------------------------------------


def test_command_ids_are_unique() -> None:
    assert new_command_id() != new_command_id()
    assert new_command_id().startswith("cmd-")


def test_kill_switch_messages_are_unchanged_without_a_command_id() -> None:
    """Every existing caller — ALF, the admin CLI — omits it."""
    assert _payload(make_kill_switch_msg("GW01", "AAPL")) == {
        "gateway_id": "GW01",
        "symbol": "AAPL",
    }
    assert "command_id" not in _payload(make_kill_switch_ack_msg("GW01", True))


def test_kill_switch_carries_the_command_id_both_ways() -> None:
    assert _payload(make_kill_switch_msg("GW01", "", "cmd-1"))["command_id"] == "cmd-1"
    ack = _payload(make_kill_switch_ack_msg("GW01", True, command_id="cmd-1"))
    assert ack["command_id"] == "cmd-1"


def test_session_transition_stays_unchanged_for_the_scheduler() -> None:
    """pm-scheduler drives the timetable and has nobody to report back to."""
    payload = _payload(
        make_session_transition_msg("OPEN", next_state="CLOSED", next_at="16:00")
    )
    assert payload == {"to_state": "OPEN", "next_state": "CLOSED", "next_at": "16:00"}


def test_session_transition_carries_command_id_only_with_a_gateway() -> None:
    """The ack is addressed to a gateway, so an id without one is unusable."""
    both = _payload(
        make_session_transition_msg("OPEN", command_id="cmd-1", gateway_id="GW01")
    )
    assert both["command_id"] == "cmd-1" and both["gateway_id"] == "GW01"
    assert "command_id" not in _payload(
        make_session_transition_msg("OPEN", command_id="cmd-1")
    )


def test_transition_ack_is_addressed_not_broadcast() -> None:
    """A command_id belongs to whoever issued it — putting it on the public
    session.state topic would hand every subscriber someone else's id."""
    frames = make_session_transition_ack_msg("GW01", "cmd-1", True, to_state="OPEN")
    assert _topic(frames) == "session.transition_ack.GW01"


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------


def test_engine_echoes_the_command_id_on_the_kill_switch_ack() -> None:
    engine = _engine()
    with patch.object(engine, "_gateway_status", return_value=(True, "")):
        engine._handle_kill_switch(
            {"gateway_id": "GW01", "symbol": "", "command_id": "cmd-7"}
        )
    acks = [
        f for f in _published(engine) if _topic(f).startswith("risk.kill_switch_ack")
    ]
    assert _payload(acks[-1])["command_id"] == "cmd-7"


def test_engine_echoes_the_command_id_on_a_rejected_kill_switch() -> None:
    """The rejection path needs it as much as the success path — arguably more,
    since that is the one a client is waiting to explain."""
    engine = _engine()
    with patch.object(engine, "_gateway_status", return_value=(False, "not connected")):
        engine._handle_kill_switch({"gateway_id": "GW01", "command_id": "cmd-8"})
    ack = _payload(_published(engine)[-1])
    assert ack["command_id"] == "cmd-8"
    assert ack["accepted"] is False


def test_session_transition_rejection_is_reported_not_silent() -> None:
    """Previously the engine returned early and published nothing, so a caller
    saw only a timeout — indistinguishable from a slow engine."""
    engine = _engine()
    engine._sessions_enabled = False
    engine._handle_session_transition(
        {"to_state": "OPEN", "command_id": "cmd-9", "gateway_id": "GW01"}
    )
    published = _published(engine)
    assert len(published) == 1
    assert _topic(published[0]) == "session.transition_ack.GW01"
    ack = _payload(published[0])
    assert ack["accepted"] is False
    assert "not enabled" in ack["reason"]


def test_an_unknown_state_is_rejected_with_a_reason() -> None:
    engine = _engine()
    engine._sessions_enabled = True
    engine._handle_session_transition(
        {"to_state": "NOT_A_STATE", "command_id": "cmd-10", "gateway_id": "GW01"}
    )
    ack = _payload(_published(engine)[-1])
    assert ack["accepted"] is False
    assert ack["command_id"] == "cmd-10"


def test_the_scheduler_gets_no_ack() -> None:
    """It supplies no command_id, so there is nobody to answer. Publishing an
    ack anyway would put it on `session.transition_ack.` with an empty id."""
    engine = _engine()
    engine._sessions_enabled = False
    engine._handle_session_transition({"to_state": "OPEN"})
    assert _published(engine) == []


# ---------------------------------------------------------------------------
# The property that replaced the lock
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_mass_cancels_resolve_to_their_own_acks() -> None:
    """The reason the per-gateway kill-switch lock could be deleted.

    Two mass cancels for one gateway are now told apart by command_id. Under
    the old code both waiters were unfiltered on the same topic, so whichever
    ack arrived first satisfied whichever caller was waiting — which is why
    the calls had to be serialised instead.
    """
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        engine = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )

    sent: list[dict[str, Any]] = []
    push = cast(MagicMock, engine._push)
    push.send_multipart.side_effect = lambda frames: sent.append(_payload(frames))

    first = asyncio.create_task(engine.send_and_await_kill_switch("GW01", "AAPL", 2.0))
    second = asyncio.create_task(engine.send_and_await_kill_switch("GW01", "MSFT", 2.0))
    for _ in range(50):
        if len(sent) == 2:
            break
        await asyncio.sleep(0)

    assert len(sent) == 2, "both requests were sent; neither waited on a lock"
    ids = [s["command_id"] for s in sent]
    assert ids[0] != ids[1]

    # Answer them out of order: the second request's ack arrives first.
    engine._handle_event(
        "risk.kill_switch_ack.GW01",
        {"accepted": True, "command_id": ids[1], "cancelled_orders": 5},
    )
    engine._handle_event(
        "risk.kill_switch_ack.GW01",
        {"accepted": True, "command_id": ids[0], "cancelled_orders": 3},
    )

    assert (await first)["cancelled_orders"] == 3
    assert (await second)["cancelled_orders"] == 5


@pytest.mark.anyio
async def test_a_transition_timeout_leaves_no_waiter_behind() -> None:
    """Requires Python 3.11+, where asyncio.TimeoutError *is* TimeoutError.

    `send_and_await_session_transition` catches the builtin, matching
    `await_event`'s existing idiom. On 3.10 the two are distinct classes, the
    except does not fire, and the waiter leaks — so this fails there. The
    project targets 3.13.
    """
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        engine = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )

    with pytest.raises(TimeoutError):
        await engine.send_and_await_session_transition("GW01", "OPEN", 0.01)
    assert not engine._pending, f"waiter left behind: {dict(engine._pending)}"


def test_the_kill_switch_lock_is_gone(client: EngineClient) -> None:
    """Pins the removal: reintroducing it would silently restore the
    serialisation this change exists to remove."""
    assert not hasattr(client, "_kill_switch_locks")
