"""Default values for pm-config-gen."""

from __future__ import annotations

DEFAULT_SNAPSHOT_INTERVAL_SEC = 0.5
DEFAULT_TICK_DECIMALS = 2

DEFAULT_STATIC_BAND_PCT = 0.20
DEFAULT_DYNAMIC_BAND_PCT = 0.02

DEFAULT_CB_WINDOW_NS = 300_000_000_000
DEFAULT_CB_LEVEL_SPECS = (
    "L1:0.07:5",
    "L2:0.13:15",
    "L3:0.20",
)

DEFAULT_MM_SPREAD_TICKS = 20
DEFAULT_MM_MIN_QTY = 100
DEFAULT_MM_STUB_QTY = 1000

DEFAULT_SCHEDULE = {
    "pre_open": "09:00",
    "opening_auction_start": "09:25",
    "continuous_start": "09:30",
    "closing_auction_start": "16:00",
    "closing_auction_end": "16:05",
}
