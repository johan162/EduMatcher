"""Static reference data for every ``pm-*`` command.

This module is the single source of truth ``pm-help``/``pm-man`` render from.
It is hand-curated (not scraped from ``--help`` at runtime) so it can carry
information no ``argparse`` parser exposes on its own: which ports a process
binds or connects to, which ZeroMQ topics it sends/subscribes, which other
commands it works alongside, and a worked example of real-world use.

Content here should stay in sync with `docs/user-guide/170-processes.md`,
which is the canonical prose reference this data is distilled from. When one
changes, check the other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    """A single command-line flag."""

    flags: str
    default: str = ""
    help: str = ""
    group: str = ""


@dataclass(frozen=True)
class Subcommand:
    """A subcommand of a multi-command CLI (e.g. ``pm-audit-cli events``)."""

    name: str
    args: str = ""
    purpose: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandInfo:
    """Everything ``pm-help``/``pm-man`` knows about one ``pm-*`` command."""

    name: str
    category: str
    title: str
    summary: str
    synopsis: tuple[str, ...]
    description: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()
    has_common_log_options: bool = False
    has_version_option: bool = True
    subcommands: tuple[Subcommand, ...] = ()
    ports: str = ""
    messages: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    doc_anchor: str = ""  # heading anchor within docs/user-guide/170-processes.md
    doc_page: str = ""  # optional dedicated topic page (shown in addition to the anchor)
    examples: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Shared option groups
#
# Every long-running process that connects to the ZeroMQ bus shares the same
# six logging flags (see docs/user-guide/040-running-the-exchange.md#logging-levels).
# Factoring them out here keeps each CommandInfo focused on what is actually
# distinctive about that command, and keeps the two docs from drifting apart
# on wording.
# ---------------------------------------------------------------------------

COMMON_LOG_OPTIONS: tuple[Option, ...] = (
    Option(
        "--log-level LEVEL",
        "WARNING",
        "Explicit level: CRITICAL, ERROR, WARNING, INFO, DEBUG",
    ),
    Option(
        "-v, --verbose",
        "off",
        "Increase verbosity (-v -> INFO, -vv -> DEBUG)",
    ),
    Option("-q, --quiet", "off", "Reduce output to warnings/errors"),
    Option(
        "--log-target TARGET",
        "server",
        "Where operational log records go: server (auto-detected pm-log-srv), stdout, or file",
    ),
    Option(
        "--log-file PATH",
        "none",
        "Operational log file path -- required when --log-target file",
    ),
    Option(
        "--log-failover-timeout SEC",
        "30 (from config)",
        "Grace window before falling back to a local log file once pm-log-srv becomes unreachable",
    ),
)

COMMON_VERSION_OPTION = Option("--version", "-", "Print version and exit")

# Display order for categories in the summary table and man-page "SEE ALSO"
# cross-references.
CATEGORY_ORDER: tuple[str, ...] = (
    "Core Runtime",
    "External Gateways",
    "Protocol Spies",
    "AI & Bots",
    "Index",
    "Query & Reporting CLIs",
    "Admin & Operations",
    "Setup & Configuration",
    "Logging",
    "Developer Tools",
    "Help",
)


# ---------------------------------------------------------------------------
# Core Runtime
# ---------------------------------------------------------------------------

_CORE_RUNTIME: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-engine",
        category="Core Runtime",
        title="Matching Engine",
        summary="The matching engine -- receives orders, matches them, publishes events.",
        synopsis=("pm-engine [-v|-vv] [--log-level LEVEL] [-q] [--log-target TARGET]",),
        description=(
            "The single writer to the order book and the heart of the system. Binds "
            "the ZeroMQ command socket (:5555) and the two publishing sockets "
            "(:5556 market events, :5557 drop-copy fills). Every other pm-* process "
            "is a producer (PUSH to :5555), a subscriber (SUB from :5556/:5557), or both.",
            "Start the engine first -- gateways and subscribers fail to connect, or "
            "silently miss early messages, if they start before it is bound.",
        ),
        has_common_log_options=True,
        ports="Binds 5555 (PULL, commands in), 5556 (PUB, market/session events), 5557 (PUB, drop-copy fills)",
        messages=(
            "Receives (PULL :5555): order.new, order.cancel, order.combo, system.gateway_connect, "
            "risk.kill_switch, risk.circuit_breaker_halt_all/resume_all, session.transition",
            "Publishes (PUB :5556): order.ack/fill/cancelled/expired.{GW_ID}, trade.executed, "
            "book.{SYMBOL}, session.state, auction.result.{SYMBOL}, system.eod",
            "Publishes (PUB :5557): drop_copy.event.{GW_ID}",
        ),
        related=("pm-opctl-cli", "pm-alf-console", "pm-scheduler", "pm-audit", "pm-stats"),
        doc_anchor="pm-engine-matching-engine",
        examples=("pm-engine -v   # start with INFO-level startup/lifecycle logging",),
        notes=(
            "On shutdown (Ctrl-C): expires resting DAY orders, serializes GTC orders "
            "to disk, publishes system.eod, then closes sockets.",
        ),
    ),
    CommandInfo(
        name="pm-alf-console",
        category="Core Runtime",
        title="User Gateway (ALF order entry)",
        summary="Interactive ALF order-entry terminal for a human trader; one instance per user.",
        synopsis=("pm-alf-console --id <GW_ID> [--drop-copy] [-v|-vv] [--log-level LEVEL]",),
        description=(
            "Accepts ALF pipe-delimited commands (NEW, AMEND, CANCEL, QUOTE, ...) on "
            "stdin and forwards them to the engine. The gateway ID must be listed in "
            "engine_config.yaml under gateways.alf or the connection is refused.",
        ),
        options=(
            Option("--id GW_ID", "required", "Unique gateway identifier (e.g. GW01, ALICE)"),
            Option(
                "--drop-copy",
                "off",
                "Enable the drop-copy relay on startup (same as sending DC|STATE=ON immediately after connecting)",
            ),
        ),
        has_common_log_options=True,
        related=("pm-engine", "pm-alf-gwy", "pm-orders", "pm-viewer"),
        doc_anchor="pm-alf-console-user-gateway",
        doc_page="055-alf-console.md",
        examples=(
            "pm-alf-console --id GW01",
            "NEW|SYM=AAPL|SIDE=BUY|QTY=100|PRICE=96|TYPE=LIMIT|TIF=DAY   # enter a new limit order",
            "CANCEL|ID=<order-id>                                        # cancel a resting order",
            "ORDERS                                                      # list this gateway's own orders",
        ),
        notes=(
            "Full command vocabulary: NEW (LIMIT, MARKET, STOP, STOP_LIMIT, FOK, ICEBERG, "
            "IOC, TRAILING_STOP), AMEND, CANCEL, QUOTE, QUOTE_CANCEL, QLEGS, ORDERS, "
            "SYMBOLS, KILL, HELP, EXIT/QUIT.",
        ),
    ),
    CommandInfo(
        name="pm-viewer",
        category="Core Runtime",
        title="Order Book Viewer",
        summary="Live full-screen terminal view of a single symbol's order book.",
        synopsis=(
            "pm-viewer --symbol AAPL [--depth N] [--db data/stats.db]",
            "          [--text-color COLOR] [--zebra-lines] [--zebra-lines-color COLOR]",
        ),
        description=(
            "Draws a bordered box on the alternate terminal buffer: a header (last "
            "price, change, session OHLC, bid/ask, spread, volume, clock) plus three "
            "columns (Bids, Asks, Trades). Repaints cleanly on terminal resize. Run "
            "multiple instances for different symbols simultaneously.",
        ),
        options=(
            Option("--symbol, -s SYMBOL", "required", "Symbol to watch"),
            Option("--depth, -d N", "fit to terminal", "Max price levels per side"),
            Option("--db PATH", "data/stats.db", "Stats SQLite DB -- seeds session OHLC and previous-close"),
            Option("--text-color COLOR", "white", "Body text color (#rrggbb hex or Rich color name)"),
            Option("--zebra-lines", "off", "Shade every second row of Bids/Asks/Trades"),
            Option("--zebra-lines-color COLOR", "grey19", "Background tint used by --zebra-lines"),
        ),
        has_common_log_options=True,
        related=("pm-board", "pm-ticker", "pm-orders", "pm-stats"),
        doc_anchor="pm-viewer-order-book-viewer",
        examples=(
            "pm-viewer --symbol AAPL &",
            "pm-viewer --symbol MSFT --depth 10 --zebra-lines",
        ),
        notes=(
            "Iceberg orders only ever show their displayed_qty -- the hidden quantity "
            "is intentionally invisible, demonstrating the iceberg privacy feature.",
        ),
    ),
    CommandInfo(
        name="pm-orders",
        category="Core Runtime",
        title="Order Status Monitor",
        summary="Live cross-gateway table of every order in the system.",
        synopsis=("pm-orders [--gateway GW01] [-v|-vv] [--log-level LEVEL]",),
        description=(
            "Displays ID | Gateway | Symbol | Side | Type | TIF | Qty | Remaining | "
            "Price | Status | Updated, colour-coded by status "
            "(green=NEW, yellow=PARTIAL, bright green=FILLED, red=REJECTED/CANCELLED, dim=EXPIRED).",
        ),
        options=(Option("--gateway, -g GW_ID", "all", "Filter to a single gateway"),),
        has_common_log_options=True,
        related=("pm-viewer", "pm-board", "pm-admin"),
        doc_anchor="pm-orders-order-status-monitor",
    ),
    CommandInfo(
        name="pm-board",
        category="Core Runtime",
        title="Market Board",
        summary="Full-screen multi-symbol market board for large monitors or projection.",
        synopsis=("pm-board [--rows 8] [--interval 10]",),
        description=(
            "Paged table of every active symbol with exchange-style colouring "
            "(Symbol, Last, Chg%, Bid, Ask, Spread, Last Buy/Sell, Vol, Updated). "
            "Auto-rotates pages every --interval seconds; press Enter to advance "
            "immediately. Symbols are auto-discovered -- no configuration needed.",
        ),
        options=(
            Option("--rows, -r N", "8", "Max symbols (rows) displayed per page"),
            Option("--interval, -i SEC", "10", "Seconds before auto-rotating to the next page"),
        ),
        has_common_log_options=True,
        related=("pm-viewer", "pm-ticker"),
        doc_anchor="pm-board-market-board",
        examples=("pm-board --rows 15 --interval 8   # large-screen classroom/conference demo",),
    ),
    CommandInfo(
        name="pm-ticker",
        category="Core Runtime",
        title="Scrolling Market Ticker",
        summary="Scrolling ticker-tape bar of live prices and OHLCV across all symbols.",
        synopsis=("pm-ticker [--db data/stats.db] [--db-interval 900] [--timezone TZ]",),
        description=(
            "A bordered header (brand, today's total volume, clock) plus a single "
            "scrolling line combining live ZMQ data (last price, bid/ask) with "
            "historical DB data (OHLCV, trade count) from pm-stats's SQLite database. "
            "Without pm-stats running it still works but omits OHLCV/volume/trade count.",
        ),
        options=(
            Option("--db PATH", "data/stats.db", "Path to the statistics SQLite database"),
            Option("--db-interval SEC", "900", "Seconds between daily_stats DB re-queries"),
            Option("--timezone TZ", "DB-recorded timezone", "Exchange session timezone (IANA name)"),
        ),
        has_common_log_options=True,
        related=("pm-stats", "pm-board", "pm-viewer"),
        doc_anchor="pm-ticker-scrolling-market-ticker",
    ),
    CommandInfo(
        name="pm-stats",
        category="Core Runtime",
        title="Statistics Recorder",
        summary="Records OHLCV, trade log, and index-level history to stats.db.",
        synopsis=(
            "pm-stats [--db data/stats.db] [--snapshot-interval SEC] [--timezone TZ]",
            "         [--sql-trace] [-v|-vv] [--log-level LEVEL]",
        ),
        description=(
            "The queryable time-series home for both trading statistics and index "
            "level history (pm-index's own JSONL only keeps structural/audit records, "
            "not level ticks). Maintains three tables: daily_stats (one row per "
            "date+symbol), price_snapshots (periodic mid-price), and trade_log "
            "(append-only per-trade rows). Recommended to run immediately after pm-engine.",
        ),
        options=(
            Option("--db PATH", "data/stats.db", "SQLite database file path"),
            Option(
                "--snapshot-interval SEC",
                "900",
                "Seconds between price_snapshots rows per symbol",
            ),
            Option(
                "--timezone TZ",
                "UTC",
                "Session timezone (IANA name) defining the trading date; must match pm-clearing's --timezone",
            ),
            Option("--sql-trace", "off", "Log executed SQLite statements from the stats writer connection"),
        ),
        has_common_log_options=True,
        related=("pm-stats-cli", "pm-clearing", "pm-index", "pm-ticker", "pm-board"),
        doc_anchor="pm-stats-statistics-recorder",
        doc_page="140-statistics-and-reporting.md",
        notes=(
            "Opens two independent PUB/SUB connections: pm-engine (:5556) for "
            "trade.*/book.*/system.eod, and pm-index (:5558) for index.update.",
        ),
    ),
    CommandInfo(
        name="pm-clearing",
        category="Core Runtime",
        title="Clearing & P&L",
        summary="SQLite-backed clearing writer computing realized/unrealized P&L and positions.",
        synopsis=(
            "pm-clearing [--datapath PATH] [--db-name NAME] [--flush-size N]",
            "            [--flush-interval SEC] [--retention-days N] [--timezone TZ]",
        ),
        description=(
            "Subscribes to trade.executed and writes gateway positions, daily "
            "summaries, and raw trade events to clearing.db in batched transactions.",
        ),
        options=(
            Option("--datapath PATH", "$EDUMATCHER_DATA_DIR", "Data directory or explicit .db path"),
            Option("--db-name NAME", "clearing.db", "SQLite filename when --datapath is a directory"),
            Option("--flush-size N", "100", "Flush immediately when buffered trades reach N"),
            Option("--flush-interval SEC", "5.0", "Flush interval when the buffer is non-empty"),
            Option("--print-every N", "100", "Print in-memory P&L snapshot every N trades (0 disables)"),
            Option("--retention-days N", "90", "Prune trade_events rows older than N days on startup (0 disables)"),
            Option(
                "--timezone TZ",
                "UTC",
                "Session timezone (IANA name); must match pm-stats's --timezone or daily rollups won't reconcile",
            ),
            Option("--sql-trace", "off", "Log executed SQLite statements from the clearing writer connection"),
        ),
        has_common_log_options=True,
        related=("pm-clearing-cli", "pm-stats"),
        doc_anchor="pm-clearing-clearing-pl",
        doc_page="130-pnl-clearing.md",
    ),
    CommandInfo(
        name="pm-audit",
        category="Core Runtime",
        title="Event Logger",
        summary="Records every message on the bus to a rotating audit log file.",
        synopsis=(
            "pm-audit [--audit-log-file data/audit.log] [--terminal]",
            "         [--buffer-size 100] [--flush-interval 10]",
        ),
        description=(
            "Subscribes to everything published on :5556 with an empty topic prefix "
            "and appends each entry to a rotating log file (10 MB, 5 backups), "
            "buffering to reduce disk wear. On shutdown, buffered messages are always "
            "flushed before exit.",
        ),
        options=(
            Option("--audit-log-file PATH", "data/audit.log", "Audit-trail output log file path"),
            Option("--terminal, -t", "off", "Also print each entry to stdout"),
            Option("--buffer-size N", "100", "Messages buffered in memory before writing to disk"),
            Option("--flush-interval SEC", "10.0", "Max seconds before flushing the buffer to disk"),
        ),
        has_common_log_options=True,
        related=("pm-audit-cli", "pm-stats", "pm-clearing"),
        doc_anchor="pm-audit-event-logger",
        examples=(
            "pm-audit --terminal                              # show every event live during a demo",
            "pm-audit --buffer-size 500 --flush-interval 30    # high-traffic: larger buffer",
            "pm-audit --buffer-size 1 --flush-interval 0.1     # low-latency: flush almost every message",
        ),
    ),
    CommandInfo(
        name="pm-scheduler",
        category="Core Runtime",
        title="Session Scheduler",
        summary="Drives session-phase transitions at configured wall-clock times.",
        synopsis=("pm-scheduler [--now] [--delay 3] [--daily] [--no-confirm]",),
        description=(
            "Sends session.transition to the engine to advance "
            "PRE_OPEN -> OPENING_AUCTION -> CONTINUOUS -> CLOSING_AUCTION -> CLOSED "
            "at the times configured in engine_config.yaml. Fire-and-forget: does "
            "not subscribe to anything.",
        ),
        options=(
            Option("--now", "off", "Skip wall-clock waiting; send all transitions immediately with --delay between each"),
            Option("--delay SEC", "3.0 (with --now)", "Seconds between transitions in --now mode"),
            Option("--daily", "off", "Run continuously, repeating the schedule every calendar day"),
            Option("--no-confirm", "off", "Do not query/confirm session state via the engine before transitioning"),
        ),
        has_common_log_options=True,
        related=("pm-engine", "pm-admin"),
        doc_anchor="pm-scheduler-session-scheduler",
        doc_page="080-session-scheduling.md",
    ),
)


# ---------------------------------------------------------------------------
# External Gateways
# ---------------------------------------------------------------------------

_EXTERNAL_GATEWAYS: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-alf-gwy",
        category="External Gateways",
        title="ALF TCP Gateway",
        summary="External ALF order-entry gateway for bots/remote clients over plain TCP.",
        synopsis=("pm-alf-gwy [--bind 0.0.0.0] [--port 5565] [--engine-host HOST]",),
        description=(
            "Accepts the same ALF command vocabulary as pm-alf-console but over a "
            "TCP socket instead of stdin, for programmatic clients. Any configured "
            "gateways.alf ID may connect; each connection is one gateway session, "
            "starting with a HELLO|CLIENT=...|PROTO=ALF1|ID=<gateway-id> line.",
        ),
        options=(
            Option("--bind ADDR", "0.0.0.0", "TCP bind address for external clients"),
            Option("--port PORT", "5565", "TCP listen port for ALF clients"),
            Option("--engine-host HOST", "from config", "Override engine host for ZMQ ports 5555/5556"),
        ),
        has_common_log_options=True,
        ports="Listens on TCP 5565 (ALF); connects out to 5555, 5556, 5557",
        related=("pm-alf-console", "pm-engine", "pm-balf-gwy"),
        doc_anchor="pm-alf-gwy-alf-tcp-gateway",
        doc_page="220-alf-gateway.md",
    ),
    CommandInfo(
        name="pm-balf-gwy",
        category="External Gateways",
        title="BALF TCP Gateway",
        summary="External binary order-entry gateway (BALF) for low-latency programmatic clients.",
        synopsis=("pm-balf-gwy [--bind 0.0.0.0] [--port 5560] [--engine-host HOST]",),
        description=(
            "Accepts BALF binary frames over TCP and translates them into the same "
            "engine order flow used by the ALF gateways.",
        ),
        options=(
            Option("--bind ADDR", "0.0.0.0", "TCP bind address for BALF clients"),
            Option("--port PORT", "5560", "TCP listen port for BALF clients"),
            Option("--engine-host HOST", "from config", "Override engine host for ZMQ ports 5555/5556"),
        ),
        has_common_log_options=True,
        ports="Listens on TCP 5560 (BALF binary); connects out to 5555, 5556",
        related=("pm-alf-gwy", "pm-engine"),
        doc_anchor="pm-balf-gwy-balf-tcp-gateway",
        doc_page="230-balf-gateway.md",
    ),
    CommandInfo(
        name="pm-md-gwy",
        category="External Gateways",
        title="CALF Market-Data Gateway",
        summary="External market-data gateway distributing top/trade/state channels over CALF/TCP.",
        synopsis=(
            "pm-md-gwy [--bind 0.0.0.0] [--port 5570] [--engine-pub tcp://127.0.0.1:5556]",
            "          [--index-pub tcp://127.0.0.1:5558]",
        ),
        description=(
            "Consumes the engine and index PUB feeds internally and republishes "
            "sequence-aware TOP, TRADE, and STATE channels to external CALF clients.",
        ),
        options=(
            Option("--bind ADDR", "0.0.0.0", "TCP bind address for external clients"),
            Option("--port PORT", "5570", "TCP listen port for CALF clients"),
            Option("--engine-pub ADDR", "tcp://127.0.0.1:5556", "Engine PUB address consumed by the gateway"),
            Option("--index-pub ADDR", "tcp://127.0.0.1:5558", "Index PUB socket address (overrides config)"),
        ),
        has_common_log_options=True,
        ports="Listens on TCP 5570 (CALF); connects out to 5556, 5558",
        related=("pm-calf-spy", "pm-index", "pm-engine"),
        doc_anchor="pm-md-gwy-calf-market-data-gateway",
        doc_page="240-calf-gateway.md",
    ),
    CommandInfo(
        name="pm-ralf-gwy",
        category="External Gateways",
        title="Post-Trade Dissemination Gateway",
        summary="External post-trade dissemination gateway (RALF) for clearing/drop-copy/audit consumers.",
        synopsis=(
            "pm-ralf-gwy [--bind 0.0.0.0] [--port 5580] [--engine-pub tcp://127.0.0.1:5556]",
        ),
        description=(
            "Publishes RALF over TCP: WELCOME, SNAP, EXEC, EOD, HB, PONG, ERR, EXIT "
            "message types, role-gated (CLEARING, DROP_COPY, AUDIT).",
        ),
        options=(
            Option("--bind ADDR", "0.0.0.0", "TCP bind address for external clients"),
            Option("--port PORT", "5580", "TCP listen port for RALF clients"),
            Option("--engine-pub ADDR", "tcp://127.0.0.1:5556", "Engine PUB address consumed by the gateway"),
        ),
        has_common_log_options=True,
        ports="Listens on TCP 5580 (RALF); connects out to 5556",
        related=("pm-ralf-spy", "pm-engine"),
        doc_anchor="pm-ralf-gwy-post-trade-dissemination-gateway",
        doc_page="250-ralf-gateway.md",
    ),
    CommandInfo(
        name="pm-dc-gwy",
        category="External Gateways",
        title="Drop-Copy TCP Gateway",
        summary="Relays the engine's drop-copy fill feed as DC1 text lines to plain-TCP clients.",
        synopsis=(
            "pm-dc-gwy [--bind 0.0.0.0] [--port 5590] [--engine-dc-pub tcp://127.0.0.1:5557]",
        ),
        description=(
            "TCP counterpart to pm-dc-spy: fans drop_copy.event.<gateway_id> out to "
            "any number of concurrently connected external clients. No "
            "authentication, entitlement model, or replay-by-sequence -- any client "
            "may HELLO with any gateway ID.",
        ),
        options=(
            Option("--bind ADDR", "0.0.0.0", "TCP bind address for external clients"),
            Option("--port PORT", "5590", "TCP listen port for DC1 clients"),
            Option("--engine-dc-pub ADDR", "tcp://127.0.0.1:5557", "Engine drop-copy PUB address consumed by the gateway"),
        ),
        has_common_log_options=True,
        ports="Listens on TCP 5590 (DC1); connects out to 5557",
        related=("pm-dc-spy", "pm-engine"),
        doc_anchor="pm-dc-gwy-drop-copy-tcp-gateway",
        doc_page="201-dc-gateway.md",
    ),
    CommandInfo(
        name="pm-api-gwy",
        category="External Gateways",
        title="REST/WebSocket API Gateway",
        summary="Exposes order entry, order management, and market data over REST/JSON and WebSocket.",
        synopsis=(
            "pm-api-gwy [--instance NAME] [--host ADDR] [--port PORT]",
            "           [--engine-host HOST] [--stats-db PATH]",
        ),
        description=(
            "Not a second matching engine -- translates HTTP/WebSocket requests into "
            "the same ZMQ order flow used by pm-alf-console. Reads its named entry "
            "from the api_gateways: section of engine_config.yaml. Authenticates via "
            "Authorization: Bearer <api_key> (REST) or a first JSON message "
            "{\"api_key\": \"<key>\"} (WebSocket).",
        ),
        options=(
            Option("--instance NAME", "auto-selected if only one entry", "Named api_gateways entry to run"),
            Option("--host ADDR", "config value", "Override HTTP bind address"),
            Option("--port PORT", "config value", "Override HTTP listen port"),
            Option("--engine-host HOST", "config value", "Override engine host for ZMQ connections"),
            Option("--stats-db PATH", "config value", "Path to data/stats.db for /history/* endpoints"),
        ),
        has_common_log_options=True,
        ports="Listens on HTTP/WS at its configured port (e.g. 8080 desk, 8081 dashboards); connects out to 5555, 5556",
        related=("pm-alf-console", "pm-stats"),
        doc_anchor="pm-api-gwy-restwebsocket-api-gateway",
        doc_page="260-api-gateway.md",
        notes=("Browse http://127.0.0.1:<PORT>/docs for interactive Swagger docs when swagger_enabled: true.",),
    ),
)


# ---------------------------------------------------------------------------
# Protocol Spies -- read-only CLI clients that print exactly what a gateway
# sends, for learning the wire protocol without writing a client.
# ---------------------------------------------------------------------------

_PROTOCOL_SPIES: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-calf-spy",
        category="Protocol Spies",
        title="CALF Protocol Spy",
        summary="Read-only CALF client: prints every line pm-md-gwy sends, human or JSON.",
        synopsis=(
            "pm-calf-spy [--channels CH] [--symbols SYM] [--ping-interval SEC]",
            "            [--format human|json]",
        ),
        description=(
            "Opens a CALF TCP session against pm-md-gwy, subscribes to the requested "
            "channels/symbols, and prints every line received. Never mutates exchange "
            "state; any number of instances can run concurrently. Sends a periodic "
            "PING (default 60s) to avoid being dropped as idle.",
        ),
        options=(
            Option("--host ADDR", "127.0.0.1", "pm-md-gwy TCP host"),
            Option("--port PORT", "5570", "pm-md-gwy TCP port"),
            Option("--client-name NAME", "calf-spy-<pid>", "HELLO|CLIENT= identifier reported in gateway logs"),
            Option("--channels CH", "*", "Comma-separated channels; * = every channel offered"),
            Option("--symbols SYM", "*", "Comma-separated symbols; * = wildcard where allowed"),
            Option("--resume CH:SYM:LASTSEQ", "none", "One-shot single-stream replay request on connect"),
            Option("--ping-interval SEC", "60", "Seconds between PING keepalives; 0 disables"),
            Option("--format human|json", "human", "Output format"),
            Option("--count N", "0", "Exit after N data-carrying lines (0 = run until Ctrl-C)"),
            Option("--raw", "off", "Print raw protocol bytes instead of decoded fields"),
            Option("--no-color", "off", "Disable ANSI colour in output"),
            Option("--show-heartbeats", "off", "Include HB heartbeat lines in output"),
        ),
        has_common_log_options=True,
        related=("pm-md-gwy", "pm-ralf-spy", "pm-dc-spy"),
        doc_anchor="pm-calf-spy-calf-protocol-spy",
        doc_page="241-calf-spy-cli.md",
    ),
    CommandInfo(
        name="pm-ralf-spy",
        category="Protocol Spies",
        title="RALF Protocol Spy",
        summary="Read-only RALF client: prints every line pm-ralf-gwy sends, human or JSON.",
        synopsis=(
            "pm-ralf-spy --role ROLE [--channels CH] [--symbols SYM]",
            "            [--ping-interval SEC] [--format human|json]",
        ),
        description=(
            "Opens a RALF TCP session under a chosen role (CLEARING, DROP_COPY, or "
            "AUDIT) and prints every line received. Never mutates exchange state; "
            "any number of instances can run concurrently, each with its own role/filter.",
        ),
        options=(
            Option("--host ADDR", "127.0.0.1", "pm-ralf-gwy TCP host"),
            Option("--port PORT", "5580", "pm-ralf-gwy TCP port"),
            Option("--client-name NAME", "ralf-spy-<pid>", "HELLO|CLIENT= identifier reported in gateway logs"),
            Option("--role ROLE", "AUDIT", "HELLO|ROLE= to authenticate as: CLEARING, DROP_COPY, or AUDIT"),
            Option("--channels CH", "*", "Comma-separated channels; * = every channel --role is entitled to"),
            Option("--symbols SYM", "*", "Comma-separated symbols; * = every symbol"),
            Option("--lastseq N", "0", "Requests replay on connect via HELLO|LASTSEQ=N (0 = no replay)"),
            Option("--ping-interval SEC", "60", "Seconds between PING keepalives; 0 disables"),
            Option("--format human|json", "human", "Output format"),
            Option("--count N", "0", "Exit after N data-carrying lines (0 = run until Ctrl-C)"),
            Option("--raw", "off", "Print raw protocol bytes instead of decoded fields"),
            Option("--no-color", "off", "Disable ANSI colour in output"),
            Option("--show-heartbeats", "off", "Include HB heartbeat lines in output"),
        ),
        has_common_log_options=True,
        related=("pm-ralf-gwy", "pm-calf-spy", "pm-dc-spy"),
        doc_anchor="pm-ralf-spy-ralf-protocol-spy",
        doc_page="251-ralf-spy-cli.md",
    ),
    CommandInfo(
        name="pm-dc-spy",
        category="Protocol Spies",
        title="Drop-Copy Spy",
        summary="Read-only drop-copy client: prints every fill event from the engine's :5557 feed.",
        synopsis=("pm-dc-spy [--gateway GW_ID] [--replay-of ID] [--format human|json]",),
        description=(
            "Opens a plain zmq.SUB connection directly to the engine's drop-copy PUB "
            "socket -- no handshake or heartbeat, unlike CALF/RALF. Subscribes to "
            "fills for one gateway or all gateways.",
        ),
        options=(
            Option("--host ADDR", "127.0.0.1", "Drop-copy PUB socket host"),
            Option("--port PORT", "5557", "Drop-copy PUB socket port"),
            Option("--gateway GW_ID", "none (all)", "Only show fills for this gateway"),
            Option("--replay-of ID", "none", "Also subscribe to drop_copy.replay.<RECIPIENT_ID>"),
            Option("--format human|json", "human", "Output format"),
            Option("--count N", "0", "Exit after N messages (0 = run until Ctrl-C)"),
            Option("--raw", "off", "Print raw bytes instead of decoded fields"),
            Option("--no-color", "off", "Disable ANSI colour in output"),
        ),
        has_common_log_options=True,
        related=("pm-dc-gwy", "pm-engine"),
        doc_anchor="pm-dc-spy-drop-copy-spy",
        doc_page="202-dc-spy-cli.md",
    ),
)


# ---------------------------------------------------------------------------
# AI & Bots
# ---------------------------------------------------------------------------

_AI_AND_BOTS: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-ai-trader",
        category="AI & Bots",
        title="Autonomous Trader Bot",
        summary="One autonomous trading gateway with a selectable behaviour profile.",
        synopsis=("pm-ai-trader --id AI01 [--profile cautious] [--symbols AAPL,MSFT] [options]",),
        description=(
            "On every startup/reconnect: authenticates, requests the symbol universe "
            "(tick size, prev close), queries current session state and per-symbol "
            "halt flags, and re-seeds its position/average cost from the engine's "
            "ledger -- so risk guards stay accurate across restarts.",
        ),
        options=(
            Option("--id GW_ID", "required", "Gateway ID used by the bot (e.g. AI01)"),
            Option("--profile NAME", "cautious", "Personality profile"),
            Option("--symbols LIST", "empty (all)", "Comma-separated symbol allowlist"),
            Option("--seed N", "1", "RNG seed for deterministic behaviour"),
            Option("--duration SEC", "0 (until stopped)", "Runtime in seconds"),
            Option("--run-id LABEL", "autogenerated", "Optional run label for audit/traceability"),
            Option("--max-position N", "1000", "Absolute per-symbol position limit"),
            Option("--max-rejects N", "25", "Reject threshold before the cooldown breaker trips"),
            Option("--reject-window SEC", "10.0", "Rolling reject window in seconds"),
            Option("--reject-cooldown SEC", "5.0", "Pause interval after the reject breaker trips"),
            Option("--stale-data SEC", "4.0", "Max market-data age before pausing orders"),
        ),
        has_common_log_options=True,
        related=("pm-ai-swarm", "pm-mm-bot", "pm-engine"),
        doc_anchor="pm-ai-trader-autonomous-trader-bot",
        doc_page="110-ai-traders.md",
    ),
    CommandInfo(
        name="pm-ai-swarm",
        category="AI & Bots",
        title="Multi-Agent Trading Swarm",
        summary="Launches and supervises multiple pm-ai-trader bots as a coordinated swarm.",
        synopsis=("pm-ai-swarm [--count 10] [--prefix AI] [--profiles all] [--duration 60] [options]",),
        options=(
            Option("--count N", "10", "Number of bot processes to launch"),
            Option("--prefix STR", "AI", "Gateway-ID prefix"),
            Option("--start-index N", "1", "First numeric suffix for generated IDs"),
            Option("--profiles LIST", "all profiles", "Comma-separated profile cycle"),
            Option("--symbols LIST", "from config", "Comma-separated symbol list override"),
            Option("--seed-base N", "1000", "Base seed; bot i gets seed-base + i"),
            Option("--duration SEC", "60.0", "Per-bot runtime in seconds"),
            Option("--python PATH", "current interpreter", "Python executable used for child processes"),
            Option("--max-position N", "1000", "Passed through to child bots"),
            Option("--max-rejects N", "25", "Passed through to child bots"),
            Option("--reject-window SEC", "10.0", "Passed through to child bots"),
            Option("--reject-cooldown SEC", "5.0", "Passed through to child bots"),
            Option("--stale-data SEC", "4.0", "Passed through to child bots"),
        ),
        has_common_log_options=True,
        related=("pm-ai-trader", "pm-mm-bot"),
        doc_anchor="pm-ai-swarm-multi-agent-trading-swarm",
        doc_page="110-ai-traders.md",
    ),
    CommandInfo(
        name="pm-mm-bot",
        category="AI & Bots",
        title="Autonomous Market-Maker Bot",
        summary="Autonomous two-sided quoting bot for one symbol; connects as MARKET_MAKER.",
        synopsis=("pm-mm-bot --symbol AAPL [--gap 0.10] [--qty 500] [--id-suffix 01] [options]",),
        description=(
            "Posts a two-sided quote and automatically reprices on fills, mid-price "
            "drift, and session transitions. The gateway ID is constructed as "
            "MM_<SYMBOL>_<suffix> and must be pre-registered with role: MARKET_MAKER. "
            "Run multiple instances (different --id-suffix) to cover several symbols "
            "or compete on the same one.",
        ),
        options=(
            Option("--symbol SYMBOL", "required", "Instrument to make a market in"),
            Option("--gap PRICE", "0.10", "Total spread (bid at mid-gap/2, ask at mid+gap/2)"),
            Option("--qty N", "500", "Quote size on each leg"),
            Option("--id-suffix STR", "01", "Running number for gateway ID (MM_AAPL_01)"),
            Option("--drift-ticks N", "3", "Reprice when mid moves by this many ticks"),
            Option("--reissue-delay-ms MS", "200", "Milliseconds to wait after fill before re-issuing"),
            Option("--tif DAY|GTC", "DAY", "Time-in-force for quote legs"),
            Option("--heartbeat-interval-sec SEC", "5.0", "Periodic live-quote check interval"),
            Option("--initial_min / --initial_max", "unset", "Bounds for random bootstrap price"),
            Option("--engine-pull ADDR", "tcp://127.0.0.1:5555", "Engine PUSH/PULL address"),
            Option("--engine-pub ADDR", "tcp://127.0.0.1:5556", "Engine PUB address"),
        ),
        has_common_log_options=True,
        related=("pm-ai-trader", "pm-engine", "pm-alf-console"),
        doc_anchor="pm-mm-bot-autonomous-market-maker-bot",
        doc_page="100-mm-bot.md",
        examples=("pm-mm-bot --symbol AAPL --gap 0.10 --qty 500",),
        notes=(
            "Reference price resolution order: active quote from QBOOT (restart "
            "recovery), book mid-price, last trade price, QBOOT bootstrap snapshot, "
            "then a random price from [--initial_min, --initial_max].",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

_INDEX: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-index",
        category="Index",
        title="Index Calculation Process",
        summary="Maintains one or more cap-weighted market indices in real time.",
        synopsis=("pm-index [--reset] [-v|-vv] [--log-level LEVEL]",),
        description=(
            "Subscribes to trade.executed from the engine and publishes live index "
            "values on a dedicated PUB socket so pm-md-gwy can forward them over the "
            "CALF INDEX channel. Persists structural/audit history (INIT, "
            "CORP_ACTION, ADD_CONSTITUENT, DELIST) as JSONL; level/EOD ticks are "
            "recorded by pm-stats instead.",
        ),
        options=(Option("--reset", "off", "Delete persisted state files and reinitialise all indices from config"),),
        has_common_log_options=True,
        ports="Binds 5558 (PUB, index.update), 5559 (PULL, operator commands); connects out to 5556",
        related=("pm-index-cli", "pm-index-admin-cli", "pm-stats-cli", "pm-md-gwy"),
        doc_anchor="pm-index-index-calculation-process",
        doc_page="150-market-index.md",
    ),
    CommandInfo(
        name="pm-index-cli",
        category="Index",
        title="Index Structural/Audit History Query Tool",
        summary="Read-only offline query of pm-index's structural/corporate-action JSONL history.",
        synopsis=("pm-index-cli [--config engine_config.yaml] [--format table|json|csv] COMMAND [options]",),
        description=(
            "Reads history files directly from disk -- no running process required. "
            "Does not expose level/EOD history; use `pm-stats-cli index-daily` / "
            "`index-snapshots` for that instead.",
        ),
        options=(
            Option("--config, -c PATH", "unset", "Path to engine_config.yaml; auto-discovers history files and index IDs"),
            Option("--data-dir DIR", "data/indexes", "Directory containing history files, when --config is absent"),
            Option("--format table|json|csv", "table", "Output format"),
            Option("--no-header", "off", "Suppress header row (CSV only)"),
        ),
        subcommands=(
            Subcommand("events", purpose="Structural events: INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST"),
            Subcommand("indices", purpose="List configured indices from engine_config.yaml"),
        ),
        related=("pm-index", "pm-index-admin-cli", "pm-stats-cli"),
        doc_anchor="pm-index-cli-index-structuralaudit-history-query-tool",
        doc_page="160-exchange-commands.md",
        examples=("pm-index-cli events --index MYIDX --days 30",),
    ),
    CommandInfo(
        name="pm-index-admin-cli",
        category="Index",
        title="Index Corporate Action / Constituent Change CLI",
        summary="One-shot write tool for splits, dividends, share changes, and constituent add/delist.",
        synopsis=(
            "pm-index-admin-cli --id <GW_ID> [--push ADDR] [--sub ADDR] [--timeout MS]",
            "                    [--dry-run] [-y] [--format table|json] COMMAND [options]",
        ),
        description=(
            "Talks directly to pm-index's live PUSH/PULL socket pair -- unlike "
            "pm-index-cli, it does not read JSONL files and does not require "
            "--config. Has no connect()/authentication step: pm-index's PULL socket "
            "accepts any non-empty gateway_id, used only as an ack-routing key.",
        ),
        options=(
            Option("--id GW_ID", "required", "Ack-routing label -- not authenticated by pm-index"),
            Option("--push ADDR", "tcp://127.0.0.1:5559", "pm-index PULL socket address"),
            Option("--sub ADDR", "tcp://127.0.0.1:5558", "pm-index PUB socket address"),
            Option("--timeout MS", "3000", "Ack timeout in milliseconds"),
            Option("--dry-run", "off", "Print the outbound payload instead of sending it"),
            Option("-y, --yes", "off", "Skip the confirmation prompt"),
            Option("--format table|json", "table", "Output format"),
        ),
        subcommands=(
            Subcommand("split", purpose="Apply a stock split or reverse split"),
            Subcommand("dividend", purpose="Apply a cash dividend adjustment"),
            Subcommand("shares", purpose="Set shares outstanding -- covers issuances and buy-backs"),
            Subcommand("add", purpose="Add a new constituent"),
            Subcommand("delist", purpose="Remove a constituent"),
            Subcommand("history", purpose="Show recent structural/corp-action history for an index"),
        ),
        related=("pm-index", "pm-index-cli"),
        doc_anchor="pm-index-admin-cli-index-corporate-action-constituent-change-cli",
        doc_page="152-index-admin-cli.md",
        notes=(
            "Every mutating subcommand prompts \"Continue? [y/N]\" unless -y/--yes is given.",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Query & Reporting CLIs -- read-only offline tools that query a SQLite/JSONL
# store directly, without connecting to any running process.
# ---------------------------------------------------------------------------

_QUERY_CLIS: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-audit-cli",
        category="Query & Reporting CLIs",
        title="Audit Log Query CLI",
        summary="Read-only offline query of pm-audit's rotating JSONL log files.",
        synopsis=(
            "pm-audit-cli [--log-file data/audit.log] [--log-dir PATH]",
            "             [--format table|json|csv] COMMAND [options]",
        ),
        options=(
            Option("--log-file PATH", "data/audit.log", "Primary audit log file"),
            Option("--log-dir PATH", "directory of --log-file", "Directory containing rotated log backups"),
            Option("--format table|json|csv", "table", "Output format"),
            Option("--no-header", "off", "Suppress header row in CSV output"),
            Option("--use-index PATH", "auto-detected", "Path to the optional SQLite index file"),
        ),
        subcommands=(
            Subcommand("events", args="[options]", purpose="Search log entries by topic, gateway, symbol, and time range (default limit 100)"),
            Subcommand("orders", args="[options]", purpose="Order lifecycle events for specific order IDs or filters (default limit 100)"),
            Subcommand("trades", args="[options]", purpose="Trade executions (default limit 100)"),
            Subcommand("topics", purpose="List topics present in logs with event counts"),
            Subcommand("gateways", purpose="Gateway activity summary"),
            Subcommand("timeline", args="[options]", purpose="Raw chronological event stream for session replay (default limit 500)"),
            Subcommand("stats", purpose="Summary statistics about audit log files"),
            Subcommand("index", args="[--output PATH]", purpose="Build or update the optional SQLite index for faster queries"),
        ),
        related=("pm-audit", "pm-stats-cli", "pm-clearing-cli"),
        doc_anchor="pm-audit-cli-audit-log-query-cli",
        examples=("pm-audit-cli trades --symbol AAPL --from 2026-06-01 --to 2026-06-05",),
    ),
    CommandInfo(
        name="pm-clearing-cli",
        category="Query & Reporting CLIs",
        title="Clearing Query CLI",
        summary="Command-line query interface for clearing.db, including a prune maintenance command.",
        synopsis=(
            "pm-clearing-cli [--datapath PATH] [--db-name clearing.db]",
            "                [--format table|json|csv] [--raw-output] COMMAND [options]",
        ),
        description=("Unlike pm-clearing, this is a one-shot tool: runs one query, prints output, exits.",),
        options=(
            Option("--datapath PATH", "resolved from $EDUMATCHER_DATA_DIR", "Data directory or explicit .db file path"),
            Option("--db-name NAME", "clearing.db", "SQLite filename when --datapath is a directory"),
            Option("--format table|json|csv", "table", "Output format"),
            Option("--no-header", "off", "Suppress header row in CSV output"),
            Option("--raw-output", "off", "Disable tick-decimal normalization; emit raw tick-unit values"),
        ),
        subcommands=(
            Subcommand("gateways", purpose="Gateway-level realized/unrealized/total P&L totals (limit 1000)"),
            Subcommand("positions", purpose="Current open position state by gateway and symbol (limit 10000)"),
            Subcommand("pnl", purpose="Realized/unrealized/total P&L rows per gateway and symbol (limit 10000)"),
            Subcommand("daily", purpose="Daily rollup summary rows (limit 1000)"),
            Subcommand("trades", purpose="Raw trade-event rows (limit 200)"),
            Subcommand("exposure", purpose="Net/gross notional exposure and P&L (limit 1000)"),
            Subcommand("symbols", purpose="Symbol-level totals and open exposure snapshot (limit 1000)"),
            Subcommand("dates", purpose="Available trade dates, optionally with totals (limit 1000)"),
            Subcommand("health", purpose="DB row counts, flush metadata, and WAL mode"),
            Subcommand("reconcile", purpose="Compares raw trade_events vs daily summary for discrepancies"),
            Subcommand("sessions", purpose="Gateway connection/disconnection history (limit 500)"),
            Subcommand("eod", purpose="End-of-day sentinel events written by pm-clearing (limit 100)"),
            Subcommand("prune", args="[--days N] [--dry-run]", purpose="Delete old trade_events rows by retention window"),
        ),
        related=("pm-clearing", "pm-stats-cli", "pm-audit-cli"),
        doc_anchor="pm-clearing-cli-clearing-query-cli",
        doc_page="130-pnl-clearing.md",
        examples=(
            "pm-clearing-cli gateways",
            "pm-clearing-cli --format json positions --gateway MM01",
            "pm-clearing-cli exposure --sort total_pnl",
            "pm-clearing-cli prune --days 90 --dry-run",
        ),
    ),
    CommandInfo(
        name="pm-stats-cli",
        category="Query & Reporting CLIs",
        title="Statistics Query CLI",
        summary="Read-only query interface for stats.db (OHLCV, trades, snapshots, index history).",
        synopsis=("pm-stats-cli [--db data/stats.db] [--format table|json|csv] [--timezone TZ] COMMAND [options]",),
        description=("Runs one query, prints output, and exits -- not a subscriber process.",),
        options=(
            Option("--db PATH", "data/stats.db", "SQLite database file path"),
            Option("--format table|json|csv", "table", "Output format"),
            Option("--no-header", "off", "Suppress header row in csv output"),
            Option("--timezone TZ", "DB-recorded timezone", "Override the session timezone --date resolves in"),
        ),
        subcommands=(
            Subcommand("daily", purpose="Daily OHLCV summary from daily_stats"),
            Subcommand("snapshots", purpose="Intraday snapshots from price_snapshots (--symbol required)"),
            Subcommand("trades", purpose="Trade history from trade_log"),
            Subcommand("order-events", purpose="Private order lifecycle events (--gateway required)"),
            Subcommand("order-lifecycle", purpose="All events for a single order ID (--gateway, --order-id required)"),
            Subcommand("symbols", purpose="Discover symbols available in stats data"),
            Subcommand("dates", purpose="Discover trading dates available in daily_stats"),
            Subcommand("index-daily", purpose="Daily index OHLC rollup from index_daily_stats"),
            Subcommand("index-snapshots", purpose="Every recorded index level tick (--index-id required)"),
            Subcommand("index-ids", purpose="Discover index IDs with recorded data"),
            Subcommand("instruments", purpose="Instrument reference data (tick scale per symbol)"),
            Subcommand("gaps", purpose="Detected feed gaps -- trades the recorder never received"),
            Subcommand("health", purpose="Check the pm-stats process and stats DB read/write health"),
        ),
        related=("pm-stats", "pm-clearing-cli", "pm-index-cli"),
        doc_anchor="pm-stats-cli-statistics-query-cli",
        doc_page="140-statistics-and-reporting.md",
        examples=(
            "pm-stats-cli daily --date 2026-06-14 --symbol AAPL",
            "pm-stats-cli snapshots --symbol MSFT --from 2026-06-14T09:00:00+00:00 --to 2026-06-14T16:30:00+00:00",
            "pm-stats-cli --format csv trades --symbol AAPL --date 2026-06-14",
        ),
        notes=("--after CURSOR pages through results using the cursor from a previous call's last row.",),
    ),
)


# ---------------------------------------------------------------------------
# Admin & Operations
# ---------------------------------------------------------------------------

_ADMIN_AND_OPS: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-admin",
        category="Admin & Operations",
        title="Interactive Admin Console",
        summary="Interactive REPL for operator commands (halt, kill, kick) without a full gateway.",
        synopsis=("pm-admin --id <ADMIN_GW_ID> [-v|-vv] [--log-level LEVEL]",),
        description=(
            "The prompt is coloured red to distinguish it from pm-alf-console. Tab "
            "completion and arrow-key history work the same way. The --id must be "
            "an entry in engine_config.yaml with role: ADMIN.",
        ),
        options=(Option("--id ADMIN_GW_ID", "required", "ADMIN gateway ID configured in engine_config.yaml"),),
        has_common_log_options=True,
        subcommands=(
            Subcommand("HALT / RESUME", purpose="Exchange-wide circuit-breaker halt / lift it"),
            Subcommand("HALT_SYM / RESUME_SYM", args="SYM=<sym>", purpose="Halt / resume a single symbol"),
            Subcommand("CANCEL_SYM", args="SYM=<sym>", purpose="Cancel all resting orders for a symbol"),
            Subcommand("KILL", args="GW=<gw>[|SYM=<sym>]", purpose="Cancel all (or symbol-scoped) orders/quotes for a gateway"),
            Subcommand("KICK", args="GW=<gw>[|REASON=<text>]", purpose="Forcefully disconnect a gateway"),
            Subcommand("QCANCEL", args="GW=<gw>|SYM=<sym>", purpose="Cancel an MM's active quote on one symbol"),
            Subcommand("BOOK", args="SYM=<sym>", purpose="Print L1/L2 order-book snapshot"),
            Subcommand("ORDERS", args="GW=<gw>", purpose="List resting orders for a gateway"),
            Subcommand("LEVEL", args="SYM=<sym>[|PRICE=<p>]", purpose="Show orders making up a symbol or one price level"),
            Subcommand("SYMBOLS / GATEWAYS / VOLUME", purpose="List instruments / gateways / daily traded volume"),
            Subcommand("SESSION", args="STATE=<phase>", purpose="Advance session phase"),
            Subcommand("SESSION_STATUS / SCHEDULE", purpose="Show current session state / configured schedule"),
            Subcommand("HELP / EXIT / QUIT", purpose="Show command reference / disconnect and exit"),
        ),
        related=("pm-admin-cli", "pm-opctl-cli", "pm-engine"),
        doc_anchor="pm-admin-interactive-admin-console",
        doc_page="160-exchange-commands.md",
        examples=("pm-admin --id GW_ADMIN",),
        notes=("Most commands require the ADMIN gateway role; see the full risk-control flow in Risk Controls.",),
    ),
    CommandInfo(
        name="pm-admin-cli",
        category="Admin & Operations",
        title="CLI Admin Commands",
        summary="Non-interactive, one-shot alternative to pm-admin for scripting and CI.",
        synopsis=("pm-admin-cli --id <GW_ID> <command> [options]",),
        description=("Sends one command to the engine, waits for an acknowledgement, prints the result, and exits.",),
        options=(
            Option("--id GW_ID", "required", "ADMIN gateway ID"),
            Option("--push ADDR", "from config", "Engine PULL address"),
            Option("--sub ADDR", "from config", "Engine PUB address"),
            Option("--timeout MS", "3000", "Ack timeout in milliseconds"),
        ),
        subcommands=(
            Subcommand("halt / resume", purpose="Exchange-wide halt / resume"),
            Subcommand("halt-sym / resume-sym", args="--sym SYMBOL", purpose="Halt / resume one symbol"),
            Subcommand("cancel-sym", args="--sym SYMBOL", purpose="Cancel all resting orders on one symbol"),
            Subcommand("kill", args="--gw GW_ID [--sym SYMBOL]", purpose="Cancel all (or symbol-scoped) orders/quotes for gateway"),
            Subcommand("kick", args="--gw GW_ID [--reason TEXT]", purpose="Disconnect a gateway"),
            Subcommand("qcancel", args="--gw GW_ID --sym SYMBOL", purpose="Cancel active quote for gateway on symbol"),
            Subcommand("book", args="--sym SYMBOL", purpose="Fetch book snapshot"),
            Subcommand("orders", args="--gw GW_ID", purpose="List resting orders for gateway"),
            Subcommand("symbols / gateways / volume", purpose="List instruments / gateway states / daily volume"),
            Subcommand("session", args="--state STATE", purpose="Request session transition"),
            Subcommand("session-status / schedule", purpose="Read current session state / configured schedule"),
        ),
        related=("pm-admin", "pm-opctl-cli"),
        doc_anchor="pm-admin-cli-cli-admin-commands",
        doc_page="160-exchange-commands.md",
        examples=("pm-admin-cli --id GW_ADMIN halt-sym --sym AAPL",),
    ),
    CommandInfo(
        name="pm-opctl-cli",
        category="Admin & Operations",
        title="Operational Process Control",
        summary="Start, stop, and monitor a named group of pm-* processes together (recommended stack launcher).",
        synopsis=(
            "pm-opctl-cli start|up [PROFILE]",
            "pm-opctl-cli list [-y|--no-restart] | health [-q] | stop|down | kill",
            "pm-opctl-cli init | show [--json] | clear (--state|--all) [--yes]",
        ),
        description=(
            "The recommended way to bring up or tear down a full EduMatcher stack, "
            "instead of launching each process by hand. A profile is a named list "
            "of processes defined in <DATA_DIR>/emo-config.yaml; three profiles "
            "(micro, mini, default) are built in until that file exists.",
        ),
        subcommands=(
            Subcommand("start", args="[PROFILE]", aliases=("up",), purpose="Start a profile (default when omitted), skipping entries already running"),
            Subcommand("list", purpose="Status table for the active profile: uptime and memory per process; offers to restart dead entries"),
            Subcommand("health", args="[-q]", purpose="Same checks as list; exits 0 only when every process is running -- for monitoring scripts"),
            Subcommand("stop", aliases=("down",), purpose="Send SIGTERM to processes this tool started"),
            Subcommand("kill", purpose="Emergency stop: signals every process whose command line contains pm-, including ones this tool did not start"),
            Subcommand("init", purpose="Write the built-in profiles to emo-config.yaml for editing (refuses to overwrite)"),
            Subcommand("show", args="[--json]", purpose="Print version, data directory, and deployed config paths"),
            Subcommand("clear", args="(--state|--all) [--yes]", purpose="Delete persisted data; ref_data/ configuration is never touched"),
        ),
        related=("pm-engine", "pm-config-deploy", "pm-setup", "pm-admin"),
        doc_anchor="pm-opctl-cli-operational-process-control",
        doc_page="040-running-the-exchange.md",
        examples=(
            "pm-opctl-cli init                # write editable emo-config.yaml",
            "pm-opctl-cli start                # start the default profile",
            "pm-opctl-cli list                 # status table, offers to restart dead entries",
            "pm-opctl-cli health -q && echo OK # scripting-friendly health check",
            "pm-opctl-cli stop                 # graceful shutdown",
        ),
        notes=(
            "Health is reported at three confidence levels: dead, not responding, "
            "or running. A restarted-outside-this-tool process is re-adopted by "
            "matching its command line, so a stale PID file is never treated as final.",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Setup & Configuration
# ---------------------------------------------------------------------------

_SETUP_AND_CONFIG: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-setup",
        category="Setup & Configuration",
        title="Session Bootstrap Tool",
        summary="Bootstraps a runnable EduMatcher session directory with sensible defaults.",
        synopsis=("pm-setup [--data-dir PATH] [--force] [--no-config]",),
        description=(
            "Creates the data directory and deploys the bundled sample config to "
            "<DATA_DIR>/ref_data/engine_config.json. Use once per new environment "
            "before starting runtime processes.",
        ),
        options=(
            Option("--data-dir PATH", "$EDUMATCHER_DATA_DIR or ~/.local/share/edumatcher", "Data directory for persistent files"),
            Option("--force", "off", "Replace an already-deployed config"),
            Option("--no-config", "off", "Create the data dir only; deploy nothing"),
        ),
        related=("pm-config-gen", "pm-config-deploy", "pm-opctl-cli"),
        doc_anchor="pm-setup-session-bootstrap-tool",
        doc_page="000-getting-started.md",
        notes=("Local bootstrap logic; does not participate in the ZeroMQ runtime message bus.",),
    ),
    CommandInfo(
        name="pm-config-gen",
        category="Setup & Configuration",
        title="Engine Config Generator",
        summary="Generates engine_config.yaml from explicit CLI parameters instead of hand-editing YAML.",
        synopsis=(
            "pm-config-gen --symbols SYM [SYM ...] --gateways GW_SPEC [...] [options]",
            "              --output engine_config.yaml",
        ),
        options=(
            Option("--symbols SYM [SYM ...]", "required", "One or more symbols", group="Required"),
            Option("--gateways GW_SPEC [...]", "required", "One or more ID[:ROLE[:DISCONNECT]] gateway specs", group="Required"),
            Option("--sessions-enabled", "disabled", "Enable scheduler-driven sessions", group="Session & engine"),
            Option("--static-band / --dynamic-band PCT", "unset", "Default collar bands", group="Collars & circuit breakers"),
            Option("--risk-level NAME:STATIC[:DYNAMIC]", "-", "Risk level definition; repeatable", group="Collars & circuit breakers"),
            Option("--cb-levels NAME:SHIFT[:HALT_MINS[:MODE]]", "-", "Circuit-breaker level definition; repeatable", group="Collars & circuit breakers"),
            Option("--mm-spread-ticks / --mm-min-qty", "20 / 100", "Global market-maker obligation defaults", group="Market-maker obligations"),
            Option("--post-trade-gateway", "-", "Emit post_trade_gateway: section for pm-ralf-gwy", group="Gateway sections"),
            Option("--market-data-gateway", "-", "Emit market_data_gateway: section for pm-md-gwy", group="Gateway sections"),
            Option("--balf-gateway", "-", "Emit balf_gateway: section for pm-balf-gwy", group="Gateway sections"),
            Option("--api-gateway", "-", "Emit api_gateways: section for pm-api-gwy", group="Gateway sections"),
            Option("--index INDEX_ID", "-", "Add an index to the config; repeatable", group="Index sections"),
            Option("--schedule / --no-schedule", "auto", "Force include/suppress the schedule section", group="Schedule"),
            Option("--combo SPEC", "-", "Add a pre-configured combo definition; repeatable", group="Combos"),
            Option("--output FILE", "stdout", "Output YAML file path", group="Output"),
            Option("--dry-run", "off", "Print generated YAML; write nothing", group="Output"),
        ),
        related=("pm-cverifier", "pm-config-deploy", "pm-config-show"),
        doc_anchor="pm-config-gen-engine-config-generator",
        doc_page="010-configuration.md",
        examples=(
            "pm-config-gen --symbols AAPL MSFT --gateways TRADER01 TRADER02 OPS01:ADMIN "
            "--sessions-enabled --output engine_config.yaml",
        ),
        notes=(
            "Full option reference (80+ flags across gateway/symbol overrides, "
            "seeding, and per-gateway sub-flags) is in the Configuration chapter's "
            "Option Reference -- this page shows the groups, not every flag.",
        ),
    ),
    CommandInfo(
        name="pm-cverifier",
        category="Setup & Configuration",
        title="Config Verifier",
        summary="Validates engine_config.yaml across YAML, schema, semantic, and completeness checks.",
        synopsis=("pm-cverifier [--format text|json] [--level info|warn|error] [--strict] CONFIG_FILE",),
        options=(
            Option("CONFIG_FILE", "required", "Path to engine_config.yaml"),
            Option("--format text|json", "text", "Output format"),
            Option("--level info|warn|error", "info", "Minimum severity to show"),
            Option("--no-color", "off", "Disable ANSI colour in text output"),
            Option("--strict", "off", "Treat warnings as errors for CI exit-code purposes"),
        ),
        related=("pm-config-gen", "pm-config-deploy", "pm-config-show"),
        doc_anchor="pm-cverifier-config-verifier",
        notes=("Exit 0: no findings at/above threshold. Exit 1: one or more findings at/above threshold.",),
    ),
    CommandInfo(
        name="pm-config-deploy",
        category="Setup & Configuration",
        title="Compile and Install a Configuration",
        summary="Validates, compiles, and installs engine_config.yaml as the file every process reads.",
        synopsis=(
            "pm-config-deploy SOURCE",
            "pm-config-deploy --check SOURCE",
            "pm-config-deploy --show",
        ),
        description=(
            "Runs all four pm-cverifier layers before installing; a failing "
            "configuration is never installed and the previous artifact is left "
            "untouched (staged write + rename). Compiling also resolves every "
            "default exactly once.",
        ),
        options=(
            Option("SOURCE", "-", "Authored engine_config.yaml to validate, compile and install"),
            Option("--check", "off", "Validate and compile, but install nothing -- for CI"),
            Option("--show", "off", "Print the deployed paths and exit"),
        ),
        related=("pm-cverifier", "pm-config-gen", "pm-config-show", "pm-opctl-cli"),
        doc_anchor="pm-config-deploy-compile-and-install-a-configuration",
        doc_page="010-configuration.md",
        notes=("Local bootstrap logic; does not participate in the ZeroMQ runtime message bus.",),
    ),
    CommandInfo(
        name="pm-config-show",
        category="Setup & Configuration",
        title="Config Viewer",
        summary="Prints the effective configuration as a terminal dashboard, or renders it as a PDF.",
        synopsis=(
            "pm-config-show [-m 1|2] [--all] [-f FILE]",
            "pm-config-show --format pdf -o exchange.pdf",
        ),
        description=(
            "Where pm-cverifier answers \"is this file correct\", pm-config-show "
            "answers \"what does this file say\" -- including the resolved port map, "
            "which cannot be read off the YAML alone. Strictly read-only.",
        ),
        options=(
            Option("-f, --file YAML", "<DATA_DIR>/ref_data/engine_config.yaml", "Config file to read"),
            Option("-m, --density [1|2]", "0", "1 adds risk/gateway detail, 2 adds every knob"),
            Option("-a, --all", "off", "Show everything: implies -m 2, unmasks API keys"),
            Option("--format terminal|pdf", "terminal", "Output format"),
            Option("-o, --output FILE", "engine-config-<stem>.pdf", "Destination file for --format pdf"),
            Option("--no-color", "off", "Disable ANSI colour"),
            Option("--ascii", "off", "ASCII box drawing; auto-enabled on non-UTF-8 terminals"),
            Option("--width N", "terminal width", "Force render width -- for scripted capture"),
        ),
        related=("pm-cverifier", "pm-config-deploy", "pm-config-gen"),
        doc_anchor="pm-config-show-config-viewer",
        doc_page="010-configuration.md",
        notes=(
            "Exit 2: config file missing/unreadable. Exit 3: not valid YAML "
            "(points at pm-cverifier). Local inspection logic; not on the ZeroMQ bus.",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOGGING: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-log-srv",
        category="Logging",
        title="Centralized Log Server",
        summary="Collects LALF log lines from every pm-* process into a queryable log.db.",
        synopsis=(
            "pm-log-srv [--host ADDR] [--port 5600] [--db PATH] [--retention-days N]",
            "           [--pub-port 5601] [--pull-port 5602] [--no-pubsub]",
        ),
        description=(
            "A dedicated collector process, unrelated to the ZeroMQ order-flow bus: "
            "accepts LALF TCP connections and appends every record to SQLite. Also "
            "runs a LALF-PS ZeroMQ PUB/PULL pair that pushes live rows to log "
            "viewers without polling log.db.",
        ),
        options=(
            Option("--host ADDR", "0.0.0.0 (from config)", "TCP bind address"),
            Option("--port PORT", "5600", "TCP listen port for LALF clients"),
            Option("--db PATH", "data/log.db", "SQLite database path"),
            Option("--retention-days N", "30", "Prune log_events rows older than N days (0 = unbounded)"),
            Option("--max-message-bytes N", "65536", "Truncation ceiling per LOG payload"),
            Option("--pub-port PORT", "5601", "LALF-PS PUB bind port for log distribution"),
            Option("--pull-port PORT", "5602", "LALF-PS PULL bind port for subscriber control"),
            Option("--no-pubsub", "off", "Disable the LALF-PS interface entirely"),
            Option("--lease-sec N", "30", "Subscription lease TTL before an unrenewed subscriber is reaped"),
            Option("--log-level LEVEL", "WARNING", "Explicit level: CRITICAL, ERROR, WARNING, INFO, DEBUG"),
            Option("-v, --verbose", "off", "Increase verbosity"),
            Option("-q, --quiet", "off", "Reduce output to warnings/errors"),
            Option("--log-target stdout|file", "stdout", "Never server -- pm-log-srv must not depend on itself"),
        ),
        ports="Listens on TCP 5600 (LALF collection), binds ZMQ 5601 (PUB) and 5602 (PULL) unless --no-pubsub",
        related=("pm-log-cli",),
        doc_anchor="pm-log-srv-centralized-log-server",
        doc_page="280-log-srv.md",
        notes=("Fully implemented; auto-detection by every other pm-* process is a follow-up phase not yet rolled out.",),
    ),
    CommandInfo(
        name="pm-log-cli",
        category="Logging",
        title="Log Server Query/Troubleshooting CLI",
        summary="Read-only offline query and troubleshooting tool for log.db.",
        synopsis=("pm-log-cli [--db PATH] [--format human|json] COMMAND [options]",),
        description=(
            "Queries log.db directly from disk, never over the network, so a busy "
            "or even-stopped pm-log-srv never blocks troubleshooting.",
        ),
        options=(
            Option("--db PATH", "data/log.db", "SQLite database path"),
            Option("--format human|json", "human", "Output format"),
        ),
        subcommands=(
            Subcommand("tail", purpose="Follow recent log records"),
            Subcommand("query", purpose="Search log records by filter"),
            Subcommand("processes", purpose="Summarize which processes have logged"),
            Subcommand("stats", purpose="Summary statistics about the log database"),
            Subcommand("diagnose", purpose="Rule-based troubleshooting heuristics with concrete recommendations"),
            Subcommand("prune", purpose="Manual retention maintenance"),
        ),
        related=("pm-log-srv",),
        doc_anchor="pm-log-cli-log-server-querytroubleshooting-cli",
        doc_page="280-log-srv.md",
    ),
)


# ---------------------------------------------------------------------------
# Developer Tools
# ---------------------------------------------------------------------------

_DEVELOPER_TOOLS: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-msgen",
        category="Developer Tools",
        title="Message Binding Generator",
        summary="Generates Python/C message bindings and message-reference docs from spec/.",
        synopsis=(
            "pm-msgen generate [--spec DIR] [--out-python DIR] [--out-c DIR]",
            "pm-msgen check    [--spec DIR] [--out-python DIR] [--out-c DIR]",
            "pm-msgen lint     [--spec DIR]",
            "pm-msgen grep-literals [--spec DIR] [--src DIR]",
        ),
        description=(
            "Not part of the running exchange -- no pm-* runtime process invokes "
            "it. Keeps the spec in spec/ as the single source of truth for every "
            "topic name and payload shape. `check` is the CI gate: it re-renders "
            "from the spec and fails if committed output differs, run via "
            "`make msgen-check`.",
        ),
        subcommands=(
            Subcommand("generate", purpose="Render Python bindings, C artifacts, and docs; write to disk"),
            Subcommand("check", purpose="Fail (exit 1) if committed output differs from the spec"),
            Subcommand("lint", purpose="Validate the spec only; prints a family/message count"),
            Subcommand("grep-literals", purpose="Scan a source tree for topic literals a generated constant should replace"),
        ),
        options=(
            Option("--spec DIR", "spec", "Spec root holding transports.yaml and messages/"),
            Option("--out-python DIR", "src/edumatcher/models/generated", "Python output directory (generate/check)"),
            Option("--out-c DIR", "docs/examples/generated", "C output directory (generate/check)"),
            Option("--src DIR", "src", "Source tree to scan (grep-literals)"),
        ),
        related=(),
        doc_anchor="pm-msgen-message-binding-generator",
        examples=("make msgen        # regenerate after editing a spec file", "make msgen-check  # CI drift gate"),
        notes=(
            "Exit 2 on spec error or a missing --spec directory (usually the wrong "
            "working directory -- run from the repo root, or pass --spec).",
            "Local build tooling; does not participate in the ZeroMQ runtime message bus.",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

_HELP: tuple[CommandInfo, ...] = (
    CommandInfo(
        name="pm-help",
        category="Help",
        title="Command Index and Man-Page Reference",
        summary="Lists every pm-* command, or prints a full man page for one of them.",
        synopsis=(
            "pm-help [--format table|text] [-v]",
            "pm-help [--format table|text] [-v] <pm-command>",
        ),
        description=(
            "With no argument, prints the version, data directories, and a table "
            "of every pm-* command with a one-sentence description, grouped by "
            "category. With a command name, prints a full man page for that "
            "command: synopsis, description, options, subcommands, ports/message "
            "bus involvement, related commands, and examples.",
        ),
        options=(
            Option("--format table|text", "table", "table uses UTF-8 box-drawing characters; text is plain-aligned columns"),
            Option("-v, --verbose", "off", "Show extra detail (and an example, where one exists) for each command"),
        ),
        aliases=("pm-man",),
        related=(),
        doc_anchor="",
        examples=(
            "pm-help                    # version, data dirs, and the full command table",
            "pm-help --format text -v   # plain-text table with per-command examples",
            "pm-help pm-viewer          # full man page for pm-viewer",
            "pm-man pm-alf-console      # pm-man is an alias for pm-help",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public assembly
# ---------------------------------------------------------------------------

ALL_COMMANDS: tuple[CommandInfo, ...] = (
    _CORE_RUNTIME
    + _EXTERNAL_GATEWAYS
    + _PROTOCOL_SPIES
    + _AI_AND_BOTS
    + _INDEX
    + _QUERY_CLIS
    + _ADMIN_AND_OPS
    + _SETUP_AND_CONFIG
    + _LOGGING
    + _DEVELOPER_TOOLS
    + _HELP
)

_BY_NAME: dict[str, CommandInfo] = {cmd.name: cmd for cmd in ALL_COMMANDS}
for _cmd in ALL_COMMANDS:
    for _alias in _cmd.aliases:
        _BY_NAME.setdefault(_alias, _cmd)
del _cmd, _alias


def all_commands() -> tuple[CommandInfo, ...]:
    """Return every known command, in category-then-registration order."""
    return ALL_COMMANDS


def get_command(name: str) -> CommandInfo | None:
    """Look up a command by exact name or alias.

    Accepts the name with or without a leading ``pm-`` so ``viewer`` finds
    ``pm-viewer`` as a convenience for a mistyped invocation.
    """
    if name in _BY_NAME:
        return _BY_NAME[name]
    if not name.startswith("pm-") and f"pm-{name}" in _BY_NAME:
        return _BY_NAME[f"pm-{name}"]
    return None


def commands_by_category() -> tuple[tuple[str, tuple[CommandInfo, ...]], ...]:
    """Group commands by category, in ``CATEGORY_ORDER``."""
    grouped: dict[str, list[CommandInfo]] = {cat: [] for cat in CATEGORY_ORDER}
    for cmd in ALL_COMMANDS:
        grouped.setdefault(cmd.category, []).append(cmd)
    return tuple((cat, tuple(cmds)) for cat, cmds in grouped.items() if cmds)


def close_matches(name: str, limit: int = 3) -> tuple[str, ...]:
    """Suggest similar command names for an unknown-command error message."""
    import difflib

    candidates = list(_BY_NAME.keys())
    return tuple(difflib.get_close_matches(name, candidates, n=limit, cutoff=0.4))
