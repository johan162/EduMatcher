"""Tests for Automated Corridor Expansion (ACE) on circuit-breaker reopenings.

ACE decides whether a halted symbol may reopen. The behaviour that matters is
arithmetic — where the corridor sits after N extensions — and the terminating
argument that the ladder's last rung repeats, so these are exercised directly
rather than through the engine's poll loop.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from edumatcher.engine.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerLevel,
    CircuitBreakerState,
    ExpansionLevel,
    ReopeningConfig,
)
from edumatcher.engine.config_loader import load_engine_config

MIN = 60_000_000_000


def _state(reopening: ReopeningConfig | None = None) -> CircuitBreakerState:
    cfg = CircuitBreakerConfig(
        symbol="ABC",
        levels=[CircuitBreakerLevel("L1", 0.07, 5 * MIN)],
        reopening=reopening or ReopeningConfig(random_end_max_ns=0),
    )
    state = CircuitBreakerState(symbol="ABC", config=cfg)
    state.reference_price = 10_000  # $100.00 in ticks
    return state


class TestCorridorArithmetic:
    def test_reproduces_the_published_nasdaq_ladder(self) -> None:
        # The SEC order approving SR-NASDAQ-2024-065 works through a $100
        # reference giving collars 90/110, then 80/120, then 60/140. Getting
        # the same numbers is the cheapest check that widening is additive on
        # the reference rather than compounding on the previous width.
        state = _state()
        state.activate(0, state.config.levels[0])

        seen = [state.corridor()]
        for _ in range(2):
            state.extend(0)
            seen.append(state.corridor())

        assert seen == [(9_000, 11_000), (8_000, 12_000), (6_000, 14_000)]

    def test_the_last_rung_repeats_so_the_corridor_never_stops_widening(self) -> None:
        # This is what makes an extension cap unnecessary: any finite price is
        # eventually contained, so a halt always resolves on its own.
        reopening = ReopeningConfig(random_end_max_ns=0)
        widths = [reopening.band_pct_at(i) for i in range(6)]

        assert widths == pytest.approx([0.10, 0.20, 0.40, 0.60, 0.80, 1.00])
        assert reopening.duration_at(5) == reopening.expansions[-1].min_duration_ns

    def test_a_price_inside_the_corridor_may_print(self) -> None:
        state = _state()
        state.activate(0, state.config.levels[0])

        assert state.within_corridor(10_500)
        assert not state.within_corridor(12_200)

        state.extend(0)
        state.extend(0)
        assert state.within_corridor(12_200)  # now inside +/-40%

    def test_the_corridor_reference_is_latched_at_halt_time(self) -> None:
        # An uncross elsewhere moves reference_price. If the corridor tracked
        # it, the target would drift mid-halt and the ladder would chase it.
        state = _state()
        state.activate(0, state.config.levels[0])
        state.reference_price = 50_000

        assert state.corridor() == (9_000, 11_000)

    def test_a_disabled_reopening_leaves_the_reopen_unbounded(self) -> None:
        state = _state(ReopeningConfig(enabled=False))
        state.activate(0, state.config.levels[0])

        assert state.corridor() is None
        assert state.within_corridor(999_999)


class TestRandomEnd:
    def test_the_tail_lands_within_its_configured_bound(self) -> None:
        reopening = ReopeningConfig(random_end_max_ns=30_000_000_000)
        rng = random.Random(1234)
        for _ in range(50):
            state = _state(reopening)
            state.activate(0, state.config.levels[0], rng)
            assert state.resume_at_ns is not None
            assert 5 * MIN <= state.resume_at_ns <= 5 * MIN + 30_000_000_000

    def test_halt_duration_is_a_floor_not_an_exact_time(self) -> None:
        reopening = ReopeningConfig(random_end_max_ns=30_000_000_000)
        rng = random.Random(7)
        ends: set[int] = set()
        for _ in range(30):
            state = _state(reopening)
            state.activate(0, state.config.levels[0], rng)
            assert state.resume_at_ns is not None
            ends.add(state.resume_at_ns)

        assert len(ends) > 1, "a predictable reopen instant can be targeted"

    def test_zero_bound_makes_reopen_times_exact(self) -> None:
        state = _state(ReopeningConfig(random_end_max_ns=0))
        state.activate(0, state.config.levels[0], random.Random(1))

        assert state.resume_at_ns == 5 * MIN

    def test_extensions_are_randomised_too(self) -> None:
        # Xetra randomises the end of every call phase, not just the first;
        # an extension is where the price is most contested.
        reopening = ReopeningConfig(random_end_max_ns=10_000_000_000)
        rng = random.Random(99)
        state = _state(reopening)
        state.activate(0, state.config.levels[0], rng)

        ends: set[int] = set()
        for _ in range(20):
            state.expansion_index = 0
            state.extend(0, rng)
            assert state.resume_at_ns is not None
            ends.add(state.resume_at_ns)

        assert len(ends) > 1
        assert all(2 * MIN <= e <= 2 * MIN + 10_000_000_000 for e in ends)


class TestRestOfDayLevels:
    def test_a_rest_of_day_halt_never_enters_the_ace_cycle(self) -> None:
        # No timed resume means no call phase ever ends, so there is nothing
        # to extend. It waits for the closing backstop or an ADMIN resume.
        cfg = CircuitBreakerConfig(
            symbol="ABC",
            levels=[CircuitBreakerLevel("L3", 0.20, None)],
            reopening=ReopeningConfig(random_end_max_ns=0),
        )
        state = CircuitBreakerState(symbol="ABC", config=cfg)
        state.reference_price = 10_000
        state.activate(0, cfg.levels[0])

        assert state.resume_at_ns is None
        assert not state.should_resume(10**18)


class TestLoaderMerge:
    def _write(self, tmp_path: Path, body: str) -> Path:
        source = tmp_path / "engine_config.yaml"
        source.write_text(
            "gateways:\n  alf: [{id: TRADER01, role: TRADER}]\n" + body,
            encoding="utf-8",
        )
        return source

    def test_a_symbol_overrides_one_field_without_restating_the_ladder(
        self, tmp_path: Path
    ) -> None:
        source = self._write(
            tmp_path,
            """
circuit_breaker_defaults:
  levels:
    L1: {price_shift_pct: 0.07, halt_duration_ns: 300000000000}
  reopening:
    initial_band_pct: 0.10
    expansions:
      - {widen_pct: 0.15, min_duration_ns: 60000000000}
symbols:
  AAPL: {tick_decimals: 2}
  MSFT:
    tick_decimals: 2
    circuit_breaker:
      reopening:
        initial_band_pct: 0.03
""",
        )
        cfg = load_engine_config(source)

        aapl = cfg.symbols["AAPL"].circuit_breaker
        msft = cfg.symbols["MSFT"].circuit_breaker
        assert aapl is not None and msft is not None
        assert aapl.reopening.initial_band_pct == 0.10
        assert msft.reopening.initial_band_pct == 0.03
        # The ladder came from defaults and survived the override.
        assert msft.reopening.expansions == [
            ExpansionLevel(widen_pct=0.15, min_duration_ns=60_000_000_000)
        ]

    def test_a_per_symbol_random_seed_is_rejected(self, tmp_path: Path) -> None:
        # Engine-wide by construction: accepting it per symbol would store a
        # value that is then silently ignored.
        source = self._write(
            tmp_path,
            """
symbols:
  AAPL:
    tick_decimals: 2
    circuit_breaker:
      levels:
        L1: {price_shift_pct: 0.07, halt_duration_ns: 300000000000}
      reopening:
        random_seed: 7
""",
        )
        with pytest.raises(ValueError, match="random_seed"):
            load_engine_config(source)

    def test_a_per_symbol_expansion_ladder_is_rejected(self, tmp_path: Path) -> None:
        # The corridor's starting width describes the instrument; the
        # escalation schedule describes how long the venue tolerates a
        # suspended symbol. Keeping the ladder uniform is what makes halts
        # comparable across the book — and an unenforced restriction is worse
        # than either answer, since the config GUI drops what it cannot model.
        source = self._write(
            tmp_path,
            """
symbols:
  AAPL:
    tick_decimals: 2
    circuit_breaker:
      levels:
        L1: {price_shift_pct: 0.07, halt_duration_ns: 300000000000}
      reopening:
        expansions:
          - {widen_pct: 0.30, min_duration_ns: 600000000000}
""",
        )
        with pytest.raises(ValueError, match="expansions is exchange-wide"):
            load_engine_config(source)

    def test_a_symbol_may_still_override_the_starting_corridor(
        self, tmp_path: Path
    ) -> None:
        # The restriction is on the ladder only — the instrument-shaped part
        # of ACE stays per symbol.
        source = self._write(
            tmp_path,
            """
symbols:
  AAPL:
    tick_decimals: 2
    circuit_breaker:
      levels:
        L1: {price_shift_pct: 0.07, halt_duration_ns: 300000000000}
      reopening:
        initial_band_pct: 0.05
        random_end_max_ns: 0
""",
        )
        cb = load_engine_config(source).symbols["AAPL"].circuit_breaker
        assert cb is not None
        assert cb.reopening.initial_band_pct == 0.05
        assert cb.reopening.random_end_max_ns == 0

    def test_the_engine_seed_is_read_from_the_defaults_block(
        self, tmp_path: Path
    ) -> None:
        source = self._write(
            tmp_path,
            """
circuit_breaker_defaults:
  levels:
    L1: {price_shift_pct: 0.07, halt_duration_ns: 300000000000}
  reopening:
    random_seed: 20260730
symbols:
  AAPL: {tick_decimals: 2}
""",
        )
        assert load_engine_config(source).reopening_random_seed == 20260730

    def test_an_empty_expansion_ladder_is_refused(self, tmp_path: Path) -> None:
        source = self._write(
            tmp_path,
            """
circuit_breaker_defaults:
  levels:
    L1: {price_shift_pct: 0.07, halt_duration_ns: 300000000000}
  reopening:
    expansions: []
symbols:
  AAPL: {tick_decimals: 2}
""",
        )
        with pytest.raises(ValueError, match="expansions"):
            load_engine_config(source)
