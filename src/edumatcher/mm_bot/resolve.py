"""Merge CLI scopes and config-file blocks into one per-symbol parameter set.

Precedence, most specific source first
(docs-design/EduMatcher-mm-bot-multi.md §6):

1. the symbol's own CLI scope — ``--symbol MSFT --gap 0.20``
2. the symbol's block in the config file — ``symbols.MSFT.gap``
3. the global CLI scope — ``--gap 0.20`` before the first ``--symbol``
4. the config file's ``defaults:`` block
5. the built-in default

Rank 2 above rank 3 is deliberate: a per-symbol value written into a
reviewed, version-controlled file should not be silently un-tuned by a
throwaway gateway-wide flag. Overriding one symbol from the command line is
still possible — by naming it: ``--symbol TSLA --gap 0.10``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from edumatcher.mm_bot.config import FileConfig
from edumatcher.mm_bot.params import (
    TIER2_DEFAULTS,
    TIER2_KEYS,
    validate_symbol_params,
)


class NoSymbolsError(ValueError):
    """No symbol was named by the CLI or the config file."""


@dataclass(frozen=True)
class ResolvedConfig:
    """Fully resolved per-symbol parameters, in start-up order."""

    symbols: list[str]
    params: dict[str, dict[str, Any]]

    @property
    def primary(self) -> dict[str, Any]:
        """The first symbol's parameters.

        ``MMBot`` takes its flat keyword arguments as the all-symbols
        baseline and a per-symbol ``overrides`` mapping on top; this is what
        feeds the baseline.
        """
        return self.params[self.symbols[0]]


def resolve_symbol_params(
    file_config: FileConfig,
    global_cli: Mapping[str, Any],
    symbol_cli: Sequence[tuple[str, Mapping[str, Any]]] = (),
    extra_symbols: Sequence[str] = (),
) -> ResolvedConfig:
    """Resolve every symbol's Tier-2 parameters.

    ``global_cli`` and each ``symbol_cli`` mapping use ``None`` for "flag not
    given", which is what makes "explicitly set to the same value as the
    default" distinguishable from "never set" — see ``gap_was_explicit``.

    The symbol universe is the union of the config file's symbols, any
    ``--symbols`` entries, and any ``--symbol`` scopes, in that order.
    """
    scope_params = {sym: dict(values) for sym, values in symbol_cli}

    order: list[str] = []
    for name in (
        *file_config.symbols,
        *(s.strip().upper() for s in extra_symbols),
        *(sym for sym, _ in symbol_cli),
    ):
        if name and name not in order:
            order.append(name)
    if not order:
        raise NoSymbolsError(
            "no symbols configured: use --symbol, --symbols, or a config "
            "file with a 'symbols:' block"
        )

    params: dict[str, dict[str, Any]] = {}
    for symbol in order:
        layers = (
            scope_params.get(symbol, {}),
            file_config.symbols.get(symbol, {}),
            global_cli,
            file_config.defaults,
        )
        merged: dict[str, Any] = {}
        for key in TIER2_KEYS:
            for layer in layers:
                if layer.get(key) is not None:
                    merged[key] = layer[key]
                    break
        # Only a value the operator supplied somewhere counts; the built-in
        # 0.10 does not, so bot.py may still derive the gap from the symbol's
        # MM spread obligation.
        gap_was_explicit = "gap" in merged
        resolved = validate_symbol_params(symbol, {**TIER2_DEFAULTS, **merged})
        resolved["gap_was_explicit"] = gap_was_explicit
        params[symbol] = resolved

    return ResolvedConfig(symbols=order, params=params)
