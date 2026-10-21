/**
 * Explanations for table columns and value rows (WP-UI02), looked up by the
 * heading as shown. `undefined` shows no tip.
 */

/** Overview and Movers columns, by heading. */
const COLUMN: Record<string, string> = {
  Symbol: "The instrument's ticker. Click a row to open its detail.",
  Last: "The price of the most recent trade.",
  Chg: "Last price minus the reference price. The reference is the previous close; a row marked * has none on record and is measured from today's open.",
  "%Chg": "Chg as a percentage of the reference price. A * marks a change measured from today's open because no previous close is on record.",
  "Bid sz": "The quantity available at the best bid.",
  Bid: "The best bid: the highest price a buyer is offering.",
  Ask: "The best ask: the lowest price a seller will accept.",
  "Ask sz": "The quantity available at the best ask.",
  Spread: "Best ask minus best bid: what an immediate round trip costs. Narrow means liquid.",
  Volume: "The quantity traded today.",
  Turnover: "The money value traded today, estimated as volume × VWAP. It is a reconstruction, so it may differ slightly from the sum of the individual trades.",
  Time: "When the latest trade happened, in the exchange's time zone.",
  Indic: "Indicative price: the price at which the symbol would uncross if the auction ended now. It changes as orders arrive. In an auction the quote columns are replaced by these.",
  "Indic sz": "The quantity that would trade at the indicative price.",
  Imbalance: "The quantity left over at the indicative price and the side it is on. A BUY imbalance means more buy than sell interest: the price tends to rise during the call. Balanced is the aim of an auction.",
  "Value traded": "The money value traded today, estimated as volume × VWAP.",
};

/** Heading text that depends on the tab. */
const MOVERS: Record<string, string> = {
  "%Chg": "Change since the previous close in percent. The label beside the table says if the open is used instead.",
  Turnover: "The money value traded today, estimated as volume × VWAP. The Active tab ranks by it.",
};

const DEPTH: Record<string, string> = {
  Cum: "Cumulative quantity: this level plus every level nearer the best price. It is how much you could trade through to this price.",
  Qty: "The quantity resting at this price level, over all orders there.",
  "#": "How many separate orders rest at this price. Only the count is shown, never who they belong to.",
  Bid: "The price of a bid level, best (highest) first.",
  Ask: "The price of an ask level, best (lowest) first.",
  "%": "How far this level's price is from its side's best price, as a percentage. A big quantity far from the best price matters less than the same quantity right at it.",
};

const TAPE: Record<string, string> = {
  Time: "When the trade happened, in the exchange's time zone.",
  Symbol: "The instrument traded.",
  Price: "The price the trade printed at.",
  Qty: "The quantity traded.",
  Side: "The aggressor: the side that crossed the spread and took liquidity. ▲ BUY means a buyer hit the ask; ▼ SELL means a seller hit the bid. Blank when the side is not known.",
};

const NEWS: Record<string, string> = {
  Time: "When the news item was published.",
  Status: "RUMOUR: not confirmed, with the credibility the source gives it. CONFIRMED: a later item confirmed a rumour. RETRACTED: withdrawn, shown struck through. Blank: ordinary news.",
  Scope: "MARKET: moves the whole market. Otherwise the symbols the item concerns.",
  Headline: "The text of the item. Green leans positive for prices, red negative.",
};

/** Rows of the symbol and index detail panels, by label. */
const VALUE: Record<string, string> = {
  Bid: "The best bid and the quantity at it.",
  Ask: "The best ask and the quantity at it.",
  Spread: "Best ask minus best bid. In basis points (bps, 1/100 of a percent) beside it, so tight and wide can be compared across cheap and expensive instruments.",
  "Mid (live)": "The midpoint of the best bid and ask, a fair-price estimate. It moves with the quotes, not with trades.",
  "Prev close": "The last trade price of the previous session.",
  Open: "The price of the first trade today.",
  High: "The highest trade price today.",
  Low: "The lowest trade price today.",
  Last: "The latest trade price.",
  VWAP: "Volume-weighted average price: total value traded divided by total volume. The benchmark an execution is judged against; the note shows where the last price sits relative to it.",
  Indicative: "The price at which the symbol would uncross if the auction ended now, and how far it is from the last price. No cross: bids and offers do not overlap yet.",
  "Would match": "The quantity that would trade at the indicative price.",
  Imbalance: "The surplus on one side at the indicative price. Balanced when there is none.",
  Volume: "The quantity traded today.",
  Turnover: "The money value traded today, estimated as volume × VWAP.",
  Trades: "The number of trades today.",
  "Avg trade": "Volume divided by the number of trades: the typical trade size.",
  Phase: "The trading phase this symbol is in right now.",
};

/** Rows of the index panel, by label. */
const INDEX: Record<string, string> = {
  Open: "The index level at the first calculation of the day.",
  High: "The highest index level today.",
  Low: "The lowest index level today.",
  "Aggregate cap": "The summed market capitalisation of the index's constituents, in trillions.",
  Session: "The session phase the index feed reports.",
};

export const columnHelp = (heading: string): string | undefined => COLUMN[heading];
export const moversHelp = (heading: string): string | undefined => MOVERS[heading] ?? COLUMN[heading];
export const depthHelp = (heading: string): string | undefined => DEPTH[heading];
export const tapeHelp = (heading: string): string | undefined => TAPE[heading];
export const newsHelp = (heading: string): string | undefined => NEWS[heading];
export const valueHelp = (label: string): string | undefined => VALUE[label];
export const indexHelp = (label: string): string | undefined => INDEX[label];
