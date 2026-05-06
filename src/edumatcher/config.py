"""
ZeroMQ addresses and data-file paths.
All processes import constants from here — change ports in one place.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# ZMQ endpoints
# ---------------------------------------------------------------------------
ENGINE_PULL_ADDR = "tcp://127.0.0.1:5555"  # engine receives orders here
ENGINE_PUB_ADDR = "tcp://127.0.0.1:5556"  # engine publishes all events here

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent.parent / "data"

GTC_ORDERS_FILE = DATA_DIR / "gtc_orders.json"
GTC_COMBOS_FILE = DATA_DIR / "gtc_combos.json"
BOOK_STATS_FILE = DATA_DIR / "book_stats.json"
AUDIT_LOG_FILE = DATA_DIR / "audit.log"
CLEARING_REPORT_FILE = DATA_DIR / "clearing_report.csv"
STATS_DB_FILE = DATA_DIR / "stats.db"

# Default engine configuration file (can be overridden with --config)
# config.py lives in src/edumatcher, so parent.parent.parent points to repo root.
ENGINE_CONFIG_FILE = Path(__file__).parent.parent.parent / "engine_config.yaml"

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
ORDERBOOK_DEPTH = 10  # top-N levels shown in viewer
CLEARING_PRINT_EVERY = 10  # print P&L table every N trades
