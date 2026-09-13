"""Every price in engine_config.yaml is display money on its symbol's grid.

The file used to say both things at once: `market_maker_quotes` carried
display prices and combo legs carried raw ticks, under keys spelled the same
way. These tests pin the single convention that replaced it, and the refusal
that keeps a price the grid cannot represent from being quietly rounded.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from edumatcher.cverifier.models import CheckResult
from edumatcher.cverifier import layer2_schema
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.models.price import TickViolation, to_ticks_exact_at


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def _schema_codes(tmp_path: Path, content: str) -> list[CheckResult]:
    path = _write(tmp_path, content)
    return layer2_schema.check(yaml.safe_load(path.read_text()), path)


# A 2-decimal symbol and a 4-decimal one, so a conversion at the wrong scale
# cannot hide behind a tick_decimals=2 coincidence.
TWO_SCALES = """
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 150.25
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 150.20
        ask_price: 150.30
        bid_qty: 100
        ask_qty: 100
  EURUSD:
    tick_decimals: 4
    last_buy_price: 1.2345
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 1.2344
        ask_price: 1.2346
        bid_qty: 100
        ask_qty: 100
gateways:
  alf:
    - id: MM01
      role: MARKET_MAKER
market_maker_combos:
  - combo_id: PAIR1
    legs:
      - symbol: AAPL
        side: BUY
        order_type: LIMIT
        quantity: 100
        price: 150.25
      - symbol: EURUSD
        side: SELL
        order_type: LIMIT
        quantity: 100
        price: 1.2345
"""


class TestScale:
    def test_each_price_converts_at_its_own_symbols_scale(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write(tmp_path, TWO_SCALES))

        aapl = cfg.symbols["AAPL"].market_maker_quotes[0]
        assert (aapl.bid_price_ticks, aapl.ask_price_ticks) == (15020, 15030)
        eur = cfg.symbols["EURUSD"].market_maker_quotes[0]
        assert (eur.bid_price_ticks, eur.ask_price_ticks) == (12344, 12346)

        # The legs of one combo trade different instruments, so each leg is
        # converted at its own symbol's scale, not the combo's first.
        legs = cfg.market_maker_combos[0].legs
        assert (legs[0].price_ticks, legs[0].tick_decimals) == (15025, 2)
        assert (legs[1].price_ticks, legs[1].tick_decimals) == (12345, 4)

    def test_last_prices_stay_display_money(self, tmp_path: Path) -> None:
        # Two consumers want different units — the engine ticks for the book,
        # pm-index money for a market cap — so the file's own unit is kept.
        cfg = load_engine_config(_write(tmp_path, TWO_SCALES))
        assert cfg.symbols["AAPL"].last_buy_price == 150.25
        assert cfg.symbols["EURUSD"].last_buy_price == 1.2345


class TestOffGridIsRejected:
    @pytest.mark.parametrize(
        ("field", "line", "bad", "where"),
        [
            (
                "last_buy_price",
                "    last_buy_price: 150.25",
                "    last_buy_price: 150.255",
                "last_buy_price",
            ),
            (
                "bid_price",
                "        bid_price: 150.20",
                "        bid_price: 150.205",
                "market_maker_quotes[0].bid_price",
            ),
            (
                "leg price",
                "        price: 150.25",
                "        price: 150.255",
                "legs[0].price",
            ),
        ],
    )
    def test_off_grid_price_is_a_config_error(
        self, tmp_path: Path, field: str, line: str, bad: str, where: str
    ) -> None:
        doc = textwrap.dedent(TWO_SCALES).replace(line, bad)
        assert bad in doc, f"{field}: fixture line did not match"
        with pytest.raises(ValueError) as exc:
            load_engine_config(_write(tmp_path, doc))
        # The failure names the field, not just the price.
        assert where in str(exc.value)
        assert "tick size" in str(exc.value)

    def test_the_four_decimal_symbol_is_checked_at_four_decimals(
        self, tmp_path: Path
    ) -> None:
        # 1.23455 is off EURUSD's grid but would sit on a 2-decimal one only
        # after rounding — the case a registry-resolved scale would miss,
        # since the registry is populated from this very file.
        doc = textwrap.dedent(TWO_SCALES).replace(
            "        price: 1.2345", "        price: 1.23455"
        )
        with pytest.raises(ValueError, match="tick size"):
            load_engine_config(_write(tmp_path, doc))


class TestVerifierAgrees:
    """pm-cverifier reports S078 for what the loader would refuse."""

    def test_clean_config_has_no_s078(self, tmp_path: Path) -> None:
        results = _schema_codes(tmp_path, TWO_SCALES)
        assert [r for r in results if r.code == "S078"] == []

    @pytest.mark.parametrize(
        ("line", "bad"),
        [
            ("    last_buy_price: 150.25", "    last_buy_price: 150.255"),
            ("        bid_price: 150.20", "        bid_price: 150.205"),
            ("        price: 150.25", "        price: 150.255"),
        ],
    )
    def test_off_grid_price_is_reported(
        self, tmp_path: Path, line: str, bad: str
    ) -> None:
        doc = textwrap.dedent(TWO_SCALES).replace(line, bad)
        results = _schema_codes(tmp_path, doc)
        assert [r for r in results if r.code == "S078"], [r.code for r in results]

    def test_unusable_tick_decimals_suppresses_the_grid_check(
        self, tmp_path: Path
    ) -> None:
        # S010 owns a malformed tick_decimals; there is no grid to check
        # against until it is fixed, so S078 must not pile on.
        doc = textwrap.dedent(TWO_SCALES).replace(
            "    tick_decimals: 2", "    tick_decimals: nonsense"
        )
        codes = {r.code for r in _schema_codes(tmp_path, doc)}
        assert "S010" in codes
        assert "S078" not in codes


class TestScaleTakingConverter:
    def test_it_ignores_the_registry(self) -> None:
        # The whole reason it exists: to_ticks_exact would resolve EURUSD to
        # the two-decimal default while the config that declares 4 is still
        # being read.
        assert to_ticks_exact_at(1.2345, 4, "EURUSD") == 12345
        with pytest.raises(TickViolation) as exc:
            to_ticks_exact_at(1.23455, 4, "EURUSD")
        assert exc.value.tick_decimals == 4
