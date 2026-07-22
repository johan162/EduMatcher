"""
Tests for edumatcher.index.admin_cli (pm-index-admin-cli).

Strategy
--------
Two layers, matching the pattern already used in tests/test_commands.py:

1.  Pure unit tests for client-side validators (_parse_ratio,
    _require_positive, _require_positive_int) — no ZMQ dependency.
2.  Handler-level tests that build an ExchangeCommandClient in injection
    mode (a _FakePush + a pre-loaded _recv_queue), then call the
    subcommand handler functions (_cmd_split, _cmd_dividend, ...)
    directly with a parsed argparse.Namespace. This exercises the full
    "parse args -> validate -> build message -> send -> report" path
    without opening a real socket or running pm-index.

Confirmation prompts are bypassed everywhere via args.yes=True (or --yes
in argparse-level tests) so tests never block on stdin.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pytest

from edumatcher.commands import CommandError, CommandTimeoutError, ExchangeCommandClient
from edumatcher.index import admin_cli
from edumatcher.models.message import (
    decode,
    make_index_constituent_change_ack_msg,
    make_index_corp_action_ack_msg,
    make_index_error_msg,
    make_index_history_msg,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakePush:
    sent: list[list[bytes]] = field(default_factory=list)

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass


def _q(*frames_list: list[bytes]) -> deque[list[bytes]]:
    return deque(frames_list)


def _client(
    gw_id: str = "OPS01", recv_queue: deque[list[bytes]] | None = None
) -> tuple[ExchangeCommandClient, _FakePush]:
    push = _FakePush()
    client = ExchangeCommandClient(
        gw_id,
        _push_sock=push,
        _sub_sock=None,
        _recv_queue=recv_queue or deque(),
    )
    return client, push


def _last_sent(push: _FakePush) -> tuple[str, dict[str, Any]]:
    return decode(push.sent[-1])


def _ns(**kwargs: Any) -> argparse.Namespace:
    """Build a minimal argparse.Namespace with the global defaults set."""
    base = {
        "id": "OPS01",
        "dry_run": False,
        "yes": True,
        "format": "table",
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# Argument parser — argparse-level surface tests
# ---------------------------------------------------------------------------


class TestArgumentParser:
    def test_help_lists_all_subcommands(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = admin_cli._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])
        out = capsys.readouterr().out
        for cmd in ("split", "dividend", "shares", "add", "delist", "history"):
            assert cmd in out

    def test_id_is_required(self) -> None:
        parser = admin_cli._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["split", "--index", "TECH10", "--sym", "AAPL", "--ratio", "4:1"]
            )

    def test_command_is_required(self) -> None:
        parser = admin_cli._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--id", "OPS01"])

    def test_split_parses_flags(self) -> None:
        parser = admin_cli._build_parser()
        args = parser.parse_args(
            [
                "--id",
                "OPS01",
                "split",
                "--index",
                "TECH10",
                "--sym",
                "AAPL",
                "--ratio",
                "4:1",
            ]
        )
        assert args.command == "split"
        assert args.index == "TECH10"
        assert args.sym == "AAPL"
        assert args.ratio == "4:1"

    def test_shares_new_shares_and_delta_are_mutually_exclusive(self) -> None:
        parser = admin_cli._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--id",
                    "OPS01",
                    "shares",
                    "--index",
                    "TECH10",
                    "--sym",
                    "AAPL",
                    "--new-shares",
                    "100",
                    "--delta",
                    "-5",
                ]
            )

    def test_shares_requires_one_of_new_shares_or_delta(self) -> None:
        parser = admin_cli._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["--id", "OPS01", "shares", "--index", "TECH10", "--sym", "AAPL"]
            )

    def test_default_format_is_table(self) -> None:
        parser = admin_cli._build_parser()
        args = parser.parse_args(
            ["--id", "OPS01", "delist", "--index", "TECH10", "--sym", "XYZ"]
        )
        assert args.format == "table"

    def test_format_json_accepted(self) -> None:
        parser = admin_cli._build_parser()
        args = parser.parse_args(
            [
                "--id",
                "OPS01",
                "--format",
                "json",
                "delist",
                "--index",
                "TECH10",
                "--sym",
                "XYZ",
            ]
        )
        assert args.format == "json"

    def test_invalid_format_rejected(self) -> None:
        parser = admin_cli._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--id",
                    "OPS01",
                    "--format",
                    "xml",
                    "delist",
                    "--index",
                    "TECH10",
                    "--sym",
                    "XYZ",
                ]
            )


# ---------------------------------------------------------------------------
# Client-side validators
# ---------------------------------------------------------------------------


class TestParseRatio:
    def test_valid_ratio(self) -> None:
        assert admin_cli._parse_ratio("4:1") == (4, 1)

    def test_reverse_split_ratio(self) -> None:
        assert admin_cli._parse_ratio("1:10") == (1, 10)

    def test_missing_colon_rejected(self) -> None:
        with pytest.raises(ValueError, match="N:M form"):
            admin_cli._parse_ratio("4")

    def test_non_integer_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be integers"):
            admin_cli._parse_ratio("four:one")

    def test_zero_numerator_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            admin_cli._parse_ratio("0:1")

    def test_zero_denominator_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            admin_cli._parse_ratio("1:0")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            admin_cli._parse_ratio("-4:1")


class TestRequirePositive:
    def test_positive_ok(self) -> None:
        admin_cli._require_positive(0.75, "--amount")  # no raise

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="--amount"):
            admin_cli._require_positive(0.0, "--amount")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="--amount"):
            admin_cli._require_positive(-1.0, "--amount")


class TestRequirePositiveInt:
    def test_positive_ok(self) -> None:
        admin_cli._require_positive_int(100, "--shares")  # no raise

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="--shares"):
            admin_cli._require_positive_int(0, "--shares")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="--shares"):
            admin_cli._require_positive_int(-5, "--shares")


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


class TestCmdSplit:
    def test_accepted_sends_correct_frames_and_reports(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8452.17,
                    divisor=118.3352,
                )
            )
        )
        args = _ns(command="split", index="tech10", sym="aapl", ratio="4:1")
        ok = admin_cli._cmd_split(client, args)

        topic, payload = _last_sent(push)
        assert topic == "index.corp_action"
        assert payload["action"] == "SPLIT"
        assert payload["index_id"] == "TECH10"
        assert payload["symbol"] == "AAPL"
        assert payload["ratio_numerator"] == 4
        assert payload["ratio_denominator"] == 1
        assert ok is True
        out = capsys.readouterr().out
        assert "SPLIT OK" in out
        assert "TECH10" in out
        assert "AAPL" in out

    def test_rejected_reports_reason(self, capsys: pytest.CaptureFixture[str]) -> None:
        client, _push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=False,
                    reason="Unknown symbol 'XYZ'",
                    index_id="TECH10",
                )
            )
        )
        args = _ns(command="split", index="tech10", sym="xyz", ratio="4:1")
        ok = admin_cli._cmd_split(client, args)
        assert ok is False
        out = capsys.readouterr().out
        assert "REJECTED" in out
        assert "Unknown symbol" in out

    def test_bad_ratio_raises_before_send(self) -> None:
        client, push = _client()
        args = _ns(command="split", index="tech10", sym="aapl", ratio="bad")
        with pytest.raises(ValueError):
            admin_cli._cmd_split(client, args)
        assert push.sent == []

    def test_dry_run_does_not_send(self, capsys: pytest.CaptureFixture[str]) -> None:
        client, push = _client()
        args = _ns(
            command="split", index="tech10", sym="aapl", ratio="4:1", dry_run=True
        )
        ok = admin_cli._cmd_split(client, args)
        assert ok is True
        assert push.sent == []
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert '"action": "SPLIT"' in out

    def test_json_format_prints_raw_ack(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, _push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8452.17,
                    divisor=118.3352,
                )
            )
        )
        args = _ns(
            command="split", index="tech10", sym="aapl", ratio="4:1", format="json"
        )
        ok = admin_cli._cmd_split(client, args)
        assert ok is True
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["accepted"] is True
        assert parsed["index_id"] == "TECH10"

    def test_confirmation_declined_does_not_send(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, push = _client()
        monkeypatch.setattr(admin_cli, "_confirm", lambda *_a, **_k: False)
        args = _ns(command="split", index="tech10", sym="aapl", ratio="4:1", yes=False)
        ok = admin_cli._cmd_split(client, args)
        assert ok is False
        assert push.sent == []


# ---------------------------------------------------------------------------
# dividend
# ---------------------------------------------------------------------------


class TestCmdDividend:
    def test_accepted_sends_correct_frames(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8447.61,
                    divisor=118.3352,
                )
            )
        )
        args = _ns(command="dividend", index="tech10", sym="msft", amount=0.75)
        ok = admin_cli._cmd_dividend(client, args)

        topic, payload = _last_sent(push)
        assert topic == "index.corp_action"
        assert payload["action"] == "CASH_DIVIDEND"
        assert payload["dividend_per_share"] == 0.75
        assert ok is True

    def test_rejected_when_price_would_go_non_positive(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, _push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=False,
                    reason="Resulting price for MSFT would be non-positive (-88.50)",
                    index_id="TECH10",
                )
            )
        )
        args = _ns(command="dividend", index="tech10", sym="msft", amount=500.0)
        ok = admin_cli._cmd_dividend(client, args)
        assert ok is False
        assert "non-positive" in capsys.readouterr().out

    def test_zero_amount_rejected_client_side(self) -> None:
        client, push = _client()
        args = _ns(command="dividend", index="tech10", sym="msft", amount=0.0)
        with pytest.raises(ValueError, match="--amount"):
            admin_cli._cmd_dividend(client, args)
        assert push.sent == []

    def test_negative_amount_rejected_client_side(self) -> None:
        client, push = _client()
        args = _ns(command="dividend", index="tech10", sym="msft", amount=-1.0)
        with pytest.raises(ValueError):
            admin_cli._cmd_dividend(client, args)
        assert push.sent == []


# ---------------------------------------------------------------------------
# shares
# ---------------------------------------------------------------------------


class TestCmdShares:
    def test_new_shares_absolute_value(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8401.09,
                    divisor=118.1187,
                )
            )
        )
        args = _ns(
            command="shares",
            index="tech10",
            sym="aapl",
            new_shares=15_200_000_000,
            delta=None,
        )
        ok = admin_cli._cmd_shares(client, args)

        topic, payload = _last_sent(push)
        assert topic == "index.corp_action"
        assert payload["action"] == "SHARES_ISSUANCE"
        assert payload["new_shares_outstanding"] == 15_200_000_000
        assert ok is True

    def test_zero_new_shares_rejected_client_side(self) -> None:
        client, push = _client()
        args = _ns(
            command="shares", index="tech10", sym="aapl", new_shares=0, delta=None
        )
        with pytest.raises(ValueError):
            admin_cli._cmd_shares(client, args)
        assert push.sent == []

    def test_delta_resolves_against_history_buyback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # index_history() called first (delta resolution), then
        # index_corp_action() — two acks must be queued in send order.
        client, push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01",
                    index_id="TECH10",
                    records=[
                        {
                            "type": "CORP_ACTION",
                            "timestamp": 100.0,
                            "index_id": "TECH10",
                            "symbol": "AAPL",
                            "action": "SHARES_ISSUANCE",
                            "detail": "shares=16000000000",
                        }
                    ],
                ),
                make_index_corp_action_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8401.09,
                    divisor=118.1187,
                ),
            )
        )
        args = _ns(
            command="shares",
            index="tech10",
            sym="aapl",
            new_shares=None,
            delta=-800_000_000,
        )
        ok = admin_cli._cmd_shares(client, args)
        assert ok is True

        # Second send is the corp_action; assert the resolved absolute value.
        _, payload = decode(push.sent[-1])
        assert payload["new_shares_outstanding"] == 15_200_000_000
        out = capsys.readouterr().out
        assert "Last known shares_outstanding for AAPL: 16,000,000,000" in out

    def test_delta_with_no_prior_history_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01", index_id="TECH10", records=[]
                ),
            )
        )
        args = _ns(
            command="shares",
            index="tech10",
            sym="nvda",
            new_shares=None,
            delta=-100,
        )
        ok = admin_cli._cmd_shares(client, args)
        assert ok is False
        # Only the history request was sent — no corp_action attempted.
        assert len(push.sent) == 1
        captured = capsys.readouterr()
        assert "no prior shares_outstanding" in captured.err

    def test_delta_resolution_ignores_add_constituent_records(self) -> None:
        """ADD_CONSTITUENT history records carry reference_price, not
        shares_outstanding — they must not be mistaken for a share count."""
        client, push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01",
                    index_id="TECH10",
                    records=[
                        {
                            "type": "ADD_CONSTITUENT",
                            "timestamp": 50.0,
                            "index_id": "TECH10",
                            "symbol": "AAPL",
                            "reference_price": 118.5,
                        }
                    ],
                ),
            )
        )
        args = _ns(
            command="shares",
            index="tech10",
            sym="aapl",
            new_shares=None,
            delta=-100,
        )
        ok = admin_cli._cmd_shares(client, args)
        assert ok is False
        assert len(push.sent) == 1  # only the history request


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestCmdAdd:
    def test_accepted_sends_correct_frames(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_constituent_change_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8511.44,
                    divisor=119.0244,
                )
            )
        )
        args = _ns(
            command="add",
            index="tech10",
            sym="nvda",
            shares=2_470_000_000,
            price=118.50,
        )
        ok = admin_cli._cmd_add(client, args)

        topic, payload = _last_sent(push)
        assert topic == "index.constituent_change"
        assert payload["change_type"] == "ADD"
        assert payload["symbol"] == "NVDA"
        assert payload["shares_outstanding"] == 2_470_000_000
        assert payload["initial_price"] == 118.50
        assert ok is True

    def test_zero_shares_rejected_client_side(self) -> None:
        client, push = _client()
        args = _ns(command="add", index="tech10", sym="nvda", shares=0, price=118.50)
        with pytest.raises(ValueError):
            admin_cli._cmd_add(client, args)
        assert push.sent == []

    def test_zero_price_rejected_client_side(self) -> None:
        client, push = _client()
        args = _ns(command="add", index="tech10", sym="nvda", shares=100, price=0.0)
        with pytest.raises(ValueError):
            admin_cli._cmd_add(client, args)
        assert push.sent == []


# ---------------------------------------------------------------------------
# delist
# ---------------------------------------------------------------------------


class TestCmdDelist:
    def test_accepted_sends_correct_frames(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_constituent_change_ack_msg(
                    gateway_id="OPS01",
                    accepted=True,
                    index_id="TECH10",
                    level=8390.02,
                    divisor=118.9931,
                )
            )
        )
        args = _ns(command="delist", index="tech10", sym="xyz")
        ok = admin_cli._cmd_delist(client, args)

        topic, payload = _last_sent(push)
        assert topic == "index.constituent_change"
        assert payload["change_type"] == "DELIST"
        assert payload["symbol"] == "XYZ"
        assert ok is True

    def test_rejected_when_last_constituent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, _push = _client(
            recv_queue=_q(
                make_index_constituent_change_ack_msg(
                    gateway_id="OPS01",
                    accepted=False,
                    reason="Cannot delist AAPL: index TECH10 would have no "
                    "remaining constituents",
                    index_id="TECH10",
                )
            )
        )
        args = _ns(command="delist", index="tech10", sym="aapl")
        ok = admin_cli._cmd_delist(client, args)
        assert ok is False
        assert "no remaining constituents" in capsys.readouterr().out

    def test_confirmation_declined_does_not_send(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, push = _client()
        monkeypatch.setattr(admin_cli, "_confirm", lambda *_a, **_k: False)
        args = _ns(command="delist", index="tech10", sym="xyz", yes=False)
        ok = admin_cli._cmd_delist(client, args)
        assert ok is False
        assert push.sent == []


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


class TestCmdHistory:
    def test_table_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01",
                    index_id="TECH10",
                    records=[
                        {
                            "type": "CORP_ACTION",
                            "timestamp": "2026-07-19T09:15:02Z",
                            "index_id": "TECH10",
                            "symbol": "AAPL",
                            "action": "SPLIT",
                            "detail": "4:1",
                            "level": 8452.17,
                        }
                    ],
                )
            )
        )
        args = _ns(
            command="history",
            index="tech10",
            from_ts=None,
            to_ts=None,
            types=None,
            limit=50,
        )
        ok = admin_cli._cmd_history(client, args)
        assert ok is True

        topic, payload = _last_sent(push)
        assert topic == "index.history_request"
        assert payload["index_id"] == "TECH10"

        out = capsys.readouterr().out
        assert "CORP_ACTION" in out
        assert "AAPL" in out
        assert "SPLIT" in out

    def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        client, _push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01",
                    index_id="TECH10",
                    records=[{"type": "INIT", "timestamp": 1.0, "index_id": "TECH10"}],
                )
            )
        )
        args = _ns(
            command="history",
            index="tech10",
            from_ts=None,
            to_ts=None,
            types=None,
            limit=50,
            format="json",
        )
        ok = admin_cli._cmd_history(client, args)
        assert ok is True
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert isinstance(parsed, list)
        assert parsed[0]["type"] == "INIT"

    def test_no_records_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        client, _push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01", index_id="TECH10", records=[]
                )
            )
        )
        args = _ns(
            command="history",
            index="tech10",
            from_ts=None,
            to_ts=None,
            types=None,
            limit=50,
        )
        ok = admin_cli._cmd_history(client, args)
        assert ok is True
        assert "No history records found." in capsys.readouterr().out

    def test_types_filter_uppercased_and_split(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01", index_id="TECH10", records=[]
                )
            )
        )
        args = _ns(
            command="history",
            index="tech10",
            from_ts=None,
            to_ts=None,
            types="corp_action, delist",
            limit=50,
        )
        admin_cli._cmd_history(client, args)
        _, payload = _last_sent(push)
        assert payload["types"] == ["CORP_ACTION", "DELIST"]

    def test_limit_truncates_records(self, capsys: pytest.CaptureFixture[str]) -> None:
        records = [
            {"type": "INIT", "timestamp": float(i), "index_id": "TECH10"}
            for i in range(5)
        ]
        client, _push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="OPS01", index_id="TECH10", records=records
                )
            )
        )
        args = _ns(
            command="history",
            index="tech10",
            from_ts=None,
            to_ts=None,
            types=None,
            limit=2,
            format="json",
        )
        admin_cli._cmd_history(client, args)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert len(parsed) == 2


# ---------------------------------------------------------------------------
# Timeout handling (via main(), with a client injected to raise on _recv)
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    def test_split_handler_propagates_timeout(self) -> None:
        client, _push = _client(recv_queue=_q())  # empty queue -> exhausted
        args = _ns(command="split", index="tech10", sym="aapl", ratio="4:1")
        with pytest.raises(CommandTimeoutError):
            admin_cli._cmd_split(client, args)


# ---------------------------------------------------------------------------
# CommandError handling — unknown --index fails fast instead of timing out
# ---------------------------------------------------------------------------


class TestCommandErrorHandling:
    def test_split_handler_propagates_command_error(self) -> None:
        """A reply on index.error.* (unknown index_id) must surface as
        CommandError from the handler, not CommandTimeoutError — this is
        the fix for the bug where an unknown --index silently waited out
        the full --timeout instead of failing fast.
        """
        client, _push = _client(
            recv_queue=_q(make_index_error_msg("OPS01", "Unknown index_id 'NOPE'"))
        )
        args = _ns(command="split", index="nope", sym="aapl", ratio="4:1")
        with pytest.raises(CommandError, match="Unknown index_id 'NOPE'"):
            admin_cli._cmd_split(client, args)

    def test_history_handler_propagates_command_error(self) -> None:
        client, _push = _client(
            recv_queue=_q(make_index_error_msg("OPS01", "Unknown index_id 'NOPE'"))
        )
        args = _ns(
            command="history",
            index="nope",
            from_ts=None,
            to_ts=None,
            types=None,
            limit=50,
        )
        with pytest.raises(CommandError):
            admin_cli._cmd_history(client, args)

    def test_main_reports_rejected_and_exits_1_table_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End-to-end through main(): an unrecognized --index now prints a
        REJECTED line and exits 1 immediately, instead of hanging for
        --timeout ms and printing a misleading 'is pm-index running?'
        message.
        """
        client, _push = _client(
            recv_queue=_q(make_index_error_msg("OPS01", "Unknown index_id 'NOPE'"))
        )
        monkeypatch.setattr(admin_cli, "ExchangeCommandClient", lambda *a, **k: client)
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-index-admin-cli",
                "--id",
                "OPS01",
                "-y",
                "split",
                "--index",
                "NOPE",
                "--sym",
                "AAPL",
                "--ratio",
                "4:1",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            admin_cli.main()
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "REJECTED" in out
        assert "Unknown index_id 'NOPE'" in out
        # Must NOT print the timeout-specific message for this path.
        assert "Timed out" not in out

    def test_main_reports_rejected_as_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, _push = _client(
            recv_queue=_q(make_index_error_msg("OPS01", "Unknown index_id 'NOPE'"))
        )
        monkeypatch.setattr(admin_cli, "ExchangeCommandClient", lambda *a, **k: client)
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-index-admin-cli",
                "--id",
                "OPS01",
                "--format",
                "json",
                "-y",
                "delist",
                "--index",
                "NOPE",
                "--sym",
                "AAPL",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            admin_cli.main()
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["accepted"] is False
        assert parsed["reason"] == "Unknown index_id 'NOPE'"

    def test_main_still_reports_timeout_when_no_error_reply_arrives(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Sanity check: genuine unreachable-pm-index timeouts (no reply at
        all) still hit the CommandTimeoutError branch, unchanged."""
        client, _push = _client(recv_queue=_q())  # empty -> exhausted
        monkeypatch.setattr(admin_cli, "ExchangeCommandClient", lambda *a, **k: client)
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-index-admin-cli",
                "--id",
                "OPS01",
                "-y",
                "split",
                "--index",
                "TECH10",
                "--sym",
                "AAPL",
                "--ratio",
                "4:1",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            admin_cli.main()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Timed out waiting for pm-index" in err


# ---------------------------------------------------------------------------
# _confirm() behaviour
# ---------------------------------------------------------------------------


class TestConfirm:
    def test_yes_flag_skips_prompt(self) -> None:
        assert admin_cli._confirm("Continue?", assume_yes=True) is True

    def test_non_tty_without_yes_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        result = admin_cli._confirm("Continue?", assume_yes=False)
        assert result is False
        assert "REJECTED" in capsys.readouterr().err

    def test_tty_yes_input_confirms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "y")
        assert admin_cli._confirm("Continue?", assume_yes=False) is True

    def test_tty_blank_input_declines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        assert admin_cli._confirm("Continue?", assume_yes=False) is False
