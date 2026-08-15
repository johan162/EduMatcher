/**
 * Static help content (§19.1.1), authored inline rather than loaded from
 * `/help/*.md` — this keeps the bundle free of a Markdown renderer and the
 * content type-checked. Each topic is a list of blocks (an optional heading
 * plus paragraphs/bullets). The "shortcuts" topic is rendered specially from
 * {@link SHORTCUTS} so the table has a single source of truth.
 */
export interface HelpBlock {
  heading?: string;
  /** Plain paragraphs. */
  paragraphs?: string[];
  /** Bulleted items. */
  bullets?: string[];
}

export interface HelpTopic {
  id: string;
  title: string;
  blocks: HelpBlock[];
}

/** Sentinel id: the Keyboard Shortcuts topic renders the shared shortcut table. */
export const SHORTCUTS_TOPIC_ID = "shortcuts";

export const HELP_TOPICS: HelpTopic[] = [
  {
    id: "getting-started",
    title: "Getting Started",
    blocks: [
      {
        heading: "What is EduMatcher?",
        paragraphs: [
          "EduMatcher is a teaching exchange. This UI is a graphical trading terminal that connects to the pm-api-gwy gateway over REST and WebSocket.",
        ],
      },
      {
        heading: "Connecting",
        paragraphs: [
          "Log in with an API key. The key resolves to a gateway and a role, which decides the screens you see.",
        ],
      },
      {
        heading: "Roles",
        bullets: [
          "TRADER — order entry, blotter, positions, trade history.",
          "MARKET_MAKER — two-sided quote management, positions.",
          "ADMIN — system dashboard, session/gateway control, risk & monitor views.",
        ],
      },
    ],
  },
  {
    id: "workspace",
    title: "Trading Workspace",
    blocks: [
      {
        paragraphs: [
          "The Workspace binds a chart, depth ladder, order ticket, and compact blotter to one active symbol. Selecting a symbol anywhere re-binds every panel at once.",
        ],
      },
      {
        heading: "Click-to-trade",
        paragraphs: [
          "Clicking a price level in the depth ladder prefills the ticket price and suggests a side (the bid column suggests SELL, the ask column BUY).",
        ],
      },
      {
        heading: "BUY / SELL",
        paragraphs: [
          "Submit with the BUY/SELL buttons, or press B / S while the ticket has focus. Both run the same validation.",
        ],
      },
    ],
  },
  {
    id: "order-types",
    title: "Order Types",
    blocks: [
      {
        bullets: [
          "Market — execute immediately at the best available price (continuous trading only).",
          "Limit — rest at a price no worse than your limit.",
          "Stop / Stop-Limit — trigger at a stop price, then trade at market / at a limit.",
          "FOK (Fill or Kill) — fill in full immediately or cancel entirely.",
          "Iceberg — show only a slice (visible qty) of a larger order.",
          "IOC (Immediate or Cancel) — fill what it can now, cancel the rest.",
          "Trailing Stop — a stop that follows the price by a trail offset.",
          "OCO — two orders where one leg filling cancels the other.",
          "Combo — a multi-leg all-or-none order.",
        ],
      },
    ],
  },
  {
    id: "amend-replace",
    title: "Amend vs Cancel-Replace",
    blocks: [
      {
        paragraphs: [
          "Amend a resting order for a same-price size reduction — it keeps queue priority.",
          "Cancel-Replace to change price (or increase size): the old order is cancelled and a new one submitted, losing priority. If the original is already gone, the replacement is not sent.",
        ],
      },
    ],
  },
  {
    id: "tif",
    title: "Time in Force (TIF)",
    blocks: [
      {
        bullets: [
          "DAY — rests until end of the trading day.",
          "GTC — good till cancelled.",
          "ATO — at the open; valid only during the opening auction.",
          "ATC — at the close; valid only during the closing auction.",
        ],
      },
      {
        paragraphs: [
          "The ticket only offers TIF values valid in the current session phase; others show as unavailable.",
        ],
      },
    ],
  },
  {
    id: "auctions",
    title: "Auctions & Indicative Price",
    blocks: [
      {
        paragraphs: [
          "During an opening or closing auction, orders rest and match together at a single uncross price rather than continuously.",
          "The indicative price is what would print if the call phase ended now; the final result prints at the uncross. Market / FOK / IOC are not accepted during an auction.",
        ],
      },
    ],
  },
  {
    id: "risk",
    title: "Risk Controls",
    blocks: [
      {
        heading: "Price Collars",
        paragraphs: [
          "A static band bounds prices against a reference price; a dynamic band bounds them against the last trade. Orders outside the band are rejected.",
        ],
      },
      {
        heading: "Circuit Breakers",
        paragraphs: [
          "A per-symbol ladder halts trading when the price shifts past a level's threshold. A halt reopens via a call auction.",
        ],
      },
      {
        heading: "Kill Switch",
        paragraphs: [
          "An ADMIN action that cancels resting orders/quotes by symbol, by gateway, or market-wide. It cancels exposure; it does not halt trading.",
        ],
      },
    ],
  },
  {
    id: "mm",
    title: "Market-Maker Quoting",
    blocks: [
      {
        paragraphs: [
          "Submit a two-sided quote (bid and ask) per symbol; the spread indicator shows the distance in ticks and currency as you type.",
          "When a leg fills, a fill alert offers a Re-quote action that prefills the form with the previous quote's values. The cards show per-leg fill progress from the bootstrap snapshot.",
        ],
      },
    ],
  },
  {
    id: "admin",
    title: "Admin Reference",
    blocks: [
      {
        bullets: [
          "Session control — transition the venue between phases (only valid transitions are offered).",
          "Gateway management — see connected gateways and kick (disconnect) one.",
          "Risk / Circuit Breakers — read-only config plus manual halt/clear.",
          "Symbol configuration is loaded from engine_config.yaml at startup; live add/edit requires a backend extension (§6.7) and is disabled.",
        ],
      },
    ],
  },
  {
    id: SHORTCUTS_TOPIC_ID,
    title: "Keyboard Shortcuts",
    blocks: [],
  },
];
