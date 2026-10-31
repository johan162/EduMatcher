"""WP-API08: the normative WebSocket chapter agrees with the code.

``070-websocket.md`` is what a client is written against; every catalogue in
it is derived here from the code it describes, in both directions, so a new
event type, control frame, reason or queue size cannot ship undocumented.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path
from typing import Any, get_args

from edumatcher.api_gateway.events import PRIVATE_PREFIXES, websocket_type
from edumatcher.api_gateway.routers import ws
from edumatcher.api_gateway.schemas import (
    ALWAYS_ON_CHANNELS,
    MarketDataChannel,
    MarketDataControl,
)
from edumatcher.models.generated.registry import TOPIC_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/books/protocols-and-clients/part-2-specifications/070-websocket.md"
WS_SOURCE = ROOT / "src/edumatcher/api_gateway/routers/ws.py"
SIM_SOURCE = ROOT / "src/edumatcher/api_gateway/sim_client.py"


@cache
def _text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _section(heading: str) -> str:
    """The body under the first heading whose text is *heading*."""
    text = _text()
    match = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.M)
    assert match, f"no section {heading!r}"
    level = len(match.group(1))
    rest = text[match.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _rows(body: str) -> list[list[str]]:
    """Every table row (header and separator excluded) in *body*."""
    rows = []
    for table in re.findall(r"(?:^\|.*\|\s*\n)+", body, re.M):
        lines = [line for line in table.strip().splitlines()]
        for line in lines[2:]:
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _code(cell: str) -> str:
    match = re.match(r"`([^`]+)`", cell)
    return match.group(1) if match else cell


@cache
def _ws_tree() -> ast.Module:
    return ast.parse(WS_SOURCE.read_text(encoding="utf-8"))


def _function(name: str) -> ast.AST:
    for node in ast.walk(_ws_tree()):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name == name
        ):
            return node
    raise AssertionError(name)


def _type_literals(tree: ast.AST) -> set[str]:
    """String values of ``"type"`` keys in dict literals under *tree*."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "type"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.add(value.value)
    return found


# --- streams ------------------------------------------------------------------


def _queue_size(handler: str) -> int:
    for node in ast.walk(_function(handler)):
        if isinstance(node, ast.keyword) and node.arg == "maxsize":
            assert isinstance(node.value, ast.Constant)
            assert isinstance(node.value.value, int)
            return node.value.value
    raise AssertionError(f"{handler} has no bounded queue")


def test_the_streams_table_is_the_routes_and_their_queues() -> None:
    handlers = {
        route.path: route.endpoint.__name__  # type: ignore[attr-defined]
        for route in ws.router.routes
    }
    documented = {_code(r[0]): int(_code(r[3])) for r in _rows(_section("Streams"))}
    assert set(documented) == set(handlers)
    for path, handler in handlers.items():
        assert documented[path] == _queue_size(handler), path


def test_the_auth_timeout_is_as_documented() -> None:
    calls = [
        node
        for node in ast.walk(_function("_authenticate_ws"))
        if isinstance(node, ast.keyword) and node.arg == "timeout"
    ]
    assert [c.value.value for c in calls if isinstance(c.value, ast.Constant)] == [5.0]
    assert "within **5 seconds**" in _section("Connecting")


def test_the_only_close_code_is_documented() -> None:
    used = {
        int(node.attr.split("_")[1])
        for node in ast.walk(_ws_tree())
        if isinstance(node, ast.Attribute) and node.attr.startswith("WS_")
    }
    documented = {int(_code(r[0])) for r in _rows(_section("Close codes"))}
    assert used == documented == {1008}


# --- envelope and types -----------------------------------------------------


def _concrete(topic: str) -> str:
    return (
        topic.replace("{gateway_id}", "GW01")
        .replace("{symbol}", "AAPL")
        .replace("circuit_breaker.*", "circuit_breaker.halt.AAPL")
    )


def test_every_documented_type_exception_holds() -> None:
    for row in _rows(_section("Event types")):
        topic, expected = _code(row[0]), _code(row[1])
        assert websocket_type(_concrete(topic)) == expected, topic


def test_the_private_catalogue_is_the_private_routing_table() -> None:
    documented = {
        _code(r[0]): _code(r[1]) for r in _rows(_section("Private event catalogue"))
    }
    derived = {websocket_type(prefix + "GW01"): prefix for prefix in PRIVATE_PREFIXES}
    assert set(documented) == set(derived)
    for type_, topic in documented.items():
        assert topic == derived[type_] + "{gateway_id}", type_


# --- market data ----------------------------------------------------------------


def _channels_table() -> dict[str, tuple[str, set[str]]]:
    table = {}
    for row in _rows(_section("Channels")):
        types = set(re.findall(r"`([^`]+)`", row[2]))
        table[_code(row[0])] = (row[1], types)
    return table


def test_channels_match_the_subscription_model() -> None:
    table = _channels_table()
    subscribable = {name for name, (sub, _) in table.items() if sub == "yes"}
    always = {name for name, (sub, _) in table.items() if sub == "always on"}
    assert subscribable == set(get_args(MarketDataChannel))
    assert always == set(ALWAYS_ON_CHANNELS)


def test_market_data_event_types_are_what_the_socket_forwards() -> None:
    table = _channels_table()
    for channel, (_, types) in table.items():
        for type_ in types:
            assert ws._event_channel(type_) == channel, type_
    # Completeness: every type any engine topic (or news) can produce that the
    # socket would forward is documented under some channel.
    candidates = {websocket_type(_concrete(t)) for t in TOPIC_REGISTRY} | {"news"}
    forwarded = {t for t in candidates if ws._event_channel(t) is not None}
    documented = set().union(*(types for _, types in table.values()))
    assert forwarded == documented


def test_control_actions_are_the_control_model() -> None:
    documented = {_code(r[0]) for r in _rows(_section("Control frames"))}
    actions = MarketDataControl.model_fields["action"].annotation
    assert documented == set(get_args(actions))


def _reasons(source: Any) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(source):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "reason"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.add(value.value)
    return found


def _server_frames_part(start: str, end: str | None) -> set[str]:
    """First-column values of the table between two markers in the section."""
    body = _section("Server control frames").split(start, 1)[1]
    if end is not None:
        body = body.split(end, 1)[0]
    return {_code(r[0]) for r in _rows(body)}


def test_subscription_rejection_reasons() -> None:
    documented = _server_frames_part(
        "`subscription.data.rejected`", "`resume.rejected.data.reason`"
    )
    assert documented == _reasons(_function("apply"))


def _resume_reasons_code() -> set[str]:
    found: set[str] = set()
    for node in ast.walk(_ws_tree()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_reject_resume"
            and isinstance(node.args[-1], ast.Constant)
            and isinstance(node.args[-1].value, str)
        ):
            found.add(node.args[-1].value)
    return found


def test_resume_rejection_reasons() -> None:
    documented = _server_frames_part("`resume.rejected.data.reason`", None)
    assert documented == _resume_reasons_code() == {"unknown_topic", "too_old"}


# --- frames that are not engine events ----------------------------------------


def test_every_server_frame_type_is_documented() -> None:
    sim_tree = ast.parse(SIM_SOURCE.read_text(encoding="utf-8"))
    emitted = _type_literals(_ws_tree()) | (_type_literals(sim_tree) - {"news"})
    documented = set(re.findall(r"^\| `([a-z_.]+)` \|", _text(), re.M))
    assert emitted - documented == set()


def test_the_sim_socket_forwards_its_topics_as_types() -> None:
    from edumatcher.models.generated.sim import TOPIC_SIM_STATE, TOPIC_SIM_VALUE

    documented = {_code(r[0]) for r in _rows(_section("`/api/v1/ws/admin/sim`"))}
    assert {
        TOPIC_SIM_STATE,
        TOPIC_SIM_VALUE,
        "sim.snapshot",
        "authenticated",
    } == documented
