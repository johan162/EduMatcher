/**
 * Explanations for the statistics rows and the ladder columns (WP-UI02),
 * looked up by the label on screen. `undefined` shows no tip.
 */

const FIELD: Record<string, string> = {
  Last: "The price of the most recent trade, with an arrow: ▲ above the reference price, ▼ below, ▬ equal. Green, red and grey follow the arrow.",
  Chg: "How far the last price is from the reference price, in price and in percent. The reference is the previous close when there is one, otherwise today's open; the Basis field says which.",
  Size: "The quantity of the most recent trade.",
  "Bid/Ask": "The best bid, the highest price a buyer is offering, and the best ask, the lowest price a seller will accept. They are the top of the two ladders below.",
  Sprd: "The spread: best ask minus best bid, the gap between buyers and sellers. A narrow spread means a liquid market, a wide one an illiquid market. Empty when either side of the book is empty.",
  O: "Open: the price of the first trade of the session.",
  H: "High: the highest trade price of the session.",
  L: "Low: the lowest trade price of the session.",
  C: "Close: the price of the latest trade of the session. It becomes the previous close tomorrow.",
  Prev: "The close of the previous session. n/a when the symbol has no history yet.",
  Range: "High minus low: how far the price has moved within the session.",
  Vol: "The quantity traded in the session so far.",
  Basis: "What Chg is measured against. prev-close: the previous session's close. session-open: today's open, used when there is no previous close. live since HH:MM: history could not be read, so the figures only cover the trades seen since that time.",
};

const COLUMN: Record<string, string> = {
  Ord: "Orders: how many separate orders rest at this price. Orders at one price form one level and trade in the order they arrived.",
  Qty: "Quantity resting at this price, summed over all orders there. For a trade: the quantity traded. Hidden iceberg reserve is not shown.",
  Price: "The price of the level; for a trade, the price it printed at. Bids are listed highest first, asks lowest first, so the best prices meet in the middle.",
  Depth: "A bar for the quantity at this level, scaled to the largest level shown. It grows outward from the centre. Long bars are where much volume is waiting.",
  Time: "When the trade happened, in the exchange's time zone.",
};

const PANEL: Record<string, string> = {
  BIDS: "Buy orders waiting in the book, best (highest) price at the top. A seller who wants to trade now sells to these.",
  ASKS: "Sell orders waiting in the book, best (lowest) price at the top. A buyer who wants to trade now buys from these.",
  TRADES: "The most recent trades, newest first. Green: the price rose against the previous trade, red: it fell, grey: unchanged.",
};

export const fieldHelp = (label: string): string | undefined => FIELD[label];
export const columnHelp = (label: string): string | undefined => COLUMN[label];
export const panelHelp = (title: string): string | undefined => PANEL[title];
