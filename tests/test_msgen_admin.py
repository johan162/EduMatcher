"""Phase 6.1d: the admin family, and the map that turned out to be closed.

``scope`` was ``dict[str, Any]`` and the builder's docstring said its shape
"varies by action". Twelve producer sites draw on seven keys and never
anything else, so it is a declared record now.

The record keeps its nesting, unlike section 24.2's ``details``: the envelope
is what every admin action has and ``scope`` is what this one acted on. What
the spec still cannot say is which subset a given ``action`` uses — section
20.3's limitation, a second time.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import admin as G
from edumatcher.models.generated._runtime import MessageValidationError

_ENGINE = pathlib.Path(__file__).resolve().parents[1] / "src/edumatcher/engine/main.py"


def _payload(frames: list[bytes]) -> dict:
    return M.decode(frames)[1]


def _scope_literals() -> list[tuple[int, ast.Dict]]:
    """Every ``scope`` dict literal passed to ``_publish_admin_action``."""
    tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "_publish_admin_action"
            and len(node.args) > 3
            and isinstance(node.args[3], ast.Dict)
        ):
            out.append((node.lineno, node.args[3]))
    return out


class TestTheBuilderDelegates:
    def test_byte_identical_to_the_generated_call(self) -> None:
        assert M.make_admin_action_msg(
            "ADMIN01", "c1", "circuit_breaker.trigger", {"symbol": "AAPL"}, True
        ) == G.make_admin_action(
            gateway_id="ADMIN01",
            command_id="c1",
            initiator_gateway_id="ADMIN01",
            action="circuit_breaker.trigger",
            scope={"symbol": "AAPL"},
            accepted=True,
            reason="",
        )

    def test_the_initiator_is_repeated_in_the_body(self) -> None:
        """Redundant on the live wire, load-bearing off it: a stored or
        forwarded event without its topic still says who ran the command."""
        p = _payload(
            M.make_admin_action_msg("ADMIN01", "c1", "kill_switch.global", {}, True)
        )
        assert p["initiator_gateway_id"] == "ADMIN01"
        assert "gateway_id" not in p


class TestTheScopeRecordIsClosed:
    """The gate that will disagree the moment a thirteenth call site adds a key.

    ``from_dict`` reads declared keys only, so an undeclared one is dropped
    with no error — the builder returns, the monitor receives a well-formed
    event, and a field is simply missing. Section 1's failure class, and the
    reason this is checked statically rather than trusted.
    """

    def test_an_undeclared_key_is_silently_dropped(self) -> None:
        """The hazard itself, stated so the static check below has a reason."""
        p = _payload(
            M.make_admin_action_msg(
                "A", "c", "kill_switch.self", {"index_id": "EDU100"}, True
            )
        )
        assert p["scope"] == {}

    def test_every_engine_scope_key_is_declared(self) -> None:
        declared = {f.name for f in G.AdminActionScope.__dataclass_fields__.values()}
        offenders = []
        for lineno, node in _scope_literals():
            for key in node.keys:
                if not isinstance(key, ast.Constant):
                    offenders.append(f"main.py:{lineno}: non-literal scope key")
                elif key.value not in declared:
                    offenders.append(f"main.py:{lineno}: undeclared {key.value!r}")
        assert offenders == [], "\n".join(offenders)

    def test_the_scan_actually_found_the_call_sites(self) -> None:
        """A check that matched nothing would pass for the wrong reason."""
        assert len(_scope_literals()) == 12

    def test_index_id_is_not_one_of_them(self) -> None:
        """The builder's docstring offered it as an example for a long time
        and no producer has ever sent it. Section 27.6."""
        assert "index_id" not in G.AdminActionScope.__dataclass_fields__


class TestPresence:
    def test_an_unscoped_kill_switch_omits_the_symbol(self) -> None:
        """``kill_switch.self`` emitted an explicit null where its siblings
        omitted the key — two spellings of one absence, now one."""
        p = _payload(
            M.make_admin_action_msg(
                "A", "c", "kill_switch.self", {"symbol": None}, True
            )
        )
        assert "symbol" not in p["scope"]

    def test_an_empty_note_omits(self) -> None:
        """Regime 4, matching ``risk.kill_switch``'s own note — the field this
        value arrives from. A field that omits on one message and emits "" on
        the next would be two answers to one question."""
        p = _payload(
            M.make_admin_action_msg("A", "c", "kill_switch.self", {"note": ""}, True)
        )
        assert "note" not in p["scope"]

    def test_a_rejection_carries_an_empty_scope_object(self) -> None:
        """``kill_switch.global`` rejected names nothing at all. The key stays
        — a record is always emitted — and its object is empty."""
        p = _payload(
            M.make_admin_action_msg(
                "A", "c", "kill_switch.global", {}, False, "not admin"
            )
        )
        assert p["scope"] == {}
        assert p["reason"] == "not admin"

    def test_reason_is_always_present(self) -> None:
        p = _payload(M.make_admin_action_msg("A", "c", "kill_switch.self", {}, True))
        assert p["reason"] == ""

    def test_a_zero_count_is_emitted(self) -> None:
        """A kill switch that cancelled nothing is a real outcome."""
        p = _payload(
            M.make_admin_action_msg(
                "A", "c", "kill_switch.self", {"cancelled_orders": 0}, True
            )
        )
        assert p["scope"]["cancelled_orders"] == 0


class TestTheActionEnum:
    def test_every_action_the_engine_publishes_is_declared(self) -> None:
        """Enumerated from the call sites, not from the docstring."""
        from typing import get_args

        tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
        used = {
            node.args[2].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "_publish_admin_action"
            and len(node.args) > 2
            and isinstance(node.args[2], ast.Constant)
        }
        assert used == set(get_args(G.AdminActionAction))

    def test_an_undeclared_action_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="action"):
            M.make_admin_action_msg("A", "c", "index.rebalance", {}, True)

    def test_the_values_are_not_topics(self) -> None:
        """`circuit_breaker.trigger` is the action behind `risk.symbol_halt`,
        and there is no topic by that name anywhere."""
        from edumatcher.msgen.spec import load_all

        root = pathlib.Path(__file__).resolve().parents[1] / "spec"
        _registry, families = load_all(root)
        topics = {m.topic for f in families for m in f.messages}
        assert "circuit_breaker.trigger" not in topics


class TestTheBoundTheAuditAdded:
    def test_the_engine_clamps_the_operator_note(self) -> None:
        """27.5: the ack is published *before* the monitor record, so an
        unbounded note lets the command succeed, answer "accepted", and lose
        its own audit entry to a validation error nobody sees."""
        source = _ENGINE.read_text(encoding="utf-8")
        reads = re.findall(
            r'note = str\(payload\.get\("note", ""\)\)(\[[^\]]*\])?', source
        )
        assert reads, "no note reads found — has the handler shape changed?"
        assert all(r == "[:_MAX_WIRE_NOTE_LEN]" for r in reads), reads

    def test_the_clamp_matches_the_spec(self) -> None:
        from edumatcher.engine.main import _MAX_WIRE_NOTE_LEN

        assert _MAX_WIRE_NOTE_LEN == 256

    def test_the_ack_really_does_go_first(self) -> None:
        """The ordering the bound depends on, pinned rather than remembered."""
        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine._handle_kill_switch)
        assert source.index("make_kill_switch_ack_msg") < source.index(
            "_publish_admin_action"
        )


class TestTheTopicIsDeclared:
    def test_one_topic(self) -> None:
        assert len(G.FAMILY_TOPICS) == 1

    def test_it_is_gateway_addressed(self) -> None:
        assert G.topic_admin_action("ADMIN01") == "admin.action.ADMIN01"
        assert G.match_admin_action("admin.action.ADMIN01") == "ADMIN01"

    def test_it_is_not_a_private_prefix(self) -> None:
        """The one topic addressed to a gateway that is not for that gateway:
        the suffix names the ADMIN caller so a monitor can filter, and it must
        never reach that caller's own trading stream."""
        from edumatcher.api_gateway.events import ADMIN_ACTION_PREFIX, PRIVATE_PREFIXES

        assert ADMIN_ACTION_PREFIX == "admin.action."
        assert ADMIN_ACTION_PREFIX not in PRIVATE_PREFIXES
