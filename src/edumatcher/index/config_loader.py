from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edumatcher.engine.config_loader import (
    IndexConfig,
    SymbolConfig,
    load_engine_config,
)


@dataclass(frozen=True)
class IndexRuntimeConfig:
    id: str
    description: str
    base_value: float
    publish_interval_sec: float
    history_file: str
    state_file: str
    constituents: list[str]
    outstanding_shares: dict[str, int]
    reference_prices: dict[str, float]


def _reference_price(symbol: str, cfg: SymbolConfig) -> float:
    buy = cfg.last_buy_price
    sell = cfg.last_sell_price
    if buy is not None and sell is not None:
        return (float(buy) + float(sell)) / 2.0
    if buy is not None:
        return float(buy)
    if sell is not None:
        return float(sell)
    raise ValueError(
        f"Symbol '{symbol}' requires at least one of last_buy_price/last_sell_price"
    )


def _to_runtime_index_config(
    idx: IndexConfig,
    symbols: dict[str, SymbolConfig],
) -> IndexRuntimeConfig:
    shares: dict[str, int] = {}
    prices: dict[str, float] = {}
    for symbol in idx.constituents:
        sym_cfg = symbols[symbol]
        if sym_cfg.outstanding_shares is None:
            raise ValueError(
                f"Index '{idx.id}' constituent '{symbol}' is missing outstanding_shares"
            )
        shares[symbol] = int(sym_cfg.outstanding_shares)
        prices[symbol] = _reference_price(symbol, sym_cfg)

    return IndexRuntimeConfig(
        id=idx.id,
        description=idx.description,
        base_value=idx.base_value,
        publish_interval_sec=idx.publish_interval_sec,
        history_file=idx.history_file,
        state_file=idx.state_file,
        constituents=list(idx.constituents),
        outstanding_shares=shares,
        reference_prices=prices,
    )


def load_index_runtime_configs(config_path: Path) -> list[IndexRuntimeConfig]:
    """Load and enrich index runtime configs from engine config YAML."""
    engine_cfg = load_engine_config(config_path)
    return [
        _to_runtime_index_config(idx, engine_cfg.symbols) for idx in engine_cfg.indices
    ]
