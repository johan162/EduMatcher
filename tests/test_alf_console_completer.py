"""Tab completion offers what the parser accepts (review WP-ACN06, C8)."""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from edumatcher.alf_console.completer import GatewayCompleter


def _complete(text: str) -> list[str]:
    completer = GatewayCompleter(["AAPL"])
    return [
        c.text
        for c in completer.get_completions(Document(text, len(text)), CompleteEvent())
    ]


def test_dc_and_session_are_commands() -> None:
    assert _complete("D") == ["DC"]
    assert _complete("SE") == ["SESSION"]


def test_dc_completes_state_and_its_values() -> None:
    assert _complete("DC|") == ["STATE="]
    assert _complete("DC|STATE=") == ["ON", "OFF"]


def test_new_does_not_offer_amend_and_cancel_fields() -> None:
    offered = _complete("NEW|")
    assert "ID=" not in offered
    assert "RTAG=" not in offered
    assert "SYM=" in offered and "TYPE=" in offered


def test_combo_legs_offer_stop() -> None:
    offered = _complete("NEW|TYPE=COMBO|LEG_COUNT=2|")
    assert "LEG0.STOP=" in offered
    assert "LEG1.STOP=" in offered


def test_amend_and_cancel_unchanged() -> None:
    assert _complete("AMEND|") == ["ID=", "PRICE=", "QTY=", "RTAG="]
    assert _complete("CANCEL|") == ["ID=", "COMBO_ID=", "OCO_ID=", "RTAG="]
