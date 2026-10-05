"""pm-alf-console tells the engine it is alive, so a killed console frees its
participant ID instead of locking it."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from edumatcher.models.message import decode


def _make_gateway(gw_id: str = "GW01"):
    from edumatcher.alf_console.main import Gateway

    with (
        patch("edumatcher.alf_console.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.alf_console.main.make_subscriber", return_value=MagicMock()),
    ):
        return Gateway(gw_id)


def test_heartbeat_loop_sends_beat_on_its_own_socket_then_stops() -> None:
    gw = _make_gateway()
    own_push = MagicMock()
    gw._heartbeat_stop.set()

    with patch("edumatcher.alf_console.main.make_pusher", return_value=own_push):
        gw._heartbeat_loop()

    topic, payload = decode(own_push.send_multipart.call_args.args[0])
    assert topic == "system.gateway_heartbeat"
    assert payload == {"gateway_id": "GW01", "interval_sec": 60}
    own_push.close.assert_called_once()
