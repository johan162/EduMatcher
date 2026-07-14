from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConstituentConfig:
    symbol: str
    shares_outstanding: int
    initial_price: float


class IndexCalculator:
    """Pure index state machine and math. No IO or network side effects."""

    def __init__(
        self,
        constituents: list[ConstituentConfig],
        base_value: float,
        divisor: float | None = None,
        last_prices: dict[str, float] | None = None,
    ) -> None:
        if base_value <= 0.0:
            raise ValueError("base_value must be > 0")
        if not constituents:
            raise ValueError("at least one constituent is required")

        self._base_value = float(base_value)
        self._constituents: dict[str, str] = {}
        self._outstanding_shares: dict[str, int] = {}
        self._reference_prices: dict[str, float] = {}
        self._last_prices: dict[str, float] = {}

        for cfg in constituents:
            symbol = cfg.symbol.upper()
            if cfg.shares_outstanding <= 0:
                raise ValueError(f"shares_outstanding must be > 0 for {symbol}")
            if cfg.initial_price <= 0.0:
                raise ValueError(f"initial_price must be > 0 for {symbol}")
            if symbol in self._constituents:
                raise ValueError(f"duplicate constituent: {symbol}")
            self._constituents[symbol] = symbol
            self._outstanding_shares[symbol] = int(cfg.shares_outstanding)
            self._reference_prices[symbol] = float(cfg.initial_price)

        if last_prices:
            for symbol, price in last_prices.items():
                sym = symbol.upper()
                if sym in self._constituents and price > 0.0:
                    self._last_prices[sym] = float(price)

        initial_cap = self._aggregate_cap()
        if divisor is None:
            self._divisor = initial_cap / self._base_value
        else:
            if divisor <= 0.0:
                raise ValueError("divisor must be > 0")
            self._divisor = float(divisor)

        log.info(
            "index calculator initialized constituents=%d base_value=%.6f initial_cap=%.6f divisor=%.6f",
            len(self._constituents),
            self._base_value,
            initial_cap,
            self._divisor,
        )

    @property
    def divisor(self) -> float:
        return self._divisor

    @property
    def base_value(self) -> float:
        return self._base_value

    def constituent_symbols(self) -> list[str]:
        return sorted(self._constituents)

    def last_price(self, symbol: str) -> float:
        sym = symbol.upper()
        if sym not in self._constituents:
            raise KeyError(f"unknown constituent: {sym}")
        return self._last_prices.get(sym, self._reference_prices[sym])

    def shares_outstanding(self, symbol: str) -> int:
        sym = symbol.upper()
        if sym not in self._constituents:
            raise KeyError(f"unknown constituent: {sym}")
        return self._outstanding_shares[sym]

    def _aggregate_cap(self) -> float:
        total = 0.0
        for symbol in self._constituents:
            price = self._last_prices.get(symbol, self._reference_prices[symbol])
            total += price * self._outstanding_shares[symbol]
        return total

    def aggregate_cap(self) -> float:
        return self._aggregate_cap()

    def recalculate(self) -> float:
        if self._divisor == 0.0:
            raise ValueError("Divisor is zero - index is not initialised")
        aggregate_cap = self._aggregate_cap()
        level = aggregate_cap / self._divisor
        log.debug(
            "index recalculation aggregate_cap=%.6f divisor=%.6f level=%.6f",
            aggregate_cap,
            self._divisor,
            level,
        )
        return level

    def update_price(self, symbol: str, price: float) -> None:
        sym = symbol.upper()
        if sym not in self._constituents:
            log.debug("ignoring price update for non-constituent symbol=%s", sym)
            return
        if price <= 0.0:
            raise ValueError("price must be > 0")
        old_price = self._last_prices.get(sym, self._reference_prices[sym])
        self._last_prices[sym] = float(price)
        log.debug(
            "price update symbol=%s old_price=%.6f new_price=%.6f",
            sym,
            old_price,
            float(price),
        )

    def apply_split(
        self, symbol: str, ratio_numerator: int, ratio_denominator: int
    ) -> None:
        sym = symbol.upper()
        if sym not in self._constituents:
            raise KeyError(f"unknown constituent: {sym}")
        if ratio_numerator <= 0 or ratio_denominator <= 0:
            raise ValueError("Split ratio must be positive")

        old_cap = self._aggregate_cap()
        if old_cap <= 0.0:
            raise ValueError("Cannot apply split when aggregate cap is non-positive")
        old_shares = self._outstanding_shares[sym]
        self._outstanding_shares[sym] = (
            old_shares * ratio_numerator + ratio_denominator // 2
        ) // ratio_denominator

        old_price = self._last_prices.get(sym, self._reference_prices[sym])
        new_price = old_price * ratio_denominator / ratio_numerator
        self._last_prices[sym] = new_price

        new_cap = self._aggregate_cap()
        if new_cap != old_cap:
            self._divisor = self._divisor * (new_cap / old_cap)
        log.info(
            "applied split symbol=%s ratio=%d:%d shares=%d->%d price=%.6f->%.6f cap=%.6f->%.6f divisor=%.6f",
            sym,
            ratio_numerator,
            ratio_denominator,
            old_shares,
            self._outstanding_shares[sym],
            old_price,
            new_price,
            old_cap,
            new_cap,
            self._divisor,
        )

    def apply_cash_dividend(self, symbol: str, dividend_per_share: float) -> None:
        sym = symbol.upper()
        if sym not in self._constituents:
            raise KeyError(f"unknown constituent: {sym}")
        if dividend_per_share <= 0.0:
            raise ValueError("dividend_per_share must be > 0")

        old_cap = self._aggregate_cap()
        old_price = self._last_prices.get(sym, self._reference_prices[sym])
        new_price = old_price - dividend_per_share
        if new_price <= 0.0:
            raise ValueError("Dividend would make price non-positive")
        self._last_prices[sym] = new_price
        new_cap = self._aggregate_cap()

        if old_cap <= 0.0:
            raise ValueError("Cannot apply dividend when aggregate cap is non-positive")
        self._divisor = self._divisor * (new_cap / old_cap)
        log.info(
            "applied cash dividend symbol=%s dividend=%.6f price=%.6f->%.6f cap=%.6f->%.6f divisor=%.6f",
            sym,
            dividend_per_share,
            old_price,
            new_price,
            old_cap,
            new_cap,
            self._divisor,
        )

    def apply_shares_issuance(self, symbol: str, new_shares_outstanding: int) -> None:
        sym = symbol.upper()
        if sym not in self._constituents:
            raise KeyError(f"unknown constituent: {sym}")
        if new_shares_outstanding <= 0:
            raise ValueError("new_shares_outstanding must be positive")

        old_cap = self._aggregate_cap()
        if old_cap <= 0.0:
            raise ValueError(
                "Cannot apply shares issuance when aggregate cap is non-positive"
            )
        old_shares = self._outstanding_shares[sym]
        self._outstanding_shares[sym] = new_shares_outstanding
        new_cap = self._aggregate_cap()
        self._divisor = self._divisor * (new_cap / old_cap)
        log.info(
            "applied shares issuance symbol=%s shares=%d->%d cap=%.6f->%.6f divisor=%.6f",
            sym,
            old_shares,
            new_shares_outstanding,
            old_cap,
            new_cap,
            self._divisor,
        )

    def delist_symbol(self, symbol: str) -> None:
        sym = symbol.upper()
        if sym not in self._constituents:
            raise KeyError(f"Symbol {sym!r} is not an index constituent")

        old_cap = self._aggregate_cap()
        old_shares = self._outstanding_shares[sym]
        old_price = self._last_prices.get(sym, self._reference_prices[sym])
        del self._constituents[sym]
        self._outstanding_shares.pop(sym, None)
        self._reference_prices.pop(sym, None)
        self._last_prices.pop(sym, None)
        new_cap = self._aggregate_cap()

        if new_cap == 0.0:
            raise ValueError("Delisting last constituent would make aggregate cap zero")
        self._divisor = self._divisor * (new_cap / old_cap)
        log.info(
            "delisted constituent symbol=%s shares=%d last_price=%.6f cap=%.6f->%.6f divisor=%.6f",
            sym,
            old_shares,
            old_price,
            old_cap,
            new_cap,
            self._divisor,
        )

    def add_constituent(
        self, symbol: str, shares_outstanding: int, initial_price: float
    ) -> None:
        sym = symbol.upper()
        if sym in self._constituents:
            raise KeyError(f"Symbol {sym!r} is already a constituent")
        if shares_outstanding <= 0:
            raise ValueError("shares_outstanding must be positive")
        if initial_price <= 0.0:
            raise ValueError("initial_price must be positive")

        old_cap = self._aggregate_cap()
        self._constituents[sym] = sym
        self._outstanding_shares[sym] = shares_outstanding
        self._reference_prices[sym] = initial_price
        self._last_prices[sym] = initial_price
        new_cap = self._aggregate_cap()

        if old_cap <= 0.0:
            self._divisor = new_cap / self._base_value
        else:
            self._divisor = self._divisor * (new_cap / old_cap)
        log.info(
            "added constituent symbol=%s shares=%d initial_price=%.6f cap=%.6f->%.6f divisor=%.6f",
            sym,
            shares_outstanding,
            initial_price,
            old_cap,
            new_cap,
            self._divisor,
        )
