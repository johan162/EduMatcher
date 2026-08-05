"""Per-symbol multi-level circuit breaker runtime state.

This model implements exchange-style L1/L2/L3 (or custom) breaker levels:

- each level has a price-shift threshold
- each level has its own halt duration
- larger price shifts can trigger deeper levels with longer halts
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CircuitBreakerLevel:
    """One trigger level in a circuit-breaker ladder."""

    name: str
    price_shift_pct: float
    halt_duration_ns: int | None


@dataclass
class ExpansionLevel:
    """One rung of the automated corridor-expansion ladder.

    ``widen_pct`` is added to the corridor half-width, as a fraction of the
    *reference* price — it does not compound on the previous width. See
    ``ReopeningConfig`` for why.
    """

    widen_pct: float
    min_duration_ns: int


#: Nasdaq's published ladder expressed in this schema: an initial +/-10%
#: corridor, one 10% widening, then 20% every period thereafter.
_DEFAULT_EXPANSIONS: list[ExpansionLevel] = [
    ExpansionLevel(widen_pct=0.10, min_duration_ns=120_000_000_000),
    ExpansionLevel(widen_pct=0.20, min_duration_ns=300_000_000_000),
]


@dataclass
class ReopeningConfig:
    """Automated Corridor Expansion (ACE) settings for one symbol.

    A circuit-breaker halt is a reopening auction's call phase. ACE governs
    how that call phase ends:

    - a price corridor bounds the price at which the symbol may reopen;
    - if the indicative uncross price falls outside it, the call is extended
      and the corridor widened rather than printing an outlying price;
    - every call phase, initial and extended, ends at a uniformly random
      point in a tail after its minimum duration, so the exact uncross
      instant cannot be targeted.

    Widening is *additive on the reference price*, matching Nasdaq Rule
    4120(c)(7)(B)-(C), where each extension widens the previous collar by a
    percentage of the **initial** Auction Reference Price. With
    ``initial_band_pct=0.10`` and the default ladder the corridor half-width
    runs 10%, 20%, 40%, 60%, ... of the reference.
    """

    enabled: bool = True
    initial_band_pct: float = 0.10
    expansions: list[ExpansionLevel] = field(
        default_factory=lambda: list(_DEFAULT_EXPANSIONS)
    )
    random_end_max_ns: int = 30_000_000_000
    #: Engine-wide; only read from ``circuit_breaker_defaults``. ``None``
    #: seeds from OS entropy, so reopen instants differ between runs.
    random_seed: int | None = None

    def band_pct_at(self, expansion_index: int) -> float:
        """Corridor half-width after ``expansion_index`` extensions.

        The ladder's final rung repeats indefinitely, so a call phase can
        always eventually widen enough to contain any finite price. This is
        what makes an extension cap unnecessary.
        """
        pct = self.initial_band_pct
        if not self.expansions:
            return pct
        for i in range(expansion_index):
            rung = self.expansions[min(i, len(self.expansions) - 1)]
            pct += rung.widen_pct
        return pct

    def duration_at(self, expansion_index: int) -> int:
        """Minimum call duration for extension number ``expansion_index``.

        Only meaningful for ``expansion_index >= 1``; the initial call phase
        takes its minimum from the triggered level's ``halt_duration_ns``.
        """
        if not self.expansions:
            return 0
        rung = self.expansions[min(expansion_index - 1, len(self.expansions) - 1)]
        return rung.min_duration_ns


@dataclass
class CircuitBreakerConfig:
    """Static configuration for one symbol's circuit breaker."""

    symbol: str
    reference_window_ns: int = 300_000_000_000  # 5 minutes
    levels: list[CircuitBreakerLevel] = field(default_factory=list)
    reopening: ReopeningConfig = field(default_factory=ReopeningConfig)


@dataclass
class CircuitBreakerState:
    """Mutable runtime state for one symbol's circuit breaker."""

    symbol: str
    config: CircuitBreakerConfig
    trade_history: deque[tuple[int, int]] = field(
        default_factory=deque
    )  # (timestamp_ns, price_ticks)
    _trade_price_sum: int = 0
    _history_len_synced: int = 0
    halted: bool = False
    halted_at_ns: Optional[int] = None
    resume_at_ns: Optional[int] = None
    trigger_price: Optional[int] = None
    reference_price: Optional[int] = None
    triggered_level: Optional[str] = None
    # What put this symbol into a halt: "CB" for an automatic breaker trigger,
    # "ADMIN" for an operator halt. Not *how* it resumes — a halt is always a
    # reopening auction call (orders rest, no matching) and always ends in an
    # uncross, because LIMIT orders accumulate freely while halted and
    # resuming without one would start continuous trading on a crossed book.
    halt_source: Optional[str] = None
    #: How many ACE extensions this halt has been through. 0 = still in the
    #: initial call phase.
    expansion_index: int = 0
    #: Price the ACE corridor is centred on, latched when the halt begins so
    #: that trades printed by an earlier uncross cannot move it mid-halt.
    corridor_reference: Optional[int] = None

    def _sync_history_aggregate(self) -> None:
        """Resync rolling aggregates if history was mutated outside this class."""
        cur_len = len(self.trade_history)
        if cur_len != self._history_len_synced:
            self._trade_price_sum = sum(price for _, price in self.trade_history)
            self._history_len_synced = cur_len

    def seed_reference(self, price: int, now: int) -> None:
        """Seed an initial reference price before any real trade has occurred.

        On day one (no fills yet) ``trade_history`` is empty, so ``record_trade``
        has no baseline to compare against and the breaker cannot trigger. This
        seeds a synthetic baseline (from the symbol's configured
        ``last_buy_price`` / ``last_sell_price``) so the breaker is active from
        the first order, mirroring how collars are active from their reference
        price immediately. No-op if a real trade history already exists.
        """
        if self.trade_history:
            return
        self.trade_history.append((now, price))
        self._trade_price_sum += price
        self._history_len_synced += 1
        self.reference_price = price

    def record_trade(self, price: int, now: int) -> CircuitBreakerLevel | None:
        """Record a fill and return the triggered breaker level, if any."""
        if self.halted:
            return None  # don't double-trigger an active halt

        self._sync_history_aggregate()

        # Trim entries older than the reference window — O(k) where k ≤ window age
        cutoff = now - self.config.reference_window_ns
        while self.trade_history and self.trade_history[0][0] < cutoff:
            _, old_price = self.trade_history.popleft()
            self._trade_price_sum -= old_price
            self._history_len_synced -= 1

        fired_level: CircuitBreakerLevel | None = None
        if self.trade_history:
            ref = self._trade_price_sum // len(self.trade_history)
            self.reference_price = ref
            shift = abs(price - ref) / ref if ref > 0 else 0.0
            for level in sorted(
                self.config.levels,
                key=lambda lvl: lvl.price_shift_pct,
            ):
                if shift >= level.price_shift_pct:
                    fired_level = level

        self.trade_history.append((now, price))
        self._trade_price_sum += price
        self._history_len_synced += 1
        if fired_level is not None:
            self.trigger_price = price
            self.triggered_level = fired_level.name
        return fired_level

    def _random_tail(self, rng: "random.Random | None") -> int:
        """Uniform delay added after a call phase's minimum duration.

        Returns 0 when the random end is disabled or no generator was
        supplied, which keeps every call site deterministic by default.
        """
        max_ns = self.config.reopening.random_end_max_ns
        if rng is None or max_ns <= 0:
            return 0
        return rng.randint(0, max_ns)

    def activate(
        self,
        now: int,
        level: CircuitBreakerLevel,
        rng: "random.Random | None" = None,
    ) -> None:
        """Activate a halt at the specified triggered level.

        ``halt_duration_ns`` is the *minimum* length of the reopening call
        phase; the random end adds a tail on top. A level with no duration
        (rest-of-day) never resumes on a timer and so never enters the ACE
        cycle — it waits for the end-of-day backstop or an ADMIN resume.
        """
        self.halted = True
        self.halted_at_ns = now
        self.resume_at_ns = (
            None
            if level.halt_duration_ns is None
            else now + level.halt_duration_ns + self._random_tail(rng)
        )
        self.halt_source = "CB"
        self.expansion_index = 0
        self.corridor_reference = self.reference_price

    def corridor(self) -> tuple[int, int] | None:
        """Current ACE price corridor in ticks, or ``None`` if not applicable.

        ``None`` means the reopen is unbounded: either ACE is switched off or
        the halt began with no reference price to centre a corridor on.
        """
        reopening = self.config.reopening
        if not reopening.enabled or self.corridor_reference is None:
            return None
        ref = self.corridor_reference
        band = ref * reopening.band_pct_at(self.expansion_index)
        low = max(1, int(ref - band))
        high = int(ref + band)
        return low, high

    def within_corridor(self, price: int) -> bool:
        """Whether an indicative uncross price may print as-is."""
        bounds = self.corridor()
        if bounds is None:
            return True
        low, high = bounds
        return low <= price <= high

    def extend(self, now: int, rng: "random.Random | None" = None) -> None:
        """Widen the corridor one rung and start another call phase."""
        self.expansion_index += 1
        self.resume_at_ns = (
            now
            + self.config.reopening.duration_at(self.expansion_index)
            + self._random_tail(rng)
        )

    def should_resume(self, now: int) -> bool:
        """Return ``True`` when a timed halt duration has elapsed."""
        return (
            self.halted and self.resume_at_ns is not None and now >= self.resume_at_ns
        )

    def deactivate(self) -> None:
        """Clear the halt state."""
        self.halted = False
        self.halted_at_ns = None
        self.resume_at_ns = None
        self.trigger_price = None
        self.triggered_level = None
        self.halt_source = None
        self.expansion_index = 0
        self.corridor_reference = None
        # Keep reference_price — useful for diagnostics after resume.
