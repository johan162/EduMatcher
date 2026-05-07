from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PersonalityProfile:
    name: str
    decision_interval_ms: int
    order_size_min: int
    order_size_max: int
    cross_probability: float
    passive_offset_ticks: int
    tick_size: float
    size_distribution: str

    def sample_qty(self, rng: random.Random) -> int:
        if self.order_size_min >= self.order_size_max:
            return self.order_size_min

        lo = self.order_size_min
        hi = self.order_size_max

        if self.size_distribution == "small-heavy":
            span = hi - lo
            qty = lo + int((rng.random() ** 2.0) * span)
            return max(lo, min(hi, qty))

        if self.size_distribution == "block-heavy":
            span = hi - lo
            qty = lo + int((1.0 - ((1.0 - rng.random()) ** 2.0)) * span)
            return max(lo, min(hi, qty))

        return rng.randint(lo, hi)


_PRESET_PROFILES: dict[str, PersonalityProfile] = {
    "aggressive": PersonalityProfile(
        name="aggressive",
        decision_interval_ms=250,
        order_size_min=20,
        order_size_max=120,
        cross_probability=0.35,
        passive_offset_ticks=0,
        tick_size=0.01,
        size_distribution="balanced",
    ),
    "cautious": PersonalityProfile(
        name="cautious",
        decision_interval_ms=900,
        order_size_min=10,
        order_size_max=60,
        cross_probability=0.05,
        passive_offset_ticks=2,
        tick_size=0.01,
        size_distribution="balanced",
    ),
    "many-small": PersonalityProfile(
        name="many-small",
        decision_interval_ms=180,
        order_size_min=1,
        order_size_max=25,
        cross_probability=0.18,
        passive_offset_ticks=1,
        tick_size=0.01,
        size_distribution="small-heavy",
    ),
    "few-large": PersonalityProfile(
        name="few-large",
        decision_interval_ms=1400,
        order_size_min=150,
        order_size_max=700,
        cross_probability=0.12,
        passive_offset_ticks=1,
        tick_size=0.01,
        size_distribution="block-heavy",
    ),
}


def get_profile(name: str) -> PersonalityProfile:
    key = name.strip().lower()
    if key not in _PRESET_PROFILES:
        allowed = ", ".join(sorted(_PRESET_PROFILES))
        raise ValueError(f"Unknown profile '{name}'. Allowed: {allowed}")
    return _PRESET_PROFILES[key]


def available_profiles() -> list[str]:
    return sorted(_PRESET_PROFILES)
