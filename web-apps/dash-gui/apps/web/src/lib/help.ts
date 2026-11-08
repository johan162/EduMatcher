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
    lane: "When the participant was connected over the picked range (green), with its heartbeat timeouts as red ticks. Hover for the times. Sort it to bring the participants that were disconnected longest to the top.",
  },
  "Order books": {
    symbol: "The instrument the book belongs to. Click a row for its detail.",
    long: "Long orders: resting orders with time in force GTC (good till cancelled). They stay in the book across the close and are restored when the exchange restarts. A subset of Resting.",
    resting: "Limit orders waiting in the book, on both sides.",
    stops: "Stop orders held back until their trigger price trades. They are not visible in the book.",
    bid: "Distinct buy price levels in the book. Orders at the same price share a level.",
    ask: "Distinct sell price levels in the book.",
    mem: "Estimated memory the book's data structures take in the matching engine.",
    bloat:
      "Size of the book's internal price-priority heaps compared with the size the engine tolerates before it cleans out entries of orders already gone (cancelled or filled). 1.00× or less is normal; above it, cleaning is not keeping up.",
    trades: "Trades executed in this symbol today.",
    state: "TRADING: matching normally. HALTED: trading in this symbol is stopped (for example by a circuit breaker) until it is reopened.",
  },
  "API keys": {
    key: "The API key, named by the description it has in the configuration, never by the key itself. (unauth) is requests that did not present a valid key.",
    total: "Requests the key has made since the API gateway started.",
    today: "Requests the key has made since the start of today's trading day.",
    now: "Requests per second over the last 60 seconds. Sorted by this, the key loading the gateway right now comes first.",
    hour: "Requests per second averaged over the last 60 minutes, or over the time the monitor has known the gateway if that is shorter.",
    share: "The key's share of all requests the gateway has answered since it started.",
    peak: "The most requests the key made in any single second since the gateway started. The ▲ marks the key behind the gateway's overall peak.",
    throttled: "Writes the rate limiter refused (HTTP 429) since the gateway started. Only order entry and admin commands are limited; reads are not.",
    throttled5: "Writes refused in the last 5 minutes. Any value above zero raises a warning.",
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
  "Engine p99": "How long the matching engine takes to handle one order message (new, cancel, amend, quote): 99 of 100 are faster than this, over the last minute. p50 below is the typical one. Queries and heartbeats are not counted here; the Engine latency row shows them, and how much is garbage collection.",
  "Order p50": "The typical time the engine takes to handle one order message (new, cancel, amend, quote, combo, OCO), over the last minute. 1 message in 16 is timed.",
  "Order p99": "99 of 100 order messages are handled faster than this, over the last minute. Below it, how many timed messages that rests on: under 100 the p99 is simply the slowest of them, and the row header says so.",
  "p99 without GC": "The same p99 with the time garbage collection took inside each message taken out. Far below Order p99 means the slow messages were slow because Python was collecting garbage.",
  "Other messages p99": "The p99 of everything else the engine handles: heartbeats, connects, queries such as book snapshots and order lists, and admin commands. Kept apart because a book snapshot of a deep book can take milliseconds and says nothing about matching.",
  "Longest GC pause": "The longest single garbage collection in the engine in the last minute. Every collection is timed, so a stall is never missed, even when no timed message hit it. Everything the engine does waits while it runs.",
  "Order latency": "Order p50, p99 and p99 without GC over the picked range, one point per stored sample. A p99 line that jumps while the without-GC line stays flat is garbage collection.",
  "Time in GC": "Share of the engine's time spent collecting garbage since its previous health report (every 2 s).",
  CPU: "CPU load of the whole host, all processes together, not only the exchange.",
  Memory: "Share of the host's RAM in use, all processes together.",
  "Disk free": "Free space on the data directory's disk. The engine's database and the logs live there; the colour turns when little is left.",
  "Exchange memory by process": "Resident memory of each exchange process over the selected range, stacked so the top line is the total.",
  "Memory per process": "Resident memory of each running exchange process right now, largest first.",
  "CPU per process": "CPU use of each exchange process over the selected range.",
  "Participants connected": "How many participants were connected over the picked range, from their connects and disconnects. Red lines are heartbeat timeouts. A sudden drop of many at once points at a gateway or the network rather than one client; the table below shows each participant's own lane.",
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
  "API requests / s": "HTTP requests per second the API gateway answered over the last 60 seconds, from every key, the dashboards' own polling included.",
  "API requests / s, last hour": "HTTP requests per second averaged over the last 60 minutes, or over the time the monitor has known the gateway if that is shorter.",
  "API peak / s": "The most requests the gateway answered in any single second since it started, and below it the key that made the most in its own busiest second.",
  "API requests": "HTTP requests answered since the gateway started, with today's count.",
  "API throttled": "Writes the rate limiter refused (HTTP 429) since the gateway started, over all keys. Any in the last 5 minutes raises a warning; the table shows which key.",
  "API requests / s by key": "Requests per second the API gateways answered, averaged over each bucket of the picked range, one colour per API key (the largest eight, the rest as other). Stacked, so a bar's height is the whole gateway's load and its colours say who put it there.",
  "API throttled by key": "Writes the rate limiter refused (HTTP 429) in each bucket of the picked range, by API key. Empty means nobody was throttled.",
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

/** The Session schedule row's timetable, by heading (pm-terminal's text). */
const TIMETABLE: Record<string, string> = {
  "This week":
    "Each day's hours this week, from pre-open to the end of the closing auction, in the exchange's time zone. Dashed: the exchange is closed that day. A bank holiday is named under its hours.",
  Timetable:
    "The trading day's phases in order, with the time each transition is scheduled for. NOW marks the phase the feed reports. The bar below is the day to scale, 00 to 24, with the exchange's current time on it. When today does not trade, the next trading day is shown.",
  "Next bank holiday":
    "The next bank holiday that falls on a day the exchange would otherwise trade, and whether it closes or runs on holiday hours. Holidays on days that are closed anyway are left out.",
};

export const timetableHelp = (heading: string): string | undefined => TIMETABLE[heading];

export function columnHelp(table: string, id: string): string | undefined {
  return COLUMN[table]?.[id];
}

export function widgetHelp(label: string): string | undefined {
  const m = GATEWAY_CLIENTS.exec(label);
  if (m && GATEWAY[m[1]!]) return `${GATEWAY[m[1]!]}, out of the most it accepts when a limit is set.`;
  return WIDGET[label];
}
