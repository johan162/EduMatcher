"""Phase 4a: the Python and C bindings must agree on the CALF wire.

This is capstone assertion 4 at one message's scale, and it is the assertion no
test in this repository could previously state. Everything else about the
generator can be checked within Python; whether a C client and a Python
publisher actually read the same bytes the same way cannot.

The harness compiles the *committed generated* C — the same files a student
building `docs/examples/calf` links against — drives it with lines produced by
the *committed generated* Python projection, and compares field by field.

Following ``tests/test_alf_examples.py``: `shutil.which("cc")` plus
``pytest.skip``, no new dependency, no marker. A cffi binding was considered
and rejected in design section 8 (Phase 4 corrections) — cffi is not a
dependency of this project and this pattern already works here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from edumatcher.models.generated.trade import (
    MSGTYPE_TRADE_EXECUTED_CALF,
    TradeExecuted,
    parse_trade_executed_calf,
    project_trade_executed_calf,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_C = REPO_ROOT / "docs" / "examples" / "generated"
CALF_C = REPO_ROOT / "docs" / "examples" / "calf"

_SAMPLE: dict[str, Any] = {
    "id": "42",
    "symbol": "ACME",
    "buy_order_id": "b-1",
    "sell_order_id": "s-1",
    "buy_gateway_id": "GW1",
    "sell_gateway_id": "GW2",
    "price": 101.5,
    "quantity": 300,
    "aggressor_side": "BUY",
    "timestamp": 1_700_000_000.0,
    "tick_decimals": 2,
}

#: Emits the parsed struct as JSON so the comparison happens in Python, where
#: the expected values live. Kept here rather than in the examples tree: it is
#: a test fixture, not something a student should find beside the clients.
_HARNESS = r"""
#include <stdio.h>
#include <string.h>
#include "edumatcher_trade.h"

int main(int argc, char **argv) {
    char line[2048];
    calf_message_t msg;
    edu_trade_executed_calf_t trade;
    char err[160];
    int rc;

    if (argc < 2) return 2;
    snprintf(line, sizeof(line), "%s", argv[1]);

    rc = calf_parse_line(line, &msg);
    if (rc != 0) { printf("{\"stage\":\"line\",\"rc\":%d}\n", rc); return 0; }

    rc = edu_trade_executed_calf_parse(&msg, &trade);
    if (rc != 0) {
        printf("{\"stage\":\"parse\",\"rc\":%d,\"msg\":\"%s\"}\n",
               rc, edu_msg_strerror(rc));
        return 0;
    }

    rc = edu_trade_executed_calf_validate(&trade, err, sizeof(err));
    if (rc != 0) {
        printf("{\"stage\":\"validate\",\"rc\":%d,\"msg\":\"%s\"}\n", rc, err);
        return 0;
    }

    printf("{\"stage\":\"ok\",\"price\":%.17g,\"quantity\":%lld,\"side\":\"%s\"}\n",
           trade.price, (long long)trade.quantity,
           edu_trade_executed_aggressor_side_to_str(trade.aggressor_side));
    return 0;
}
"""


def _require_cc() -> str:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("cc is required for the generated-C round-trip test")
    return cc


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compile the committed generated C together with the CALF tokeniser."""
    cc = _require_cc()
    build = tmp_path_factory.mktemp("msgen_c")
    source = build / "harness.c"
    source.write_text(_HARNESS, encoding="utf-8")
    binary = build / "harness"

    result = subprocess.run(
        [
            cc,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-pedantic",
            "-Werror",
            "-O2",
            f"-I{GENERATED_C}",
            f"-I{CALF_C}",
            "-o",
            str(binary),
            str(source),
            str(GENERATED_C / "edumatcher_trade.c"),
            str(GENERATED_C / "edumatcher_msg.c"),
            str(CALF_C / "calf_parser.c"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "generated C failed to compile:\n" + result.stdout + result.stderr
    )
    # -Werror above is the real assertion: the generated C must be warning-free
    # under -Wall -Wextra -pedantic, because it is committed and read.
    return binary


def _run(harness: Path, line: str) -> dict[str, Any]:
    result = subprocess.run(
        [str(harness), line], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def _calf_line(fields: dict[str, str], msg_type: str | None = None) -> str:
    """Build a CALF line the way md_gateway's build_line does."""
    parts = [msg_type or MSGTYPE_TRADE_EXECUTED_CALF]
    parts += [f"{key}={value}" for key, value in fields.items()]
    return "|".join(parts)


class TestGeneratedCCompiles:
    def test_it_builds_warning_free(self, harness: Path) -> None:
        """-Werror in the fixture; reaching here means it compiled clean."""
        assert harness.exists()

    def test_the_committed_c_is_what_was_compiled(self) -> None:
        """Guards against the test silently building something else."""
        header = (GENERATED_C / "edumatcher_trade.h").read_text(encoding="utf-8")
        assert header.startswith("/* GENERATED FROM spec/messages/trade.yaml")
        assert "edu_trade_executed_calf_parse" in header


class TestPythonAndCAgree:
    """Capstone assertion 4: project -> line -> C parse -> compare."""

    @pytest.mark.parametrize(
        "override",
        [
            {},
            {"aggressor_side": "SELL"},
            {"aggressor_side": "AUCTION"},
            {"price": 0.01},
            {"price": 12345.6789},
            {"quantity": 1},
            {"quantity": 1_000_000},
            {"price": 150.0, "quantity": 42},
        ],
    )
    def test_round_trip(self, harness: Path, override: dict[str, Any]) -> None:
        payload = {**_SAMPLE, **override}
        message = TradeExecuted.from_dict(payload)
        projected = project_trade_executed_calf(message.to_dict())

        result = _run(harness, _calf_line(projected))

        assert result["stage"] == "ok", result
        assert result["price"] == pytest.approx(message.price, rel=0, abs=0)
        assert result["quantity"] == message.quantity
        assert result["side"] == message.aggressor_side

    def test_envelope_keys_are_ignored_by_the_parser(self, harness: Path) -> None:
        """A real line carries CH/SYM/SEQ/TS; the projection carries none.

        The parser must read its own keys out of the full frame and ignore the
        gateway's envelope entirely (design section 4.6).
        """
        message = TradeExecuted.from_dict(_SAMPLE)
        fields = {
            "CH": "TRADE",
            "SYM": "ACME",
            "SEQ": "17",
            "TS": "2026-01-01T00:00:00.000Z",
            **project_trade_executed_calf(message.to_dict()),
        }
        result = _run(harness, _calf_line(fields))
        assert result["stage"] == "ok", result
        assert result["quantity"] == message.quantity

    def test_python_parses_back_what_it_projected(self) -> None:
        """The Python half of the round trip, independent of the compiler."""
        message = TradeExecuted.from_dict(_SAMPLE)
        recovered = parse_trade_executed_calf(
            project_trade_executed_calf(message.to_dict())
        )
        assert recovered.price == message.price
        assert recovered.quantity == message.quantity
        assert recovered.aggressor_side == message.aggressor_side

    def test_fields_the_projection_drops_are_not_invented(self) -> None:
        """CALF's TRADE print carries no id or symbol (design section 4.6)."""
        recovered = parse_trade_executed_calf(project_trade_executed_calf(_SAMPLE))
        assert recovered.id == ""
        assert recovered.symbol == ""
        assert recovered.buy_order_id == ""
        assert recovered.timestamp == 0.0


class TestCErrorPaths:
    """The declared rules must be enforced in C, not only in Python."""

    def test_wrong_msg_type(self, harness: Path) -> None:
        line = _calf_line({"PX": "1", "QTY": "1", "SIDE": "BUY"}, msg_type="MD")
        assert _run(harness, line) == {
            "stage": "parse",
            "rc": -4,
            "msg": "unknown or unexpected msg_type",
        }

    @pytest.mark.parametrize("missing", ["PX", "QTY", "SIDE"])
    def test_missing_required_field(self, harness: Path, missing: str) -> None:
        fields = {"PX": "1.5", "QTY": "10", "SIDE": "BUY"}
        del fields[missing]
        result = _run(harness, _calf_line(fields))
        assert result["stage"] == "parse"
        assert result["rc"] == -6

    @pytest.mark.parametrize(
        "fields",
        [
            {"PX": "abc", "QTY": "10", "SIDE": "BUY"},
            {"PX": "1.5", "QTY": "ten", "SIDE": "BUY"},
            {"PX": "1.5", "QTY": "10", "SIDE": "SIDEWAYS"},
            {"PX": "1.5x", "QTY": "10", "SIDE": "BUY"},
            {"PX": "1.5", "QTY": "10.5", "SIDE": "BUY"},
        ],
    )
    def test_unparseable_value(self, harness: Path, fields: dict[str, str]) -> None:
        """Trailing junk is rejected too: strtod stopping early is not success."""
        result = _run(harness, _calf_line(fields))
        assert result["stage"] == "parse"
        assert result["rc"] == -6

    @pytest.mark.parametrize(
        "fields, expected",
        [
            ({"PX": "0", "QTY": "10", "SIDE": "BUY"}, "price must be > 0"),
            ({"PX": "-1", "QTY": "10", "SIDE": "BUY"}, "price must be > 0"),
            ({"PX": "1.5", "QTY": "0", "SIDE": "BUY"}, "quantity must be > 0"),
            ({"PX": "1.5", "QTY": "-3", "SIDE": "BUY"}, "quantity must be > 0"),
        ],
    )
    def test_validation_rules_are_enforced_in_c(
        self, harness: Path, fields: dict[str, str], expected: str
    ) -> None:
        """Design goal 5: rules declared once, enforced by both bindings."""
        result = _run(harness, _calf_line(fields))
        assert result["stage"] == "validate"
        assert result["rc"] == -6
        assert result["msg"] == expected

    def test_c_and_python_reject_the_same_values(self, harness: Path) -> None:
        """The two bindings must not disagree about what is valid."""
        from edumatcher.models.generated._runtime import MessageValidationError

        for bad in ({"price": 0.0}, {"price": -1.0}, {"quantity": 0}):
            payload = {**_SAMPLE, **bad}
            message = TradeExecuted.from_dict(payload)

            with pytest.raises(MessageValidationError):
                message.validate()

            result = _run(
                harness, _calf_line(project_trade_executed_calf(message.to_dict()))
            )
            assert result["stage"] == "validate", (bad, result)


class TestEnumHelpers:
    @pytest.mark.parametrize("side", ["BUY", "SELL", "AUCTION"])
    def test_every_declared_value_round_trips_through_c(
        self, harness: Path, side: str
    ) -> None:
        line = _calf_line({"PX": "1.5", "QTY": "10", "SIDE": side})
        assert _run(harness, line)["side"] == side
