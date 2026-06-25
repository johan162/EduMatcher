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

# Index process endpoints
EDUMATCHER_INDEX_BIND_HOST = os.getenv("EDUMATCHER_INDEX_BIND_HOST", "127.0.0.1")
EDUMATCHER_ENGINE_HOST = os.getenv("EDUMATCHER_ENGINE_HOST", "127.0.0.1")
EDUMATCHER_INDEX_PUB_PORT = int(os.getenv("EDUMATCHER_INDEX_PUB_PORT", "5558"))
EDUMATCHER_INDEX_PULL_PORT = int(os.getenv("EDUMATCHER_INDEX_PULL_PORT", "5559"))

INDEX_PUB_ADDR = f"tcp://{EDUMATCHER_INDEX_BIND_HOST}:{EDUMATCHER_INDEX_PUB_PORT}"
INDEX_PULL_ADDR = f"tcp://{EDUMATCHER_INDEX_BIND_HOST}:{EDUMATCHER_INDEX_PULL_PORT}"

# Connect-side addresses for clients subscribing/sending to pm-index
INDEX_PUB_CONNECT_ADDR = f"tcp://{EDUMATCHER_ENGINE_HOST}:{EDUMATCHER_INDEX_PUB_PORT}"
INDEX_PULL_CONNECT_ADDR = f"tcp://{EDUMATCHER_ENGINE_HOST}:{EDUMATCHER_INDEX_PULL_PORT}"

# ---------------------------------------------------------------------------
# Data directory resolution
# ---------------------------------------------------------------------------
# Detect whether we are running from a source checkout.  config.py lives at
# src/edumatcher/config.py; when installed via pip/pipx it lives somewhere
# inside site-packages and the parent directory is NOT named "src".
_pkg_dir = Path(__file__).parent  # .../edumatcher/
_src_dir = _pkg_dir.parent  # .../src/   (source) or site-packages (installed)
_IN_SOURCE_TREE: bool = _src_dir.name == "src"


def _resolve_data_dir() -> Path:
    _env = os.environ.get("EDUMATCHER_DATA_DIR")
    if _env:
        return Path(_env).expanduser().resolve()
    if _IN_SOURCE_TREE:
        return _src_dir / "data"
    return Path("~/.local/share/edumatcher").expanduser()


DATA_DIR = _resolve_data_dir()

GTC_ORDERS_FILE = DATA_DIR / "gtc_orders.json"
GTC_COMBOS_FILE = DATA_DIR / "gtc_combos.json"
BOOK_STATS_FILE = DATA_DIR / "book_stats.json"
AUDIT_LOG_FILE = DATA_DIR / "audit.log"
CLEARING_REPORT_FILE = DATA_DIR / "clearing_report.csv"
STATS_DB_FILE = DATA_DIR / "stats.db"


# ---------------------------------------------------------------------------
# Engine configuration file resolution
# ---------------------------------------------------------------------------
def _resolve_engine_config() -> Path:
    _env = os.environ.get("EDUMATCHER_CONFIG")
    if _env:
        return Path(_env).expanduser().resolve()
    if _IN_SOURCE_TREE:
        # Repo root is three levels up from config.py (src/edumatcher/config.py)
        return _src_dir.parent / "engine_config.yaml"
    # Installed: look in the current working directory
    return Path.cwd() / "engine_config.yaml"


ENGINE_CONFIG_FILE = _resolve_engine_config()

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
ORDERBOOK_DEPTH = 10  # top-N levels shown in viewer
CLEARING_PRINT_EVERY = 10  # print P&L table every N trades
