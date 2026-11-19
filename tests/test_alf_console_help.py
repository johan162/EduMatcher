"""pm-alf-console's HELP text and --help say what the parser accepts
(review WP-ACN07: D1, D4, D5)."""

from __future__ import annotations

from edumatcher.alf_console.display import HELP_TEXT
from edumatcher.alf_console.main import build_parser
from edumatcher.models.order_fields import COMBO_LEG_FIELDS, TYPE_FIELDS


def test_help_lists_every_tif_the_parser_accepts() -> None:
    assert "ATO" in HELP_TEXT
    assert "ATC" in HELP_TEXT


def test_help_does_not_claim_smp_none_is_the_default() -> None:
    """Omitted SMP means the participant's configured smp_action."""
    assert "NONE (default)" not in HELP_TEXT


def test_help_lists_oco_trail_and_combo_leg_fields() -> None:
    assert "LEG1_TRAIL" in HELP_TEXT
    assert "LEG<i>.STOP" in HELP_TEXT
    assert "LEG<i>.TYPE" in HELP_TEXT


def test_help_lists_every_combo_leg_type_the_engine_accepts() -> None:
    """A combo leg can be any type whose fields a leg carries (FOK and IOC
    included); the per-leg line of HELP must offer every one of them."""
    leg_line = next(line for line in HELP_TEXT.splitlines() if "LEG<i>.TYPE=" in line)
    for order_type, (required, _optional) in TYPE_FIELDS.items():
        if all(f in COMBO_LEG_FIELDS for f in required):
            assert order_type.value in leg_line, order_type.value


def test_cli_help_has_no_repository_paths() -> None:
    assert "../" not in build_parser().format_help()
