"""Static per-symbol reference data carried on the CALF handshake.

Today that is display precision. ``tick_decimals`` is defined per symbol in
the engine configuration and governs how many decimals a price should be
rendered at; a client that formats a price without it is guessing, and
guesses right only for the instruments that happen to quote to two.

It arrives as ``REF=SYM:DECIMALS,...`` on ``WELCOME`` and on the ``SYMBOLS``
reply -- static reference data on the handshake and the reference command,
never on a market data channel, where an unchanging value would repeat on
every tick of the hottest path in the protocol.

The *presence* of ``REF`` is the capability signal, the same mechanism
``CH_SUPPORTED`` uses. A client talking to a gateway too old to send it
falls back to the documented default of 2 knowingly, via
:attr:`ReferenceData.advertised`, rather than by accident.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: What a price means when the gateway told us nothing about the symbol.
#: The documented fallback, not a guess of our own.
DEFAULT_TICK_DECIMALS = 2


class ReferenceData:
    """Per-symbol reference data, merged across the messages that carry it.

    Merged rather than replaced because ``WELCOME`` and the ``SYMBOLS``
    reply are two views of the same data arriving at different moments, and
    a reconnect should never narrow what is already known.
    """

    def __init__(self) -> None:
        self._decimals: dict[str, int] = {}
        self._advertised = False

    @property
    def advertised(self) -> bool:
        """Whether any gateway on this connection has sent a ``REF`` field.

        ``False`` means every price is rendering at
        :data:`DEFAULT_TICK_DECIMALS` because nothing better is available --
        worth surfacing, since it is the difference between a default and a
        fact.
        """
        return self._advertised

    def learn(self, ref_field: str | None) -> None:
        """Merge one ``REF=SYM:DEC,...`` field. ``None`` and empty are no-ops."""
        if not ref_field:
            return
        self._advertised = True
        for entry in ref_field.split(","):
            symbol, _, raw = entry.partition(":")
            symbol = symbol.strip().upper()
            if not symbol:
                continue
            try:
                self._decimals[symbol] = int(raw)
            except ValueError:
                # The tuple is defined as extensible -- a future gateway may
                # send SYM:DEC:MULT:CCY. Skip what this version cannot read
                # rather than reject the whole field.
                log.debug("ignoring unparseable REF entry %r", entry)

    def decimals(self, symbol: str) -> int:
        """Display precision for a symbol, falling back to the documented 2."""
        return self._decimals.get(symbol.upper(), DEFAULT_TICK_DECIMALS)

    def format_price(self, symbol: str, raw: str | float | None) -> str:
        """Render a price at the symbol's own precision.

        Returns ``"-"`` for a missing value and passes through anything
        non-numeric unchanged, so a malformed field is visible as itself
        rather than silently becoming a number.
        """
        if raw is None or raw == "":
            return "-"
        try:
            return f"{float(raw):.{self.decimals(symbol)}f}"
        except (TypeError, ValueError):
            return str(raw)

    def as_dict(self) -> dict[str, int]:
        """A copy of everything learned, for display or diagnostics."""
        return dict(self._decimals)
