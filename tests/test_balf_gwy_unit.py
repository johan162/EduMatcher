"""Unit tests for edumatcher.balf_gwy: codec, config, protocol, translate, main.

These tests exercise pure-function behaviour without sockets or ZMQ.
"""

from __future__ import annotations

import struct
import textwrap
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from edumatcher.balf_gwy.codec import (
    BALF_MAGIC,
    BALF_VERSION,
    CANCEL_REASON_CLIENT,
    CANCEL_REASON_SYSTEM,
    FRAME_SIZE,
    HEADER_SIZE,
    MSG_AMEND_ACK,
    MSG_CANCEL_ACK,
    MSG_EXECUTION_REPORT,
    MSG_HEARTBEAT,
    MSG_HEARTBEAT_ACK,
    MSG_LOGON_ACK,
    MSG_LOGOUT,
    MSG_ORDER_ACK,
    SIDE_BUY,
    SIDE_SELL,
    STATUS_FILLED,
    STATUS_PARTIAL,
    build_amend_ack,
    build_cancel_ack,
    build_execution_report,
    build_header,
    build_heartbeat,
    build_heartbeat_ack,
    build_logon_ack,
    build_logout,
    build_order_ack,
    decode_price,
    encode_price,
    now_ns,
    parse_amend_order,
    parse_cancel_order,
    parse_header,
    parse_heartbeat,
    parse_logon,
    parse_new_order,
)
from edumatcher.balf_gwy.config import (
    BalfGatewayConfig,
    load_balf_gateway_config,
    load_default_balf_gateway_config,
)
from edumatcher.balf_gwy.protocol import (
    BalfValidationError,
    RC_ATC_OUTSIDE_CLOSING,
    RC_ATO_OUTSIDE_OPENING,
    RC_GW_NOT_CONFIGURED,
    RC_GW_NOT_CONNECTED,
    RC_HALT_REJECTION,
    RC_INSUFFICIENT_LIQUIDITY,
    RC_INVALID_FIELD,
    RC_MARKET_CLOSED,
    RC_OTHER,
    RC_PHASE_REJECTION,
    RC_PRICE_COLLAR,
    RC_SYMBOL_NOT_CONFIGURED,
    RC_TRAILING_STOP_NO_PRICE,
    classify_engine_reason,
    validate_amend_flags,
    validate_new_order_price_logic,
    validate_order_type,
    validate_price_field,
    validate_quantity,
    validate_side,
    validate_smp,
    validate_symbol,
    validate_tif,
    validate_visible_qty,
)
from edumatcher.balf_gwy.translate import (
    build_engine_new_order,
    cancel_reason_from_engine,
    engine_amended_to_balf_params,
    engine_fill_to_balf_params,
    engine_side_to_balf,
    new_engine_order_id,
)
from edumatcher.models.price import clear_tick_registry

# ---------------------------------------------------------------------------
# Fixture: ensure tick registry doesn't bleed between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_tick_registry():
    yield
    clear_tick_registry()


# ===========================================================================
# Codec — frame sizes
# ===========================================================================


class TestCodecFrameSizes:
    """Every builder must produce exactly FRAME_SIZE[msg_type] bytes."""

    def test_logon_ack_accepted(self):
        assert len(build_logon_ack("GW1", accepted=True)) == FRAME_SIZE[MSG_LOGON_ACK]

    def test_logon_ack_rejected(self):
        assert (
            len(build_logon_ack("GW1", accepted=False, reject_code=1, msg="bad"))
            == FRAME_SIZE[MSG_LOGON_ACK]
        )

    def test_order_ack_accepted(self):
        frame = build_order_ack(
            client_order_id=1, balf_order_id=2, seq_no=1, accepted=True
        )
        assert len(frame) == FRAME_SIZE[MSG_ORDER_ACK]

    def test_order_ack_rejected(self):
        frame = build_order_ack(
            client_order_id=1,
            balf_order_id=0,
            seq_no=1,
            accepted=False,
            reject_code=3,
            reason="bad symbol",
        )
        assert len(frame) == FRAME_SIZE[MSG_ORDER_ACK]

    def test_cancel_ack(self):
        frame = build_cancel_ack(
            client_order_id=1, balf_order_id=2, seq_no=1, accepted=True
        )
        assert len(frame) == FRAME_SIZE[MSG_CANCEL_ACK]

    def test_amend_ack(self):
        frame = build_amend_ack(
            client_order_id=1, balf_order_id=2, seq_no=1, accepted=True
        )
        assert len(frame) == FRAME_SIZE[MSG_AMEND_ACK]

    def test_execution_report(self):
        frame = build_execution_report(
            client_order_id=1,
            balf_order_id=2,
            seq_no=1,
            fill_price=encode_price(150.0),
            fill_qty=10,
            remaining_qty=0,
            timestamp_ns=12345,
            symbol="AAPL",
            side=SIDE_BUY,
            status=STATUS_FILLED,
        )
        assert len(frame) == FRAME_SIZE[MSG_EXECUTION_REPORT]

    def test_heartbeat(self):
        assert len(build_heartbeat(seq_no=1)) == FRAME_SIZE[MSG_HEARTBEAT]

    def test_heartbeat_ack(self):
        assert len(build_heartbeat_ack(0, 1)) == FRAME_SIZE[MSG_HEARTBEAT_ACK]

    def test_logout(self):
        assert len(build_logout(seq_no=1)) == FRAME_SIZE[MSG_LOGOUT]


# ===========================================================================
# Codec — header
# ===========================================================================


class TestCodecHeader:
    def test_build_and_parse_roundtrip(self):
        raw = build_header(MSG_HEARTBEAT, seq_no=42)
        magic, msg_type, flags, seq_no = parse_header(raw)
        assert magic == BALF_MAGIC
        assert msg_type == MSG_HEARTBEAT
        assert flags == 0
        assert seq_no == 42

    def test_parse_header_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_header(b"\x00" * 3)

    def test_header_carries_magic_and_version(self):
        raw = build_header(MSG_LOGOUT, seq_no=0)
        assert raw[0] == BALF_MAGIC
        assert raw[1] == BALF_VERSION


# ===========================================================================
# Codec — price and clock
# ===========================================================================


class TestCodecPrice:
    @pytest.mark.parametrize("price", [0.01, 1.23, 150.0, 10_000.0])
    def test_encode_decode_roundtrip(self, price: float):
        assert abs(decode_price(encode_price(price)) - price) < 1e-7

    def test_encode_zero(self):
        assert encode_price(0.0) == 0

    def test_now_ns_is_positive_int(self):
        ts = now_ns()
        assert isinstance(ts, int)
        assert ts > 0


# ===========================================================================
# Codec — LOGON / LOGON_ACK
# ===========================================================================


def _make_logon_body(gw_id: str = "TRADER01", proto_ver: int = BALF_VERSION) -> bytes:
    return struct.pack(
        "<16sB7s",
        gw_id.encode("ascii"),
        proto_ver,
        b"\x00" * 7,
    )


class TestCodecLogon:
    def test_parse_logon_valid(self):
        gw_id, proto_ver = parse_logon(_make_logon_body("TRADER01"))
        assert gw_id == "TRADER01"
        assert proto_ver == BALF_VERSION

    def test_parse_logon_lowercased_input_uppercased(self):
        gw_id, _ = parse_logon(_make_logon_body("trader01"))
        assert gw_id == "TRADER01"

    def test_parse_logon_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_logon(b"\x00" * 10)

    def test_logon_ack_accepted_byte_set(self):
        frame = build_logon_ack("GW1", accepted=True, msg="welcome")
        # body[16] = accepted
        assert frame[HEADER_SIZE + 16] == 1

    def test_logon_ack_rejected_byte_clear(self):
        frame = build_logon_ack("GW1", accepted=False, reject_code=0x01)
        assert frame[HEADER_SIZE + 16] == 0
        assert frame[HEADER_SIZE + 17] == 0x01

    def test_logon_ack_msg_truncated_to_64(self):
        long_msg = "x" * 100
        frame = build_logon_ack("GW1", accepted=True, msg=long_msg)
        assert len(frame) == FRAME_SIZE[MSG_LOGON_ACK]


# ===========================================================================
# Codec — NEW_ORDER
# ===========================================================================


def _make_new_order_body(
    client_order_id: int = 1,
    symbol: str = "AAPL",
    price: int = 0,
    stop_price: int = 0,
    trail_offset: int = 0,
    quantity: int = 100,
    visible_qty: int = 0,
    side: int = SIDE_BUY,
    order_type: int = 0x02,
    tif: int = 0x01,
    smp: int = 0x00,
) -> bytes:
    return struct.pack(
        "<Q8sqqqIIBBBB",
        client_order_id,
        symbol.encode("ascii"),
        price,
        stop_price,
        trail_offset,
        quantity,
        visible_qty,
        side,
        order_type,
        tif,
        smp,
    )


class TestCodecNewOrder:
    def test_parse_valid_limit(self):
        body = _make_new_order_body(price=encode_price(150.0))
        parsed = parse_new_order(body)
        assert parsed["symbol"] == "AAPL"
        assert parsed["side"] == SIDE_BUY
        assert parsed["order_type"] == 0x02
        assert parsed["quantity"] == 100
        assert parsed["price"] == encode_price(150.0)

    def test_parse_symbol_uppercased(self):
        body = _make_new_order_body(symbol="aapl")
        parsed = parse_new_order(body)
        assert parsed["symbol"] == "AAPL"

    def test_parse_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_new_order(b"\x00" * 10)


# ===========================================================================
# Codec — ORDER_ACK
# ===========================================================================


class TestCodecOrderAck:
    def test_accepted_byte(self):
        frame = build_order_ack(
            client_order_id=99, balf_order_id=1, seq_no=5, accepted=True
        )
        # body: Q+Q+Q = 24 bytes → accepted at offset 24
        assert frame[HEADER_SIZE + 24] == 1

    def test_rejected_reject_code(self):
        frame = build_order_ack(
            client_order_id=99,
            balf_order_id=0,
            seq_no=5,
            accepted=False,
            reject_code=0x03,
            reason="sym not cfg",
        )
        assert frame[HEADER_SIZE + 24] == 0
        assert frame[HEADER_SIZE + 25] == 0x03


# ===========================================================================
# Codec — CANCEL_ORDER / CANCEL_ACK
# ===========================================================================


class TestCodecCancel:
    def test_parse_cancel_order_valid(self):
        body = struct.pack("<QQ", 42, 7)
        client_id, order_id = parse_cancel_order(body)
        assert client_id == 42
        assert order_id == 7

    def test_parse_cancel_order_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_cancel_order(b"\x00" * 5)

    def test_cancel_ack_accepted(self):
        frame = build_cancel_ack(
            client_order_id=1,
            balf_order_id=2,
            seq_no=1,
            accepted=True,
            cancel_reason=CANCEL_REASON_CLIENT,
        )
        # body: Q+Q = 16 → accepted at offset 16
        assert frame[HEADER_SIZE + 16] == 1
        assert frame[HEADER_SIZE + 17] == CANCEL_REASON_CLIENT

    def test_cancel_ack_rejected(self):
        frame = build_cancel_ack(
            client_order_id=1, balf_order_id=2, seq_no=1, accepted=False
        )
        assert frame[HEADER_SIZE + 16] == 0

    def test_cancel_ack_system_reason(self):
        frame = build_cancel_ack(
            client_order_id=1,
            balf_order_id=2,
            seq_no=1,
            accepted=True,
            cancel_reason=CANCEL_REASON_SYSTEM,
        )
        assert frame[HEADER_SIZE + 17] == CANCEL_REASON_SYSTEM


# ===========================================================================
# Codec — AMEND_ORDER / AMEND_ACK
# ===========================================================================


class TestCodecAmend:
    def _make_amend_body(
        self,
        client_order_id: int = 3,
        balf_order_id: int = 7,
        new_price: int = encode_price(200.0),
        new_quantity: int = 50,
        amend_flags: int = 0x01,
    ) -> bytes:
        return struct.pack(
            "<QQqIBxxxxxxx",
            client_order_id,
            balf_order_id,
            new_price,
            new_quantity,
            amend_flags,
        )

    def test_parse_amend_order_valid(self):
        body = self._make_amend_body()
        parsed = parse_amend_order(body)
        assert parsed["client_order_id"] == 3
        assert parsed["balf_order_id"] == 7
        assert parsed["new_quantity"] == 50
        assert parsed["amend_flags"] == 0x01

    def test_parse_amend_order_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_amend_order(b"\x00" * 10)

    def test_amend_ack_accepted(self):
        frame = build_amend_ack(
            client_order_id=1,
            balf_order_id=2,
            seq_no=1,
            accepted=True,
            new_price=encode_price(200.0),
            new_quantity=50,
            remaining_qty=50,
        )
        assert len(frame) == FRAME_SIZE[MSG_AMEND_ACK]
        # body: Q+Q+q+I+I = 32 bytes → accepted at offset 32
        assert frame[HEADER_SIZE + 32] == 1

    def test_amend_ack_rejected(self):
        frame = build_amend_ack(
            client_order_id=1, balf_order_id=2, seq_no=1, accepted=False
        )
        assert frame[HEADER_SIZE + 32] == 0


# ===========================================================================
# Codec — EXECUTION_REPORT
# ===========================================================================


class TestCodecExecutionReport:
    def test_partial_fill(self):
        frame = build_execution_report(
            client_order_id=1,
            balf_order_id=2,
            seq_no=1,
            fill_price=encode_price(150.0),
            fill_qty=50,
            remaining_qty=50,
            timestamp_ns=1_000_000,
            symbol="AAPL",
            side=SIDE_BUY,
            status=STATUS_PARTIAL,
        )
        assert len(frame) == FRAME_SIZE[MSG_EXECUTION_REPORT]
        # side at HEADER + Q+Q+q+I+I+Q+8s = 8+8+8+4+4+8+8 = 48
        assert frame[HEADER_SIZE + 48] == SIDE_BUY
        assert frame[HEADER_SIZE + 49] == STATUS_PARTIAL

    def test_full_fill_side_sell(self):
        frame = build_execution_report(
            client_order_id=1,
            balf_order_id=2,
            seq_no=1,
            fill_price=encode_price(99.5),
            fill_qty=100,
            remaining_qty=0,
            timestamp_ns=0,
            symbol="MSFT",
            side=SIDE_SELL,
            status=STATUS_FILLED,
        )
        assert frame[HEADER_SIZE + 48] == SIDE_SELL
        assert frame[HEADER_SIZE + 49] == STATUS_FILLED


# ===========================================================================
# Codec — HEARTBEAT / HEARTBEAT_ACK / LOGOUT
# ===========================================================================


class TestCodecHeartbeatLogout:
    def test_heartbeat_parse_roundtrip(self):
        ts = 1_234_567_890_123_456_789
        frame = build_heartbeat(seq_no=3, send_time_ns=ts)
        recovered = parse_heartbeat(frame[HEADER_SIZE:])
        assert recovered == ts

    def test_heartbeat_uses_now_when_zero(self):
        before = now_ns()
        frame = build_heartbeat(seq_no=1)
        after = now_ns()
        ts = parse_heartbeat(frame[HEADER_SIZE:])
        assert before <= ts <= after

    def test_parse_heartbeat_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_heartbeat(b"\x00" * 3)

    def test_heartbeat_ack_size(self):
        frame = build_heartbeat_ack(orig_send_time_ns=9876, seq_no=5)
        assert len(frame) == FRAME_SIZE[MSG_HEARTBEAT_ACK]

    def test_logout_is_header_only(self):
        frame = build_logout(seq_no=7)
        assert len(frame) == FRAME_SIZE[MSG_LOGOUT] == HEADER_SIZE


# ===========================================================================
# Config
# ===========================================================================


class TestBalfGatewayConfigDefaults:
    def test_default_port(self):
        assert BalfGatewayConfig().port == 5560

    def test_default_heartbeat_interval(self):
        assert BalfGatewayConfig().heartbeat_interval_sec == 1.0

    def test_default_dup_policy(self):
        assert BalfGatewayConfig().duplicate_session_policy == "REJECT_NEW"

    def test_default_gateway_roles_empty(self):
        assert BalfGatewayConfig().gateway_roles == ()


class TestLoadBalfGatewayConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path):
        cfg = load_balf_gateway_config(tmp_path / "nonexistent.yaml")
        assert cfg.port == 5560

    def test_empty_yaml_returns_defaults(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("{}\n")
        assert load_balf_gateway_config(p).port == 5560

    def test_non_dict_yaml_returns_defaults(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("- list\n- item\n")
        assert load_balf_gateway_config(p).port == 5560

    def test_full_config_parsed(self, tmp_path: Path):
        yaml_text = textwrap.dedent("""\
            balf_gateway:
              enabled: true
              name: my-gw
              port: 9999
              max_connections: 32
              max_messages_per_second: 200
              duplicate_session_policy: EVICT_OLD
            gateways:
              alf:
                - id: GW1
                  role: TRADER
                - id: GW2
                  role: MARKET_MAKER
        """)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml_text)
        cfg = load_balf_gateway_config(p)
        assert cfg.port == 9999
        assert cfg.name == "my-gw"
        assert cfg.max_connections == 32
        assert cfg.duplicate_session_policy == "EVICT_OLD"
        assert cfg.gateway_roles == (("GW1", "TRADER"), ("GW2", "MARKET_MAKER"))

    def test_invalid_port_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  port: 99999\n")
        with pytest.raises(ValueError, match="port"):
            load_balf_gateway_config(p)

    def test_port_zero_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  port: 0\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_invalid_dup_policy_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  duplicate_session_policy: UNKNOWN\n")
        with pytest.raises(ValueError, match="duplicate_session_policy"):
            load_balf_gateway_config(p)

    def test_max_connections_zero_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  max_connections: 0\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_max_client_queue_zero_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  max_client_queue: 0\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_max_mps_zero_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  max_messages_per_second: 0\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_max_errors_zero_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  max_errors_before_disconnect: 0\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_non_dict_section_raises(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway: not_a_dict\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_bool_port_raises(self, tmp_path: Path):
        # bool is a subclass of int in Python; _as_int should reject it
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  port: true\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_gateway_roles_prefix_collision_raises(self, tmp_path: Path):
        yaml_text = textwrap.dedent("""\
            gateways:
              alf:
                - id: GW
                  role: TRADER
                - id: GW1
                  role: TRADER
        """)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml_text)
        with pytest.raises(ValueError, match="prefix"):
            load_balf_gateway_config(p)

    def test_gateway_roles_missing_id_raises(self, tmp_path: Path):
        yaml_text = textwrap.dedent("""\
            gateways:
              alf:
                - role: TRADER
        """)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml_text)
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_gateway_roles_non_dict_item_raises(self, tmp_path: Path):
        yaml_text = textwrap.dedent("""\
            gateways:
              alf:
                - not_a_dict
        """)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml_text)
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_no_alf_section_returns_empty_roles(self, tmp_path: Path):
        yaml_text = "gateways:\n  ralf:\n    - id: RGW\n"
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml_text)
        cfg = load_balf_gateway_config(p)
        assert cfg.gateway_roles == ()

    def test_load_default_does_not_raise(self):
        cfg = load_default_balf_gateway_config()
        assert isinstance(cfg, BalfGatewayConfig)

    def test_float_timeout_accepted(self, tmp_path: Path):
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  heartbeat_interval_sec: 2.5\n")
        cfg = load_balf_gateway_config(p)
        assert cfg.heartbeat_interval_sec == 2.5

    def test_null_port_raises(self, tmp_path: Path):
        # YAML null becomes Python None which is not int/float/str → line 59
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  port: null\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_string_port_invalid_raises(self, tmp_path: Path):
        # String that cannot be converted to int → lines 62-63
        p = tmp_path / "cfg.yaml"
        p.write_text('balf_gateway:\n  port: "abc"\n')
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_null_timeout_raises(self, tmp_path: Path):
        # null in YAML for a float field → lines 69-70
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  heartbeat_interval_sec: null\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)

    def test_negative_timeout_raises(self, tmp_path: Path):
        # _as_float raises on val <= 0 → line 72
        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  heartbeat_interval_sec: -1\n")
        with pytest.raises(ValueError):
            load_balf_gateway_config(p)


# ===========================================================================
# Protocol — classify_engine_reason
# ===========================================================================


@pytest.mark.parametrize(
    "reason,expected_rc",
    [
        ("Gateway not configured: GW1", RC_GW_NOT_CONFIGURED),
        ("Gateway not connected: GW1", RC_GW_NOT_CONNECTED),
        ("Symbol not configured: AAPL", RC_SYMBOL_NOT_CONFIGURED),
        ("Market is closed", RC_MARKET_CLOSED),
        ("ATO orders only accepted during opening auction", RC_ATO_OUTSIDE_OPENING),
        ("ATC orders only accepted during closing auction", RC_ATC_OUTSIDE_CLOSING),
        ("all orders rejected during circuit breaker halt", RC_HALT_REJECTION),
        ("orders not accepted during pre-open phase", RC_PHASE_REJECTION),
        (
            "Trailing stop requires STOP= or a prior trade price",
            RC_TRAILING_STOP_NO_PRICE,
        ),
        ("Insufficient liquidity", RC_INSUFFICIENT_LIQUIDITY),
        ("price collar breach detected", RC_PRICE_COLLAR),
        ("some unknown error xyz", RC_OTHER),
    ],
)
def test_classify_engine_reason(reason: str, expected_rc: int):
    assert classify_engine_reason(reason) == expected_rc


# ===========================================================================
# Protocol — field validators
# ===========================================================================


class TestValidateSide:
    def test_buy(self):
        assert validate_side(0x01) == "BUY"

    def test_sell(self):
        assert validate_side(0x02) == "SELL"

    def test_invalid_raises(self):
        with pytest.raises(BalfValidationError) as exc_info:
            validate_side(0x99)
        assert exc_info.value.reject_code == RC_INVALID_FIELD


class TestValidateOrderType:
    @pytest.mark.parametrize(
        "code,expected",
        [(0x01, "MARKET"), (0x02, "LIMIT"), (0x05, "STOP"), (0x08, "TRAILING_STOP")],
    )
    def test_valid(self, code: int, expected: str):
        assert validate_order_type(code) == expected

    def test_invalid_raises(self):
        with pytest.raises(BalfValidationError):
            validate_order_type(0xFF)


class TestValidateTif:
    @pytest.mark.parametrize(
        "code,expected",
        [(0x01, "DAY"), (0x02, "GTC"), (0x03, "ATO"), (0x04, "ATC")],
    )
    def test_valid(self, code: int, expected: str):
        assert validate_tif(code) == expected

    def test_invalid_raises(self):
        with pytest.raises(BalfValidationError):
            validate_tif(0x99)


class TestValidateSmp:
    def test_none(self):
        assert validate_smp(0x00) == "NONE"

    def test_invalid_raises(self):
        with pytest.raises(BalfValidationError):
            validate_smp(0x99)


class TestValidateQuantity:
    def test_valid(self):
        validate_quantity(100)

    def test_zero_raises(self):
        with pytest.raises(BalfValidationError):
            validate_quantity(0)

    def test_negative_raises(self):
        with pytest.raises(BalfValidationError):
            validate_quantity(-1)

    def test_too_large_raises(self):
        with pytest.raises(BalfValidationError):
            validate_quantity(3_000_000_000)


class TestValidateVisibleQty:
    def test_valid(self):
        validate_visible_qty(50, 100)

    def test_zero_raises(self):
        with pytest.raises(BalfValidationError):
            validate_visible_qty(0, 100)

    def test_equal_to_quantity_raises(self):
        with pytest.raises(BalfValidationError):
            validate_visible_qty(100, 100)


class TestValidatePriceField:
    def test_nonzero_ok(self):
        validate_price_field(1, "price")

    def test_zero_raises(self):
        with pytest.raises(BalfValidationError):
            validate_price_field(0, "price")


class TestValidateSymbol:
    def test_valid(self):
        validate_symbol("AAPL")

    def test_empty_raises(self):
        with pytest.raises(BalfValidationError):
            validate_symbol("")

    def test_too_long_raises(self):
        with pytest.raises(BalfValidationError):
            validate_symbol("TOOLONGSYM")

    def test_non_alnum_raises(self):
        with pytest.raises(BalfValidationError):
            validate_symbol("AA.PL")


class TestValidateNewOrderPriceLogic:
    def _parsed(self, ot: str, **kw) -> dict:
        return {
            "order_type_str": ot,
            "price": kw.get("price", 0),
            "stop_price": kw.get("stop_price", 0),
            "trail_offset": kw.get("trail_offset", 0),
            "visible_qty": kw.get("visible_qty", 0),
            "quantity": kw.get("quantity", 100),
        }

    def test_limit_requires_price(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("LIMIT"))

    def test_limit_with_price_ok(self):
        validate_new_order_price_logic(self._parsed("LIMIT", price=100))

    def test_market_no_price_ok(self):
        validate_new_order_price_logic(self._parsed("MARKET"))

    def test_ioc_requires_price(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("IOC"))

    def test_fok_requires_price(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("FOK"))

    def test_stop_requires_stop_price(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("STOP"))

    def test_stop_with_stop_price_ok(self):
        validate_new_order_price_logic(self._parsed("STOP", stop_price=100))

    def test_stop_limit_missing_stop_price_raises(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("STOP_LIMIT"))

    def test_stop_limit_missing_limit_price_raises(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("STOP_LIMIT", stop_price=100))

    def test_stop_limit_both_ok(self):
        validate_new_order_price_logic(
            self._parsed("STOP_LIMIT", stop_price=100, price=95)
        )

    def test_iceberg_missing_price_raises(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(
                self._parsed("ICEBERG", visible_qty=20, quantity=100)
            )

    def test_iceberg_missing_visible_raises(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(
                self._parsed("ICEBERG", price=100, visible_qty=0, quantity=100)
            )

    def test_iceberg_valid(self):
        validate_new_order_price_logic(
            self._parsed("ICEBERG", price=100, visible_qty=20, quantity=100)
        )

    def test_trailing_stop_requires_offset(self):
        with pytest.raises(BalfValidationError):
            validate_new_order_price_logic(self._parsed("TRAILING_STOP"))

    def test_trailing_stop_with_offset_ok(self):
        validate_new_order_price_logic(self._parsed("TRAILING_STOP", trail_offset=100))


class TestValidateAmendFlags:
    @pytest.mark.parametrize("flags", [0x01, 0x02, 0x03])
    def test_valid_flags(self, flags: int):
        validate_amend_flags(flags)

    def test_zero_flags_raises(self):
        with pytest.raises(BalfValidationError):
            validate_amend_flags(0x00)


# ===========================================================================
# Translate
# ===========================================================================


class TestBuildEngineNewOrder:
    def _limit_parsed(self, symbol: str = "AAPL") -> dict:
        return {
            "client_order_id": 1,
            "symbol": symbol,
            "price": encode_price(150.0),
            "stop_price": 0,
            "trail_offset": 0,
            "quantity": 100,
            "visible_qty": 0,
            "side": SIDE_BUY,
            "order_type": 0x02,  # LIMIT
            "tif": 0x01,  # DAY
            "smp": 0x00,  # NONE
        }

    def test_limit_order_core_fields(self):
        order = build_engine_new_order(self._limit_parsed(), "TRADER01", "uuid-1")
        assert order["symbol"] == "AAPL"
        assert order["side"] == "BUY"
        assert order["order_type"] == "LIMIT"
        assert order["tif"] == "DAY"
        assert order["quantity"] == 100
        assert order["gateway_id"] == "TRADER01"
        assert order["id"] == "uuid-1"
        assert "price" in order

    def test_market_order_no_price_field(self):
        parsed = {
            **self._limit_parsed(),
            "price": 0,
            "order_type": 0x01,  # MARKET
        }
        order = build_engine_new_order(parsed, "GW1", "uuid-2")
        assert order["order_type"] == "MARKET"
        assert "price" not in order

    def test_stop_order_stop_price_in_result(self):
        parsed = {
            "client_order_id": 3,
            "symbol": "AAPL",
            "price": 0,
            "stop_price": encode_price(145.0),
            "trail_offset": 0,
            "quantity": 20,
            "visible_qty": 0,
            "side": SIDE_BUY,
            "order_type": 0x05,  # STOP
            "tif": 0x01,
            "smp": 0x00,
        }
        order = build_engine_new_order(parsed, "GW1", "uuid-3")
        assert "stop_price" in order

    def test_trailing_stop_trail_offset_in_result(self):
        parsed = {
            "client_order_id": 4,
            "symbol": "AAPL",
            "price": 0,
            "stop_price": 0,
            "trail_offset": encode_price(2.5),
            "quantity": 30,
            "visible_qty": 0,
            "side": SIDE_BUY,
            "order_type": 0x08,  # TRAILING_STOP
            "tif": 0x01,
            "smp": 0x00,
        }
        order = build_engine_new_order(parsed, "GW1", "uuid-ts")
        assert order["order_type"] == "TRAILING_STOP"
        assert "trail_offset" in order

    def test_invalid_side_raises(self):
        parsed = {**self._limit_parsed(), "side": 0x99}
        with pytest.raises(BalfValidationError):
            build_engine_new_order(parsed, "GW1", "uuid-4")

    def test_invalid_order_type_raises(self):
        parsed = {**self._limit_parsed(), "order_type": 0xFF}
        with pytest.raises(BalfValidationError):
            build_engine_new_order(parsed, "GW1", "uuid-5")

    def test_empty_symbol_raises(self):
        parsed = {**self._limit_parsed(), "symbol": ""}
        with pytest.raises(BalfValidationError):
            build_engine_new_order(parsed, "GW1", "uuid-6")

    def test_zero_quantity_raises(self):
        parsed = {**self._limit_parsed(), "quantity": 0}
        with pytest.raises(BalfValidationError):
            build_engine_new_order(parsed, "GW1", "uuid-7")

    def test_sell_side_and_smp_forwarded(self):
        parsed = {**self._limit_parsed(), "side": SIDE_SELL, "smp": 0x01}
        order = build_engine_new_order(parsed, "GW1", "uuid-8")
        assert order["side"] == "SELL"
        assert order["smp_action"] == "CANCEL_AGGRESSOR"

    def test_iceberg_visible_qty_included(self):
        parsed = {
            **self._limit_parsed(),
            "order_type": 0x07,  # ICEBERG
            "visible_qty": 20,
        }
        order = build_engine_new_order(parsed, "GW1", "uuid-9")
        assert order.get("visible_qty") == 20


class TestEngineEventTranslations:
    def test_engine_side_buy(self):
        assert engine_side_to_balf("BUY") == SIDE_BUY

    def test_engine_side_sell(self):
        assert engine_side_to_balf("SELL") == SIDE_SELL

    def test_engine_side_unknown_is_sell(self):
        assert engine_side_to_balf("UNKNOWN") == SIDE_SELL

    def test_fill_partial(self):
        payload = {
            "fill_price": 150.0,
            "fill_qty": 50,
            "remaining_qty": 50,
            "status": "PARTIAL",
            "symbol": "AAPL",
            "side": "BUY",
            "timestamp": 999,
        }
        p = engine_fill_to_balf_params(payload, balf_order_id=1, client_order_id=2)
        assert p["fill_qty"] == 50
        assert p["status"] == STATUS_PARTIAL
        assert p["side"] == SIDE_BUY
        assert p["fill_price"] == encode_price(150.0)

    def test_fill_fully_filled(self):
        payload = {
            "fill_price": 99.0,
            "fill_qty": 100,
            "remaining_qty": 0,
            "status": "FILLED",
            "symbol": "MSFT",
            "side": "SELL",
            "fill_timestamp": 1234,
        }
        p = engine_fill_to_balf_params(payload, balf_order_id=3, client_order_id=4)
        assert p["status"] == STATUS_FILLED
        assert p["side"] == SIDE_SELL

    def test_fill_missing_fields_tolerated(self):
        p = engine_fill_to_balf_params({}, balf_order_id=1, client_order_id=1)
        assert p["fill_qty"] == 0
        assert p["status"] == STATUS_PARTIAL  # default

    def test_amended_params(self):
        payload = {
            "price": 155.0,
            "qty": 80,
            "remaining_qty": 80,
            "priority_reset": True,
        }
        p = engine_amended_to_balf_params(
            payload, balf_order_id=1, client_order_id=2, symbol="AAPL"
        )
        assert p["accepted"] is True
        assert p["new_quantity"] == 80
        assert p["priority_reset"] is True
        assert p["new_price"] == encode_price(155.0)

    def test_amended_no_price(self):
        payload = {"qty": 50, "remaining_qty": 50, "priority_reset": False}
        p = engine_amended_to_balf_params(
            payload, balf_order_id=1, client_order_id=2, symbol="AAPL"
        )
        assert p["new_price"] == 0

    def test_cancel_reason_is_client(self):
        assert cancel_reason_from_engine({}) == CANCEL_REASON_CLIENT

    def test_new_engine_order_id_unique(self):
        ids = {new_engine_order_id() for _ in range(20)}
        assert len(ids) == 20

    def test_new_engine_order_id_is_string(self):
        oid = new_engine_order_id()
        assert isinstance(oid, str)
        assert len(oid) > 0


# ===========================================================================
# Main — CLI and config resolution
# ===========================================================================


class TestMain:
    def test_parser_has_config_arg(self):
        from edumatcher.balf_gwy.main import _build_parser

        args = _build_parser().parse_args(["--config", "/tmp/x.yaml"])
        assert args.config == "/tmp/x.yaml"

    def test_parser_has_bind_and_port(self):
        from edumatcher.balf_gwy.main import _build_parser

        args = _build_parser().parse_args(["--bind", "127.0.0.1", "--port", "9999"])
        assert args.bind == "127.0.0.1"
        assert args.port == 9999

    def test_parser_has_engine_host(self):
        from edumatcher.balf_gwy.main import _build_parser

        args = _build_parser().parse_args(["--engine-host", "10.0.0.1"])
        assert args.engine_host == "10.0.0.1"

    def test_parser_has_log_level(self):
        from edumatcher.balf_gwy.main import _build_parser

        args = _build_parser().parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_parser_has_verbose_and_quiet(self):
        from edumatcher.balf_gwy.main import _build_parser

        args = _build_parser().parse_args(["-vv", "--quiet"])
        assert args.verbose == 2
        assert args.quiet is True

    def test_configure_logging_prefers_explicit_level(self):
        from edumatcher.balf_gwy.main import _configure_logging

        args = Namespace(log_level="INFO", verbose=2, quiet=True)
        assert _configure_logging(args) == 20

    def test_resolve_config_bind_port_override(self, tmp_path: Path):
        from edumatcher.balf_gwy.main import _resolve_config

        p = tmp_path / "cfg.yaml"
        p.write_text("{}\n")
        args = Namespace(config=str(p), bind="127.0.0.1", port=8888, engine_host=None)
        cfg = _resolve_config(args)
        assert cfg.bind_address == "127.0.0.1"
        assert cfg.port == 8888

    def test_resolve_config_engine_host_override(self, tmp_path: Path):
        from edumatcher.balf_gwy.main import _resolve_config

        p = tmp_path / "cfg.yaml"
        p.write_text("{}\n")
        args = Namespace(config=str(p), bind=None, port=None, engine_host="192.168.1.1")
        cfg = _resolve_config(args)
        assert "192.168.1.1" in cfg.engine_pull_addr
        assert "192.168.1.1" in cfg.engine_pub_addr

    def test_resolve_config_no_overrides(self, tmp_path: Path):
        from edumatcher.balf_gwy.main import _resolve_config

        p = tmp_path / "cfg.yaml"
        p.write_text("{}\n")
        args = Namespace(config=str(p), bind=None, port=None, engine_host=None)
        cfg = _resolve_config(args)
        assert isinstance(cfg, BalfGatewayConfig)

    def test_main_disabled_config_exits(self, tmp_path: Path):
        from edumatcher.balf_gwy.main import main

        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  enabled: false\n")
        with patch("sys.argv", ["pm-balf-gwy", "--config", str(p)]):
            with pytest.raises(SystemExit):
                main()

    def test_main_bad_config_exits(self, tmp_path: Path):
        from edumatcher.balf_gwy.main import main

        p = tmp_path / "cfg.yaml"
        p.write_text("balf_gateway:\n  port: 99999\n")
        with patch("sys.argv", ["pm-balf-gwy", "--config", str(p)]):
            with pytest.raises(SystemExit):
                main()
