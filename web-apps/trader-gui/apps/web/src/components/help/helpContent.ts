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
  /** A glossary: each term in bold, then what it means. */
  terms?: { term: string; text: string }[];
  /** A literal example, shown in monospace (a ticket, a price sequence). */
  example?: string;
  /** A callout: the thing to remember, or the usual mistake. */
  note?: string;
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
        paragraphs: [
          "An order type says how your order behaves when it meets the book. The ticket offers eight single-order types; OCO and Combo link several orders together. Each has its own topic below.",
          "Two things separate them: whether the order trades now or waits, and whether the price is guaranteed or the fill is.",
        ],
      },
      {
        heading: "The types at a glance",
        terms: [
          { term: "Market", text: "Trades now at whatever the book offers. Fill is near-certain, price is not." },
          { term: "Limit", text: "Trades at your price or better; what does not trade rests in the book. Price is guaranteed, the fill is not." },
          { term: "Stop", text: "Sleeps until the market trades through a trigger price, then becomes a Market order." },
          { term: "Stop-Limit", text: "Sleeps until the trigger, then becomes a Limit order." },
          { term: "FOK (Fill or Kill)", text: "Trades the whole quantity now, or is rejected without trading at all." },
          { term: "IOC (Immediate or Cancel)", text: "Trades what it can now at your price or better; the rest is cancelled." },
          { term: "Iceberg", text: "A large Limit order that shows only a small visible slice." },
          { term: "Trailing Stop", text: "A Stop whose trigger follows the market at a fixed distance, only ever in your favour." },
          { term: "OCO", text: "Two orders where one filling or cancelling cancels the other." },
          { term: "Combo", text: "Two to ten orders in different symbols that stand or fall together." },
        ],
      },
      {
        heading: "Aggressive, passive and conditional",
        bullets: [
          "Aggressive orders (Market, IOC, FOK) take liquidity that is already resting. They never wait in the book.",
          "Passive orders (Limit, Iceberg) rest in the book and wait for someone to trade against them. They give liquidity.",
          "Conditional orders (Stop, Stop-Limit, Trailing Stop) are held by the exchange, invisible to other traders, until the last trade price reaches the trigger. Only then do they act.",
        ],
      },
      {
        heading: "Which one should I use?",
        bullets: [
          "I must be in or out now, and the price matters less: Market.",
          "I have a price in mind and can wait: Limit.",
          "I want to leave automatically if the price moves against me: Stop or Stop-Limit.",
          "I want that exit to follow a rising price up: Trailing Stop.",
          "All of it or nothing, right now: FOK. As much as is available right now: IOC.",
          "I have a large order and do not want to show it: Iceberg.",
          "I want a profit target and a stop-loss, and never both: OCO.",
        ],
      },
      {
        note: "Orders are validated twice: by this form before sending, and by the engine, which has the last word. An order the engine refuses shows as REJECTED with the reason; nothing has traded.",
      },
    ],
  },
  {
    id: "ot-market-limit",
    title: "Market & Limit",
    blocks: [
      {
        heading: "Market",
        paragraphs: [
          "Buys or sells immediately against the best resting orders on the other side, level after level, until your quantity is done or the book runs out. You give no price.",
          "You are guaranteed speed, not price. In a thin book a large Market order walks far through the levels and its average price ends up well away from the one you saw. The difference is called slippage.",
        ],
        terms: [
          { term: "Needs", text: "Symbol, side, quantity." },
          { term: "Allowed", text: "Continuous trading only. Not accepted in an auction or while trading is halted." },
          { term: "If the book runs dry", text: "The order is accepted, fills what it can, and the remainder is cancelled with reason INSUFFICIENT_LIQUIDITY. It is not rejected." },
        ],
        example: "BUY 500 at market. Asks: 100 @ 150.10, 200 @ 150.20, 400 @ 150.50\n→ fills 100 @ 150.10, 200 @ 150.20, 200 @ 150.50   (average 150.30)",
      },
      {
        heading: "Limit",
        paragraphs: [
          "Trades at your limit price or better: a BUY Limit at 150.00 fills at 150.00 or lower, a SELL Limit at 150.00 at 150.00 or higher. Whatever cannot trade at once rests in the book and waits.",
          "You are guaranteed the price, not the fill. If the market never comes to your price, the order simply sits there, or expires according to its time in force.",
        ],
        terms: [
          { term: "Needs", text: "Symbol, side, quantity, price." },
          { term: "Queue position", text: "Among orders at the same price, the one the engine accepted first trades first (price-time priority). Increasing the size or changing the price sends you to the back." },
          { term: "Marketable limit", text: "A BUY Limit at or above the best ask trades immediately, like a Market order but with a price cap." },
        ],
        example: "BUY 100 @ 150.00 limit. Best ask is 150.10 → nothing trades, the order rests as the best bid.\nBest ask drops to 150.00 → it trades at 150.00.",
      },
      {
        note: "Prices must be a multiple of the symbol's tick size, and inside the price collar around the reference price; otherwise the order is rejected.",
      },
    ],
  },
  {
    id: "ot-stops",
    title: "Stop, Stop-Limit & Trailing",
    blocks: [
      {
        paragraphs: [
          "A stop order sleeps, invisible to other traders, until the last trade price of the symbol reaches its trigger. Quotes and the mid price do not trigger it; only real trades do. When it triggers it becomes a normal order and is matched like any new order.",
        ],
        terms: [
          { term: "SELL stop", text: "Triggers when the last trade price falls to or below the stop price. The classic stop-loss: get out of a long position if the price drops." },
          { term: "BUY stop", text: "Triggers when the last trade price rises to or above the stop price. Used to enter on a breakout, or to close a short position." },
          { term: "Already met", text: "A stop whose condition is already true when you submit it triggers at once." },
        ],
      },
      {
        heading: "Stop",
        paragraphs: ["On trigger becomes a Market order. It is sure to execute, but at whatever price the book gives: in a fast market that may be well beyond the stop price."],
        terms: [{ term: "Needs", text: "Symbol, side, quantity, stop price." }],
        example: "SELL 100, stop 148.00. Last trade 149.50 → sleeping.\nTrade prints 147.80 → triggers, sells at market (fills 147.60 if that is the best bid).",
      },
      {
        heading: "Stop-Limit",
        paragraphs: [
          "On trigger becomes a Limit order at the limit price you gave. That caps how bad the fill can be, but if the market moves through your limit the order does not fill and rests unfilled.",
        ],
        terms: [{ term: "Needs", text: "Symbol, side, quantity, stop price and limit price." }],
        example: "SELL 100, stop 148.00, limit 147.50.\nTrade prints 147.80 → becomes a SELL Limit 147.50.\nBest bid is already 147.00 → no fill; it rests at 147.50 until a buyer arrives.",
      },
      {
        heading: "Trailing Stop",
        paragraphs: [
          "A stop that moves. You give a trail offset, a fixed distance. A SELL trailing stop keeps its trigger at offset below the highest price seen: when the price rises the trigger rises with it, when the price falls the trigger stays put. It never moves against you. On trigger it becomes a Market order.",
        ],
        terms: [
          { term: "Needs", text: "Symbol, side, quantity, trail offset. A stop price is optional: without one the trigger starts at last trade ± offset." },
          { term: "No last trade", text: "Without a stop price and without any trade yet in the symbol, the engine rejects it." },
        ],
        example: "SELL 100, trail 2.00, last trade 100.00 → trigger 98.00.\nPrice rises to 110.00 → trigger 108.00.\nPrice falls to 108.00 → triggers, sells at market.",
      },
      {
        note: "Stops wait for trades. While trading is paused (pre-open, auction, halt) a stop is accepted and stored, but cannot trigger until the next trade, usually the auction uncross.",
      },
    ],
  },
  {
    id: "ot-immediate",
    title: "FOK & IOC",
    blocks: [
      {
        paragraphs: [
          "Both are aggressive orders with a price limit that never rest in the book. They differ in what they do about a shortfall.",
        ],
      },
      {
        heading: "FOK — Fill or Kill",
        paragraphs: [
          "The whole quantity must be tradeable right now at your price or better, or the order is rejected without a single fill. The engine checks the available quantity first, including the hidden part of icebergs, but not your own gateway's resting orders, which self-match prevention would skip. So a FOK can be rejected even when the displayed book looks big enough.",
        ],
        terms: [{ term: "Needs", text: "Symbol, side, quantity, price." }, { term: "Rejection", text: "INSUFFICIENT_LIQUIDITY. Nothing traded." }],
        example: "BUY 300 FOK @ 150.20. Asks: 100 @ 150.10, 150 @ 150.20 (250 available)\n→ rejected; with 300 available it would fill in full.",
      },
      {
        heading: "IOC — Immediate or Cancel",
        paragraphs: [
          "Trades whatever is available at your price or better, right now, and cancels the rest. A partial fill is fine; resting is not allowed.",
        ],
        terms: [
          { term: "Needs", text: "Symbol, side, quantity, price." },
          { term: "Remainder", text: "Cancelled. The order is accepted, you see the fills and then a cancel for the unfilled quantity." },
          { term: "FOK vs IOC", text: "FOK is all or nothing and rejects; IOC takes what it can and cancels the rest." },
        ],
        example: "BUY 300 IOC @ 150.20. Asks: 100 @ 150.10, 150 @ 150.20\n→ fills 100 @ 150.10 and 150 @ 150.20, cancels the remaining 50.",
      },
      {
        note: "Neither FOK nor IOC is accepted in an auction, because an auction collects orders instead of matching them one by one. FOK and IOC are order types, not time in force values.",
      },
    ],
  },
  {
    id: "ot-iceberg",
    title: "Iceberg",
    blocks: [
      {
        paragraphs: [
          "A large Limit order that shows only a slice. Other traders see the visible quantity; the rest is hidden reserve. Each time the visible slice is used up, a new slice appears from the reserve. This hides your size so it does not move the market against you.",
        ],
        terms: [
          { term: "Needs", text: "Symbol, side, total quantity, price, visible quantity. Visible must be smaller than the total." },
          { term: "Queue position", text: "Every new slice joins the back of the queue at that price, so an iceberg fills more slowly than a plain Limit of the same size." },
          { term: "Incoming iceberg", text: "If it crosses the book it trades its full quantity at once, like a Limit. Only what is left to rest is hidden." },
        ],
        example: "BUY 1000 @ 150.00, visible 100.\nThe book shows 100 @ 150.00. A seller takes those 100 → a fresh 100 appears (900 remain hidden).",
      },
      {
        note: "Watch the depth ladder: the quantity at your price resets to the visible size after every fill, while the blotter's Remaining column counts down the whole order.",
      },
    ],
  },
  {
    id: "ot-multileg",
    title: "OCO & Combo",
    blocks: [
      {
        heading: "OCO — One Cancels Other",
        paragraphs: [
          "Two orders in one symbol that share one quantity. When either one is filled, cancelled or rejected, the engine cancels the other. You cannot get both.",
          "The classic use is a bracket around a position: a take-profit Limit above and a stop-loss Stop below. Whichever the market reaches first closes you out and removes the other.",
        ],
        terms: [
          { term: "Each leg", text: "Side, type (Limit or Stop) and its price or stop price. A Limit leg needs a price; a Stop leg needs a stop price." },
          { term: "OCO id", text: "Your label for the pair. It appears in the blotter's Group column on both legs." },
        ],
        example: "You hold 100 @ 150. SELL leg 1: Limit 160 (take profit). SELL leg 2: Stop 145 (stop loss).\nPrice reaches 160 → leg 1 fills, leg 2 is cancelled.",
      },
      {
        heading: "Combo — multi-leg, all or none",
        paragraphs: [
          "Two to ten Limit or Market legs, possibly in different symbols, tracked as one unit: a pair trade, a spread or a hedged entry. Without a Combo, one leg can fill while the other does not and leave you with exposure you never wanted (leg risk).",
        ],
        terms: [
          { term: "All or none", text: "The Combo counts as MATCHED only when every leg is completely filled." },
          { term: "Cascade", text: "If one leg is cancelled or expires, every other unfilled leg is cancelled with it. Fills that already happened are not reversed." },
          { term: "Status", text: "PENDING → PARTIALLY_MATCHED → MATCHED. FAILED if a leg is cancelled or expires; CANCELLED if you cancel it; REJECTED if validation fails." },
        ],
        example: "Leg 1: BUY 100 MSFT @ 415.00. Leg 2: SELL 100 AAPL @ 210.00.",
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
        paragraphs: [
          "Time in force says how long an order stays alive. The order type says how to trade; TIF says for how long. It matters for orders that rest: Limit, Stop, Iceberg and the legs of OCO and Combo.",
        ],
        terms: [
          { term: "DAY", text: "Valid for the current trading day. It is kept across an engine restart on the same day and expires when the day ends. The default." },
          { term: "GTC — Good Till Cancelled", text: "Stays until it trades or you cancel it, across days and restarts." },
          { term: "ATO — At The Open", text: "Only for the opening auction. It takes part in the opening uncross and any remainder expires when the auction ends." },
          { term: "ATC — At The Close", text: "Only for the closing auction. It takes part in the closing uncross and any remainder expires when the auction ends." },
        ],
      },
      {
        note: "FOK and IOC are order types, not TIF values. The ticket offers only the TIF values valid in the current session phase; the others are shown as unavailable.",
      },
    ],
  },
  {
    id: "order-status",
    title: "Order Status",
    blocks: [
      {
        paragraphs: ["The Status column of the blotter follows an order from submission to its end. FILLED, CANCELLED, REJECTED and EXPIRED are final."],
        terms: [
          { term: "PENDING", text: "Sent by this screen, no answer from the engine yet. Normally lasts a fraction of a second." },
          { term: "NEW", text: "Accepted by the engine. It is resting in the book, or waiting as a stop, and nothing has traded yet." },
          { term: "PARTIAL", text: "Part of the quantity has traded. The Remaining column shows what is still open." },
          { term: "FILLED", text: "The whole quantity has traded." },
          { term: "CANCELLED", text: "Removed before it was completely filled: by you, by a linked order (OCO, Combo), by a kill switch, or by the engine because nothing was left to trade against (an IOC or Market remainder)." },
          { term: "REJECTED", text: "Refused by the engine and never entered the book. Typical reasons: price outside the collar, wrong tick size, not allowed in this session phase, trading halted, insufficient liquidity for a FOK." },
          { term: "EXPIRED", text: "Its time in force ran out: a DAY order at the end of the day, an ATO or ATC order at the end of its auction." },
        ],
      },
      {
        note: "202 Accepted from the server only means the order reached the engine. The engine's order acknowledgement is the real verdict, and it is what moves the status from PENDING to NEW or REJECTED.",
      },
    ],
  },
  {
    id: "tables",
    title: "Reading the Tables",
    blocks: [
      {
        paragraphs: ["Hover or focus the small i next to a column heading to see what it means. This is the short reference."],
      },
      {
        heading: "Orders blotter",
        terms: [
          { term: "Side", text: "BUY or SELL." },
          { term: "Type / TIF", text: "The order type and its time in force." },
          { term: "Qty", text: "The quantity you ordered in total." },
          { term: "Remaining", text: "The quantity not yet traded. It counts down to 0 as the order fills." },
          { term: "Price", text: "The limit price; a dash for orders without one, such as Market and Stop." },
          { term: "Group", text: "The OCO or Combo id linking this order to others." },
          { term: "Status", text: "See Order Status." },
          { term: "Updated", text: "When the order last changed." },
          { term: "Order ID", text: "The engine's id. Click it to see the whole lifecycle of the order." },
        ],
      },
      {
        heading: "Positions",
        terms: [
          { term: "Position", text: "What you hold: positive is long, negative is short." },
          { term: "VWAP", text: "Volume-weighted average price you paid or received for the open position." },
          { term: "Last Traded", text: "The latest trade price in the symbol." },
          { term: "Market Value", text: "Position × last traded price: what you hold is worth now." },
          { term: "Unrealized P&L", text: "Gain or loss on the open position if you closed it at the last traded price. It moves with the market until you close." },
          { term: "Session / MTD / YTD P&L", text: "Realized gain or loss from closing trades: today, since the first of the month, since the first of January." },
        ],
      },
      {
        heading: "Market overview",
        terms: [
          { term: "Bid / Ask", text: "The best price a buyer is willing to pay / a seller is willing to accept. The gap between them is the spread." },
          { term: "Last", text: "The price of the latest trade." },
          { term: "Chg %", text: "Change of the last price against the previous close." },
          { term: "Volume", text: "Quantity traded today." },
          { term: "Status", text: "Whether the symbol is trading, in an auction, or halted." },
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
