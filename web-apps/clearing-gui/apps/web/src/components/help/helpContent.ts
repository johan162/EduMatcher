/**
 * Static help content for the help drawer -- the same block structure as
 * trader-gui's, with topics drawn from what this application shows.
 */
export interface HelpBlock {
  heading?: string;
  paragraphs?: string[];
  bullets?: string[];
}

export interface HelpTopic {
  id: string;
  title: string;
  blocks: HelpBlock[];
}

export const HELP_TOPICS: HelpTopic[] = [
  {
    id: "getting-started",
    title: "Getting Started",
    blocks: [
      {
        heading: "What is this?",
        paragraphs: [
          "A read-only view of the clearing and end-of-day settlement data that pm-clearing and pm-eod record. It talks only to pm-api-gwy, which enforces who may see what.",
        ],
      },
      {
        heading: "Roles",
        bullets: [
          "ADMIN — the venue: overview, participants (each opens in a drawer over the list), symbols, events, gateway sessions, reconciliation, EOD settlement.",
          "TRADER — its own gateway: positions at their marks, retained trades, daily and close history, EOD settlement and balance, gateway sessions.",
          "MARKET_MAKER — the trader views plus My Quote Obligations.",
        ],
      },
      {
        paragraphs: [
          "There is no margin, equity, collateral or buying power anywhere: nothing in the system computes them. The long and short totals per symbol (Symbol Activity, Explain mode) are sums of stored positions.",
        ],
      },
    ],
  },
  {
    id: "tables",
    title: "Tables and filters",
    blocks: [
      {
        bullets: [
          "Hover a column header or tile label with a dotted underline for what it shows.",
          "Click a header marked ↕ to sort; click again for the other direction. Trade lists are newest first and do not sort: the server sends them a page at a time.",
          "Tables of more than 10 rows have a pager: 10, 30, 50, 100 or all rows per page, remembered for every table. \"of 200+\" means the server holds more; paging forward fetches them.",
          "Gateway, Symbol and Account filters list the known values as you type (arrow keys and Enter, or click). An unlisted value still filters; empty means all.",
        ],
      },
    ],
  },
  {
    id: "times",
    title: "Times",
    blocks: [
      {
        paragraphs: [
          "Every time is on the venue's clock — its session timezone, the zone trading days are in — with the date and the zone, e.g. 2026-11-26 09:00:01 CET.",
          "If the engine does not answer the timezone request, times are shown in UTC and labelled UTC.",
        ],
      },
    ],
  },
  {
    id: "explain",
    title: "Explain mode",
    blocks: [
      {
        paragraphs: [
          "The Explain button in the top bar (on by default, remembered) shows how each figure is made: an explanation under every tile, a card per position, and the teaching pictures. Off, the screens are the compact operator view and the pictures' data is not requested.",
          "Always on, whatever the setting: long / short / flat beside a position, gain / loss beside a P&L, and empty tables that say what would fill them.",
        ],
      },
      {
        heading: "Where it adds what",
        bullets: [
          "Positions — the arrow at the start of a row opens how its P&L is made: the sum written out, the average cost and the mark on a price line, realized + unrealized = total, and how the position was built on its latest trading day.",
          "History — money in and out by day; the arrow on a daily row replays that day's fills.",
          "Trades — the arrow on a trade follows it: matched, received by clearing, each side's position change, the day's row, pm-eod's settlement.",
          "Settlement — netting: what was bought and sold, and the one amount left to pay or receive.",
          "ADMIN: Overview — the venue's netting and who traded with whom; Participants — gains and losses add up to zero; Symbol Activity — longs against shorts.",
        ],
      },
    ],
  },
  {
    id: "pictures",
    title: "Reading the pictures",
    blocks: [
      {
        bullets: [
          "Every picture has its numbers in a table beside or under it; the table is what a screen reader reads.",
          "Longs against shorts — each symbol's long and short bars are always the same length: every share bought was sold by someone.",
          "Gains and losses add up to zero — gateways trade with each other, so one's gain is another's loss; the sum is shown.",
          "Netting and money in and out — cash: buys set against sells. Not pm-eod's settlement, which moves the day's change in P&L.",
          "Who traded with whom — each cell is what the row's gateway bought from the column's; beyond the 20 that traded most, gateways are gathered as others.",
          "A position's replay — the top line is the position after each fill; the dots are fill prices (green buy, red sell) against the average-cost line. Select a fill in the table to have it written out. A red warning that the replay does not end where the ledger does is a fault: report it.",
        ],
      },
    ],
  },
  {
    id: "overview",
    title: "Overview warnings (ADMIN)",
    blocks: [
      {
        bullets: [
          "No new clearing write for at least N s — during continuous trading only, when the last clearing write has not changed for 30 s while this page was open: no trade has arrived, or pm-clearing is not writing. Health tells which.",
          "The last EOD run ended failed — pm-eod failed for that day; see EOD Settlement.",
          "Trading day … is closed but not settled — pm-eod has not run for it yet; expected right after the close.",
          "Needs attention lists the largest losses and the five largest open positions; select a row to open the participant.",
        ],
      },
    ],
  },
  {
    id: "units",
    title: "Units",
    blocks: [
      {
        paragraphs: [
          "Clearing money is in ticks of each symbol's tick decimals; every value is shown with its own symbol's precision. Cross-symbol totals come from the API already converted.",
          "EOD settlement amounts are a separate unit, minor units (2 decimals).",
        ],
      },
    ],
  },
  {
    id: "freshness",
    title: "Freshness",
    blocks: [
      {
        paragraphs: [
          "pm-clearing commits fills in batches (5 s at most by default), so current-state screens refresh every 5 s and say when the data was last committed.",
          "History, trades, events and settlement are fetched on demand and cached; health every 30 s; reconciliation only when you press Run.",
        ],
      },
    ],
  },
  {
    id: "errors",
    title: "Errors",
    blocks: [
      {
        paragraphs: [
          "Errors are not zeros. A refused request (403), an unavailable ledger (503 CLEARING_DB / EOD_DB), a reply that does not match the contract, or an unreachable gateway each show as an error with its reason. An empty table always means there is nothing to show.",
        ],
      },
    ],
  },
  {
    id: "retention",
    title: "Retention",
    blocks: [
      {
        paragraphs: [
          "Raw trades are kept for a retention window (90 days by default; the trade screen shows from which day). Session and gateway-session times are when clearing observed them.",
          "A GAP means clearing saw trade ids jump; no GAP does not prove the feed was complete.",
        ],
      },
    ],
  },
];
