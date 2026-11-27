/**
 * Static help content for the help drawer (clearing-gui's block structure).
 * Mark and mask wording comes from lib/marks, the same constants the canvas
 * and its lists use, so help and screen cannot drift apart.
 */
import { END_MARKS, MASK_EFFECT, MASK_LABEL } from "@/lib/marks";

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
          "A read-only review of the retained audit trail: what the exchange recorded, reconstructed by pm-audit-replay's own rules. It talks only to pm-api-gwy, and only an ADMIN key may read audit evidence.",
          "Nothing here can trade, change the exchange, or edit the evidence.",
        ],
      },
      {
        heading: "First steps",
        bullets: [
          "Choose an evidence collection in the top bar. It is pinned as a snapshot: every file's size and hash, and the active audit.log's complete lines. Every view reads that snapshot, so pages never drift onto records written later.",
          "Read the evidence banner before anything else: it says what the snapshot covers and what it cannot support.",
          "Open Market, pick a symbol, and brush the chart to zoom. Click a lifeline (or press Enter on it in the list) for the order's story.",
        ],
      },
      {
        heading: "This release",
        paragraphs: [
          "Overview (the banner) and Market are built. Findings, Participants, Explorer, Integrity & Coverage and Investigations say \"Not in this release\".",
        ],
      },
    ],
  },
  {
    id: "evidence",
    title: "Evidence banner",
    blocks: [
      {
        paragraphs: [
          "Above every workspace once a snapshot is pinned. It cannot be folded while a check has failed: a failed manifest, or a FAIL or ERROR in an attached pm-sim-forensics report.",
        ],
      },
      {
        heading: "What each line means",
        bullets: [
          "Extent: the first and last record on the receipt clock, the records and the engine runs.",
          "Gaps: recorder gaps are the replay's ESEQ_GAP findings, records the engine published that pm-audit never received. \"no recorder gap\" is a measured zero; an error is never shown as zero.",
          "Manifest: \"checked, unanchored\" means the hash chain and every archive match, but no copy of the head hash is kept outside this host, so a rewritten chain would not show. \"failed\" lists each problem. \"no manifest\" means no day has been archived.",
          "Forensics: the checks of a pm-sim-forensics report beside the collection, per status. SKIPPED (its data was absent) and ERROR (the check broke) are never a pass. A report about other audit files is flagged and not used.",
          "Not available: each analysis the evidence cannot support, with its reason code (hover for the detail).",
        ],
      },
    ],
  },
  {
    id: "market",
    title: "Market canvas",
    blocks: [
      {
        paragraphs: [
          "One symbol on one time axis. Three bands: the session phase on top, the depth heatmap with order lifelines and trades in the middle, and the signed flow strip at the bottom.",
        ],
      },
      {
        heading: "Depth heatmap",
        bullets: [
          "Cells are recorded book observations only: the displayed quantity per price level, bids blue and asks amber, darker for more.",
          "An observation is valid until the next one, a phase change, an uncross, lost records or the engine stopping. Nothing is interpolated; a bin without a valid observation is empty.",
          "Bins are never finer than the median time between observations (the cadence line under the symbol).",
          `${MASK_LABEL.gap}, hatched red: ${MASK_EFFECT.gap}.`,
          `${MASK_LABEL.halt}, hatched amber: ${MASK_EFFECT.halt}.`,
        ],
      },
      {
        heading: "Order lifelines",
        bullets: [
          "Each order or quote leg is a bar at its price from its admission to its end, thicker for more displayed quantity, dashed while a stop is held off the book.",
          "A new segment starts at every fill, iceberg refill, amendment or trigger.",
          ...Object.values(END_MARKS).map((m) => `${m.glyph} ${m.text}`),
          "Over 5,000 segments the lifelines are summed per price level instead; brush a shorter interval to see each order.",
          "The list under the chart holds the same lifelines with their end reasons in words: arrow keys move, Home and End jump, Enter opens.",
        ],
      },
      {
        heading: "Trades and flow",
        bullets: [
          "▲ buyer-initiated and ▼ seller-initiated trades, ◆ auction prints; the size of a mark grows with the quantity.",
          "The flow strip sums aggressive volume per bin: up for buyer-initiated, down for seller-initiated. Auction prints have no aggressor and are not signed.",
        ],
      },
      {
        heading: "Zoom and links",
        bullets: [
          "Drag across the chart (a brush) to set the interval; \"Whole session\" undoes it. Back and Forward restore earlier intervals.",
          "The interval, the symbol and an open drawer are in the address: copy it to share the exact view of this snapshot.",
        ],
      },
    ],
  },
  {
    id: "drawer",
    title: "Order drawer",
    blocks: [
      {
        bullets: [
          "Story: pm-audit-replay's narration of the order's episodes, fact by fact, in canonical order. Links between episodes carry their confidence (RECORDED, CERTAIN, STRONG, HEURISTIC).",
          "Checks: the replay's findings on those episodes, with code, severity and lane, or \"No finding on this order's episodes.\"",
          "Raw evidence: every retained record naming the order, with its topic, payload and audit file:line, the exact bytes the story was told from.",
          "A story never crosses into another engine run: the drawer asks for the lifeline's run.",
        ],
      },
    ],
  },
  {
    id: "clocks",
    title: "Clocks & units",
    blocks: [
      {
        bullets: [
          "Times are on the receipt clock: when pm-audit received the record, in UTC, to the millisecond. It is the only clock on every record. Several effects of one command share one stamp.",
          "Prices are integer ticks, shown as money only with the tick_decimals the records state; a symbol without one shows ticks.",
          "Engine runs are numbered from 0 in the snapshot; an order id reused after a restart is a different order in another run.",
        ],
      },
    ],
  },
];
