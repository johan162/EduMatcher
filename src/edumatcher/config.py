"""
ZeroMQ addresses and data-file paths.
All processes import constants from here — change ports in one place.

Runtime configuration
---------------------
Two environment variables allow end users to run EduMatcher without a source
checkout (e.g. after ``pipx install edumatcher``):

EDUMATCHER_DATA_DIR
    Directory where all persistent data files are stored.
    Priority order:
      1. ``EDUMATCHER_DATA_DIR`` environment variable
      2. Source-tree default: ``<repo>/src/data/``  (when running from a clone)
      3. Installed default:   ``~/.local/share/edumatcher``

EDUMATCHER_CONFIG
    Path to the engine configuration YAML file.
    Priority order:
      1. ``EDUMATCHER_CONFIG`` environment variable
      2. Source-tree default: ``<repo>/engine_config.yaml``
      3. Installed default:   ``./engine_config.yaml`` (current working directory)

Developer mode (poetry)
    When running from a source checkout nothing needs to change — the source-tree
    detection keeps the original ``src/data/`` and repo-root YAML paths.

End-user mode (pipx / pip)
    After ``pipx install edumatcher``:
      1. Run ``pm-setup`` once to create the data directory and copy a sample
         config to your working directory.
      2. Edit ``engine_config.yaml`` in that directory.
      3. Start processes from that directory, or export ``EDUMATCHER_DATA_DIR``
         and ``EDUMATCHER_CONFIG`` to point at your chosen locations.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# ZMQ endpoints
# ---------------------------------------------------------------------------
ENGINE_PULL_ADDR = "tcp://127.0.0.1:5555"  # engine receives orders here
ENGINE_PUB_ADDR = "tcp://127.0.0.1:5556"  # engine publishes all events here
DROP_COPY_PUB_ADDR = (
    "tcp://127.0.0.1:5557"  # engine drop-copy feed (per-participant fills)
)

# ---------------------------------------------------------------------------
# Data directory resolution
# ---------------------------------------------------------------------------
# Detect whether we are running from a source checkout.  config.py lives at
# src/edumatcher/config.py; when installed via pip/pipx it lives somewhere
# inside site-packages and the parent directory is NOT named "src".
_pkg_dir = Path(__file__).parent  # .../edumatcher/
_src_dir = _pkg_dir.parent  # .../src/   (source) or site-packages (installed)
_IN_SOURCE_TREE: bool = _src_dir.name == "src"

if os.environ.get("EDUMATCHER_DATA_DIR"):
    DATA_DIR = Path(os.environ["EDUMATCHER_DATA_DIR"]).expanduser().resolve()
elif _IN_SOURCE_TREE:
    DATA_DIR = _src_dir / "data"
else:
    DATA_DIR = Path("~/.local/share/edumatcher").expanduser()

GTC_ORDERS_FILE = DATA_DIR / "gtc_orders.json"
GTC_COMBOS_FILE = DATA_DIR / "gtc_combos.json"
BOOK_STATS_FILE = DATA_DIR / "book_stats.json"
AUDIT_LOG_FILE = DATA_DIR / "audit.log"
CLEARING_REPORT_FILE = DATA_DIR / "clearing_report.csv"
STATS_DB_FILE = DATA_DIR / "stats.db"

# ---------------------------------------------------------------------------
# Engine configuration file resolution
# ---------------------------------------------------------------------------
if os.environ.get("EDUMATCHER_CONFIG"):
    ENGINE_CONFIG_FILE = Path(os.environ["EDUMATCHER_CONFIG"]).expanduser().resolve()
elif _IN_SOURCE_TREE:
    # Repo root is three levels up from config.py (src/edumatcher/config.py)
    ENGINE_CONFIG_FILE = _src_dir.parent / "engine_config.yaml"
else:
    # Installed: look in the current working directory
    ENGINE_CONFIG_FILE = Path.cwd() / "engine_config.yaml"

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
ORDERBOOK_DEPTH = 10  # top-N levels shown in viewer
CLEARING_PRINT_EVERY = 10  # print P&L table every N trades
