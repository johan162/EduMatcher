"""Phase 4b: the BALF binary layout, in Python and in C.

This is capstone assertion 5 — the binary half of "a C client and a Python
publisher read the same bytes the same way" — plus the assertion that matters
most here: **the generated binding is the production gateway's serialiser**.

Byte-for-byte equality against an independent inline reference packer (the
documented layout, packed with ``struct`` right here) is what makes the spec
trustworthy: the generator and the reference share no code, so agreement is
evidence. The gateway itself calls ``serialise_execution_report_balf`` directly,
so there is no second hand-written packer left to drift.

Also guards the defect that started this phase: ``docs/examples/balf`` disagreed
with the gateway on six of twelve frame sizes for years, and nothing compared
them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from edumatcher.balf_gwy import codec
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.order import (
    FRAME_SIZE_EXECUTION_REPORT_BALF,
    MSGTYPE_EXECUTION_REPORT_BALF,
    ExecutionReport,
    parse_execution_report_balf,
    serialise_execution_report_balf,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_C = REPO_ROOT / "docs" / "examples" / "generated"
BALF_EXAMPLES = REPO_ROOT / "docs" / "examples" / "balf"

_SAMPLE: dict[str, Any] = {
    "client_order_id": 99,
    "order_id": 1234567890123,
    "fill_price": 99.5,
    "fill_qty": 100,
    "remaining_qty": 0,
    "timestamp_ns": 1_700_000_000_000_000_000,
    "symbol": "MSFT",
    "side": "SELL",
    "status": "FILLED",
}

_SIDE = {"BUY": codec.SIDE_BUY, "SELL": codec.SIDE_SELL}
_STATUS = {"PARTIAL": codec.STATUS_PARTIAL, "FILLED": codec.STATUS_FILLED}

_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "edumatcher_order.h"

int main(int argc, char **argv) {
    uint8_t frame[512];
    size_t n = 0;
    edu_execution_report_balf_t er;
    char err[160];
    int rc;
    const char *h;

    if (argc < 2) return 2;
    for (h = argv[1]; h[0] && h[1] && n < sizeof(frame); h += 2) {
        char b[3]; b[0] = h[0]; b[1] = h[1]; b[2] = 0;
        frame[n++] = (uint8_t)strtoul(b, NULL, 16);
    }

    rc = edu_execution_report_balf_parse(frame, n, &er);
    if (rc != EDU_MSG_OK) {
        printf("{\"stage\":\"parse\",\"rc\":%d,\"msg\":\"%s\"}\n",
               rc, edu_msg_strerror(rc));
        return 0;
    }
    rc = edu_execution_report_balf_validate(&er, err, sizeof(err));
    if (rc != EDU_MSG_OK) {
        printf("{\"stage\":\"validate\",\"rc\":%d,\"msg\":\"%s\"}\n", rc, err);
        return 0;
    }
    printf("{\"stage\":\"ok\",\"client_order_id\":%llu,\"order_id\":%llu,"
           "\"fill_price\":%.17g,\"fill_qty\":%u,\"remaining_qty\":%u,"
           "\"timestamp_ns\":%llu,\"symbol\":\"%s\",\"side\":\"%s\","
           "\"status\":\"%s\"}\n",
           (unsigned long long)er.client_order_id,
           (unsigned long long)er.order_id, er.fill_price, er.fill_qty,
           er.remaining_qty, (unsigned long long)er.timestamp_ns, er.symbol,
           edu_execution_report_side_to_str(er.side),
           edu_execution_report_status_to_str(er.status));
    return 0;
}
"""


def _gateway_frame(payload: dict[str, Any], seq_no: int = 7) -> bytes:
    """The same message, packed independently from the documented layout.

    An inline reference oracle: it duplicates neither the generator nor the
    gateway, so byte-equality against it proves the generated serialiser matches
    the BALF spec (header magic 0xBA / version 0x01, body ``<QQqIIQ8sBB6x``).
    """
    import struct

    header = struct.pack(
        "<BBBBI",
        codec.BALF_MAGIC,
        codec.BALF_VERSION,
        codec.MSG_EXECUTION_REPORT,
        0,
        seq_no,
    )
    body = struct.pack(
        "<QQqIIQ8sBB6x",
        payload["client_order_id"],
        payload["order_id"],
        codec.encode_price(payload["fill_price"]),
        payload["fill_qty"],
        payload["remaining_qty"],
        payload["timestamp_ns"],
        payload["symbol"].encode("ascii"),
        _SIDE[payload["side"]],
        _STATUS[payload["status"]],
    )
    return header + body


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("cc is required for the generated-C BALF round-trip test")
    build = tmp_path_factory.mktemp("msgen_balf")
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
            "-o",
            str(binary),
            str(source),
            str(GENERATED_C / "edumatcher_order.c"),
            str(GENERATED_C / "edumatcher_msg.c"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "generated BALF C failed to compile:\n" + result.stdout + result.stderr
    )
    return binary


def _run(harness: Path, frame: bytes) -> dict[str, Any]:
    result = subprocess.run(
        [str(harness), frame.hex()], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


_CASES = [
    {},
    {"side": "BUY", "status": "PARTIAL", "remaining_qty": 50},
    {"fill_price": 150.0, "symbol": "AAPL"},
    {"fill_price": 0.00000001},
    {"client_order_id": 0, "order_id": 0},
    {"order_id": 2**64 - 1, "remaining_qty": 2**32 - 1},
    {"timestamp_ns": 0},
    {"symbol": "A.B_C1"},
]


class TestAgreesWithTheProductionGateway:
    """The claim that makes the spec trustworthy."""

    def test_frame_size_matches_codec(self) -> None:
        assert (
            FRAME_SIZE_EXECUTION_REPORT_BALF
            == codec.FRAME_SIZE[codec.MSG_EXECUTION_REPORT]
        )

    def test_msg_type_matches_codec(self) -> None:
        assert MSGTYPE_EXECUTION_REPORT_BALF == codec.MSG_EXECUTION_REPORT

    def test_price_scale_matches_codec(self) -> None:
        from edumatcher.models.generated.order import (
            PRICE_SCALE_EXECUTION_REPORT_BALF,
        )

        assert PRICE_SCALE_EXECUTION_REPORT_BALF == codec.PRICE_SCALE

    def test_enum_codes_match_codec(self) -> None:
        """A wrong code here would swap BUY and SELL on a live feed."""
        from edumatcher.models.generated.order import (
            _EXECUTION_REPORT_BALF_SIDE_TO_WIRE as SIDE,
            _EXECUTION_REPORT_BALF_STATUS_TO_WIRE as STATUS,
        )

        assert SIDE == {"BUY": codec.SIDE_BUY, "SELL": codec.SIDE_SELL}
        assert STATUS == {
            "PARTIAL": codec.STATUS_PARTIAL,
            "FILLED": codec.STATUS_FILLED,
        }

    @pytest.mark.parametrize("override", _CASES)
    def test_frames_are_byte_identical(self, override: dict[str, Any]) -> None:
        payload = {**_SAMPLE, **override}
        assert serialise_execution_report_balf(payload, seq_no=7) == _gateway_frame(
            payload
        )

    def test_the_header_carries_the_sequence_number(self) -> None:
        for seq in (0, 1, 65535, 2**32 - 1):
            frame = serialise_execution_report_balf(_SAMPLE, seq_no=seq)
            assert frame == _gateway_frame(_SAMPLE, seq_no=seq)

    def test_the_gateway_frame_parses_back(self) -> None:
        parsed = parse_execution_report_balf(_gateway_frame(_SAMPLE))
        assert parsed.order_id == _SAMPLE["order_id"]
        assert parsed.symbol == _SAMPLE["symbol"]
        assert parsed.side == "SELL"
        assert parsed.status == "FILLED"
        assert parsed.fill_price == pytest.approx(_SAMPLE["fill_price"])


class TestPythonRoundTrip:
    @pytest.mark.parametrize("override", _CASES)
    def test_serialise_then_parse(self, override: dict[str, Any]) -> None:
        payload = {**_SAMPLE, **override}
        parsed = parse_execution_report_balf(
            serialise_execution_report_balf(payload, seq_no=1)
        )
        assert parsed.to_dict() == ExecutionReport.from_dict(payload).to_dict()

    def test_frame_is_exactly_the_declared_size(self) -> None:
        frame = serialise_execution_report_balf(_SAMPLE, seq_no=1)
        assert len(frame) == FRAME_SIZE_EXECUTION_REPORT_BALF == 64

    def test_reserved_bytes_are_zero(self) -> None:
        """The normative reference says "must be zero"."""
        frame = serialise_execution_report_balf(_SAMPLE, seq_no=1)
        assert frame[8 + 50 : 8 + 56] == b"\x00" * 6

    @pytest.mark.parametrize(
        "mutate, match",
        [
            (lambda f: b"\xff" + f[1:], "magic"),
            (lambda f: f[:1] + b"\x99" + f[2:], "version"),
            (lambda f: f[:2] + b"\x11" + f[3:], "msg_type"),
            (lambda f: f[:20], "64 bytes"),
            (lambda f: f + b"\x00" * 8, "64 bytes"),
            (lambda f: f[:4], "shorter than"),
        ],
    )
    def test_a_malformed_frame_is_rejected(self, mutate: Any, match: str) -> None:
        frame = serialise_execution_report_balf(_SAMPLE, seq_no=1)
        with pytest.raises(MessageValidationError, match=match):
            parse_execution_report_balf(mutate(frame))


class TestPythonAndCAgree:
    """Capstone assertion 5."""

    @pytest.mark.parametrize("override", _CASES)
    def test_round_trip(self, harness: Path, override: dict[str, Any]) -> None:
        payload = {**_SAMPLE, **override}
        frame = serialise_execution_report_balf(payload, seq_no=7)
        c = _run(harness, frame)
        py = parse_execution_report_balf(frame)

        assert c["stage"] == "ok", c
        assert c["client_order_id"] == py.client_order_id
        assert c["order_id"] == py.order_id
        assert c["fill_qty"] == py.fill_qty
        assert c["remaining_qty"] == py.remaining_qty
        assert c["timestamp_ns"] == py.timestamp_ns
        assert c["symbol"] == py.symbol
        assert c["side"] == py.side
        assert c["status"] == py.status
        assert c["fill_price"] == pytest.approx(py.fill_price, rel=0, abs=1e-9)

    def test_a_gateway_frame_parses_in_c(self, harness: Path) -> None:
        """The end-to-end claim: gateway bytes, C client, right values."""
        c = _run(harness, _gateway_frame(_SAMPLE))
        assert c["stage"] == "ok", c
        assert c["order_id"] == _SAMPLE["order_id"]
        assert c["symbol"] == "MSFT"
        assert c["side"] == "SELL"

    @pytest.mark.parametrize(
        "mutate, rc",
        [
            (lambda f: b"\xff" + f[1:], -2),
            (lambda f: f[:1] + b"\x99" + f[2:], -3),
            (lambda f: f[:2] + b"\x11" + f[3:], -4),
            (lambda f: f[:20], -5),
            (lambda f: f + b"\x00" * 8, -5),
            (lambda f: f[:4], -1),
        ],
    )
    def test_c_rejects_the_same_malformed_frames(
        self, harness: Path, mutate: Any, rc: int
    ) -> None:
        frame = serialise_execution_report_balf(_SAMPLE, seq_no=1)
        assert _run(harness, mutate(frame))["rc"] == rc

    def test_c_enforces_the_declared_rules(self, harness: Path) -> None:
        """Design goal 5, for the binary binding."""
        payload = {**_SAMPLE, "fill_price": 0.0}
        frame = serialise_execution_report_balf(payload, seq_no=1)
        result = _run(harness, frame)
        assert result["stage"] == "validate"
        assert result["msg"] == "fill_price must be > 0"
        with pytest.raises(MessageValidationError):
            ExecutionReport.from_dict(payload).validate()


class TestTheExampleParsersMatchTheGateway:
    """The regression guard for the defect that started Phase 4b.

    ``docs/examples/balf`` is offered to customers as "a reference
    implementation". It disagreed with the gateway on six of twelve frame sizes
    — every message carrying an ``order_id``, which it modelled as a 16-byte
    string where the protocol defines a ``u64``.

    Nothing caught it because nothing compared them: the example's self-test
    checks its parser against frames the same file builds, so it agreed with
    itself perfectly while being wrong.
    """

    def _example_sizes(self, filename: str, pattern: str) -> dict[str, int]:
        text = (BALF_EXAMPLES / filename).read_text(encoding="utf-8")
        return {m.group(1): int(m.group(2)) for m in re.finditer(pattern, text)}

    def _codec_sizes(self) -> dict[str, int]:
        source = Path(codec.__file__).read_text(encoding="utf-8")
        return {
            m.group(1): int(m.group(2))
            for m in re.finditer(r"MSG_(\w+): (\d+),", source)
        }

    def test_python_example_matches_codec(self) -> None:
        expected = self._codec_sizes()
        actual = self._example_sizes("balf_parser.py", r"MSG_(\w+): (\d+),")
        assert actual == expected

    def test_c_example_matches_codec(self) -> None:
        expected = self._codec_sizes()
        actual = self._example_sizes("balf_parser.c", r"case MSG_(\w+): return (\d+);")
        assert actual == expected

    def test_the_two_examples_agree_with_each_other(self) -> None:
        assert self._example_sizes(
            "balf_parser.py", r"MSG_(\w+): (\d+),"
        ) == self._example_sizes("balf_parser.c", r"case MSG_(\w+): return (\d+);")

    def test_execution_report_is_sixty_four_bytes_everywhere(self) -> None:
        """The single number that was wrong in the shipped example."""
        assert codec.FRAME_SIZE[codec.MSG_EXECUTION_REPORT] == 64
        assert FRAME_SIZE_EXECUTION_REPORT_BALF == 64
        assert (
            self._example_sizes("balf_parser.py", r"MSG_(\w+): (\d+),")[
                "EXECUTION_REPORT"
            ]
            == 64
        )

    def test_the_c_example_uses_the_generated_binding(self) -> None:
        source = (BALF_EXAMPLES / "balf_parser.c").read_text(encoding="utf-8")
        assert "edu_execution_report_balf_parse" in source
        assert '#include "edumatcher_order.h"' in source
