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

The engine configuration file is deliberately *not* separately configurable —
it always lives at ``<DATA_DIR>/ref_data/engine_config.yaml``. See
``ENGINE_CONFIG_FILE`` below for why.

Developer mode (poetry)
    When running from a source checkout nothing needs to change — the source-tree
    detection keeps the original ``src/data/`` root.

End-user mode (pipx / pip)
    After ``pipx install edumatcher``:
      1. Run ``pm-setup`` once to create the data directory and write a sample
         config into ``<DATA_DIR>/ref_data/``.
      2. Edit that ``engine_config.yaml``.
      3. Export ``EDUMATCHER_DATA_DIR`` if you want a location other than the
         default; every process follows it together.
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


def resolve_data_path(path: str | os.PathLike[str] | Path) -> Path:
    """Resolve a configured relative path inside the shared data directory.

    Generated configs historically spell paths as ``data/stats.db``. In a
    source checkout that means ``src/data/stats.db``, not a working-directory
    relative ``data/stats.db``. Absolute paths remain explicit overrides.
    """
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    parts = candidate.parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    return DATA_DIR.joinpath(*parts)


GTC_ORDERS_FILE = DATA_DIR / "gtc_orders.json"
GTC_COMBOS_FILE = DATA_DIR / "gtc_combos.json"
BOOK_STATS_FILE = DATA_DIR / "book_stats.json"
AUDIT_LOG_FILE = DATA_DIR / "audit.log"
AUDIT_INDEX_DB_FILE = DATA_DIR / "audit_index.db"
CLEARING_REPORT_FILE = DATA_DIR / "clearing_report.csv"
CLEARING_DB_FILE = DATA_DIR / "clearing.db"
STATS_DB_FILE = DATA_DIR / "stats.db"
LOG_DB_FILE = DATA_DIR / "log.db"
LOG_FALLBACK_DIR = DATA_DIR / "logs"

# ---------------------------------------------------------------------------
# pm-log-srv (LALF log server) endpoint
# ---------------------------------------------------------------------------
# See docs-design/EduMatcher-log-srv.md for the full design and the LALF
# protocol (§15). Only a host/port default lives here, matching how
# ENGINE_PULL_ADDR/ENGINE_PUB_ADDR are plain module-level constants rather
# than going through the YAML config loader — pm-log-srv's own config.py
# (mirroring md_gateway/config.py) is the actual source of truth for a
# running server; this default is only used when no engine_config.yaml
# log_server: block and no CLI override are present.
LOG_SRV_HOST = "127.0.0.1"
LOG_SRV_PORT = 5600

# LALF-PS (the ZeroMQ log distribution interface) endpoints. pm-log-srv binds
# both: a PUB socket that carries every outbound stream/notify/backfill/ack
# message, and a PULL socket that receives subscriber control requests. The
# split mirrors pm-index's own INDEX_PUB_ADDR/INDEX_PULL_ADDR pair exactly, so
# a subscriber written against pm-index needs no new socket vocabulary. Ports
# are deliberately adjacent to LOG_SRV_PORT so the whole log subsystem occupies
# one contiguous 5600-5602 block.
LOG_SRV_PUB_PORT = 5601
LOG_SRV_PULL_PORT = 5602
LOG_SRV_PUB_ADDR = f"tcp://{LOG_SRV_HOST}:{LOG_SRV_PUB_PORT}"
LOG_SRV_PULL_ADDR = f"tcp://{LOG_SRV_HOST}:{LOG_SRV_PULL_PORT}"


# ---------------------------------------------------------------------------
# Engine configuration file resolution
# ---------------------------------------------------------------------------
# Derived from DATA_DIR with no per-process override, and deliberately so.
# While a --config flag and an EDUMATCHER_CONFIG variable existed, any single
# process could be pointed at a different file from the rest of the exchange.
# That failed quietly: pm-md-gwy started with an empty symbol universe and
# looked healthy, while the engine ran the ten symbols the operator expected.
# One data directory is one exchange instance, exactly as it already is for
# stats.db, log.db and audit.log — so a mistake now detaches a process from
# its logs and statistics too, and is noticed immediately.
#
# ref_data/ holds *deployed* configuration, not authored configuration. The
# YAML kept under version control is the source; a deploy step validates and
# copies it here. Nothing at runtime accepts a path.
REF_DATA_DIR = DATA_DIR / "ref_data"
ENGINE_CONFIG_FILE = REF_DATA_DIR / "engine_config.yaml"
# What every process actually reads: the compiled artifact, with all defaults
# resolved and all validation already done. The YAML beside it is the source it
# was built from, kept for provenance and for recompiling.
COMPILED_CONFIG_FILE = REF_DATA_DIR / "engine_config.json"

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
ORDERBOOK_DEPTH = 10  # top-N levels shown in viewer
CLEARING_PRINT_EVERY = 10  # print P&L table every N trades
