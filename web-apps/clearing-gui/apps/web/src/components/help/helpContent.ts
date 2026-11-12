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
          "ADMIN — the venue: overview, participants and drill-down, symbols, events, gateway sessions, reconciliation, EOD settlement.",
          "TRADER — its own gateway: positions and exposure, retained trades, daily and close history, EOD settlement and balance, gateway sessions.",
          "MARKET_MAKER — the trader views plus My Quote Obligations.",
        ],
      },
      {
        paragraphs: [
          "There is no margin, equity, collateral, buying power or open interest anywhere: nothing in the system computes them.",
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
