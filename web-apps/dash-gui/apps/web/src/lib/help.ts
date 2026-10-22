/**
 * Explanations for what the dashboard shows (WP-UI02): table columns, tiles,
 * gauges and chart titles. Looked up by the name already on screen, so a
 * widget needs no extra prop to be explained; `undefined` shows no tip.
 */

/** Column help by table label, then column id. */
const COLUMN: Record<string, Record<string, string>> = {
  Processes: {
    state:
      "The monitor's verdict on the process. HEALTHY: beacons arrive and the main loop runs. DEGRADED: running but a loop is late (see Loop age and Lag). HUNG: beacons arrive but the main loop has stood still for over 5 s. SILENT: no beacons, yet the process still exists (the whole interpreter is stuck). DEAD: no beacons and the process is gone. MISSING: the active profile expects it but it never reported. STOPPED: it shut down cleanly. Click a column header to sort, worst first by default.",
    key: "The process name, with its instance in brackets when several of one kind run. RESTARTED marks a process that has started again recently. Click a row for the full history of that process.",
    uptime: "How long the process has been running since its start. A short uptime on a process you left running means it restarted.",
    rss: "Resident memory: the physical RAM the process holds right now. The small chart is the recent trend; a line that only climbs suggests a leak.",
    cpu: "Share of one CPU core the process used recently (100% is one full core, so a multi-threaded process can exceed it). The small chart is the recent trend.",
    loop: "Time since the process's main loop last completed an iteration. Small values mean the loop is turning; a value that keeps growing means the loop is stuck, and above 5 s the state becomes HUNG. Coloured when it crosses the warning or critical line.",
    lag: "The longest gap between two ticks of the main loop, in milliseconds. It includes each loop's designed idle wait (up to about 250 ms), so a few hundred is normal; above 1 000 ms the process is DEGRADED.",
  },
  Participants: {
    id: "The participant (trader, market maker or bot) id the gateway knows the connection by.",
    role: "What the participant does: TRADER, MARKET_MAKER or ADMIN.",
    conn: "Whether the participant is connected to a gateway right now.",
    since: "When the current connection was made, in the exchange's time zone.",
    orders: "Orders the participant has sent since the start of today's trading day.",
    now: "The order rate over the last few seconds, scaled to orders per minute.",
    "avg-min": "Average orders per minute over the last 60 minutes.",
    "avg-h": "Average orders per hour today, counted over the hours the market was open.",
    "avg-d": "Average orders per day over the last 7 days. Blank until a full day of data exists.",
    rej: "Share of the participant's requests the exchange rejected, in percent. A high value points at a client with a bug or bad limits, for example orders outside the price collar.",
    rest: "Orders from this participant resting in the books right now, waiting for a counterparty.",
    cdh: "Today's connects / disconnects / heartbeat timeouts. Many connects or any heartbeat timeouts mean an unstable client or network.",
  },
  "Order books": {
    symbol: "The instrument the book belongs to. Click a row for its detail.",
    resting: "Limit orders waiting in the book, on both sides.",
    stops: "Stop orders held back until their trigger price trades. They are not visible in the book.",
    bid: "Distinct buy price levels in the book. Orders at the same price share a level.",
    ask: "Distinct sell price levels in the book.",
    mem: "Estimated memory the book's data structures take in the matching engine.",
    garbage:
      "Share of the book's internal price-priority heap entries that belong to orders already gone (cancelled or filled) and are waiting to be cleaned up. It shows whether compaction keeps up; a high value on a busy book is a sign of trouble.",
    trades: "Trades executed in this symbol today.",
    state: "TRADING: matching normally. HALTED: trading in this symbol is stopped (for example by a circuit breaker) until it is reopened.",
  },
  "Application metrics": {
    name: "The metric's name, as the process reports it.",
    label: "What the value is about, for example a symbol or a gateway. Empty when the metric has none.",
    kind: "gauge: a level that goes up and down (memory, queue depth). counter: a total that only grows from zero at process start.",
    value: "The metric's latest value.",
  },
};

/** Tile, gauge and chart help by label. */
const WIDGET: Record<string, string> = {
  Processes: "Exchange processes that are up out of those expected. The line below names any that are not HEALTHY. Participant bots are not counted here.",
  Participants: "Participants connected to a gateway right now, out of all the exchange has seen. The small chart is the recent trend.",
  "Orders today": "Orders received since the start of today's trading day, with the average rate over the last hour.",
  "Trades today": "Trades executed since the start of today's trading day, with the average rate over the last hour.",
  "Orders / s": "The current order rate across all participants, per second.",
  "Engine p99": "How long the matching engine takes to handle one message: 99 of 100 messages are faster than this. p50 below is the typical message. A rising p99 with a flat p50 means occasional slow outliers, such as garbage collection.",
  CPU: "CPU load of the whole host, all processes together, not only the exchange.",
  Memory: "Share of the host's RAM in use, all processes together.",
  "Disk free": "Free space on the data directory's disk. The engine's database and the logs live there; the colour turns when little is left.",
  "Exchange memory by process": "Resident memory of each exchange process over the selected range, stacked so the top line is the total.",
  "Memory per process": "Resident memory of each running exchange process right now, largest first.",
  "CPU per process": "CPU use of each exchange process over the selected range.",
  "Orders per minute by participant": "Orders sent per minute, one colour per participant, over the selected range.",
  "Trades per minute": "Trades executed per minute over the selected range.",
  "Traded value per minute": "The money value of the trades executed per minute (price × quantity, summed) over the selected range.",
  "Orders avg / min": "Average orders per minute over the last 60 minutes.",
  "Orders avg / hour": "Average orders per hour today, counted over the hours the market was open.",
  "Orders avg / day": "Average orders per day over the last 7 days. Blank until a full day of data exists.",
  "Traded value today": "Total money value of today's trades (price × quantity, summed over every trade).",
  "Rejects today by reason": "Why the exchange refused requests today, by reject code: the actionable half of the reject ratio.",
  "Reject ratio, 5-minute window": "Share of requests the exchange rejected over each 5-minute window. A rise usually means a client is sending bad orders, or a rule such as the price collar is too tight.",
  "Reject ratio per hour": "Share of requests the exchange rejected, per hour. A rise usually means a client is sending bad orders, or a rule such as the price collar is too tight.",
  Books: "Order books the engine holds, one per tradable symbol.",
  "Book memory (est.)": "Estimated memory of all order books together, and its share of the engine's resident memory.",
  "API WS sessions": "WebSocket sessions open on the API gateway, summed over its instances.",
  "API dropped events": "Events the API gateway discarded because a client could not keep up. Any value above zero in the last 5 minutes raises a warning.",
  "Slow disconnects": "Clients disconnected today because they were too slow to receive their data. Any in the last 5 minutes raises a warning.",
  "Log ingest": "Log messages per second flowing into pm-log-srv from all processes.",
  "Feed gaps": "Times the statistics feed skipped data since it started. Any in the last 5 minutes raises a warning.",
  "Data files": "Size of the exchange's data files (databases, journals) in the data directory.",
  "Engine diagnostics": "Counters the matching engine keeps about its own work, for debugging and teaching.",
};

const GATEWAY_CLIENTS = /^(\w+) clients$/;
const GATEWAY: Record<string, string> = {
  ALF: "Clients connected to the ALF gateway, which takes orders from traders",
  BALF: "Clients connected to the BALF gateway, the bulk or batch order gateway",
  MD: "Clients connected to the market-data gateway, which streams quotes, trades and the session state",
  RALF: "Clients connected to the RALF gateway, which serves reference data and replays",
  DC: "Clients connected to the drop-copy gateway, which mirrors every execution",
};

export function columnHelp(table: string, id: string): string | undefined {
  return COLUMN[table]?.[id];
}

export function widgetHelp(label: string): string | undefined {
  const m = GATEWAY_CLIENTS.exec(label);
  if (m && GATEWAY[m[1]!]) return `${GATEWAY[m[1]!]}, out of the most it accepts when a limit is set.`;
  return WIDGET[label];
}
