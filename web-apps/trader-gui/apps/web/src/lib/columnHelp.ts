/**
 * What each table column means (WP-UI02), by table and the heading as shown.
 * One source for every table, so the wording is the same wherever a column
 * appears; `<HeaderTip>` looks it up.
 */
export type HelpTable =
  | "blotter"
  | "market"
  | "positions"
  | "trades"
  | "admin-gateways"
  | "admin-risk"
  | "admin-circuit"
  | "admin-monitor";

export const COLUMN_HELP: Record<HelpTable, Record<string, string[]>> = {
  blotter: {
    Symbol: ["The instrument the order is for."],
    Side: ["BUY: you want to buy. SELL: you want to sell."],
    Type: ["How the order behaves against the book: Market, Limit, Stop, Stop-Limit, FOK, IOC, Iceberg or Trailing Stop. See Help → Order Types."],
    TIF: ["Time in force: how long the order lives. DAY until end of day, GTC until cancelled, ATO / ATC for the opening / closing auction."],
    Qty: ["The total quantity you ordered."],
    Remaining: ["The quantity still open. It counts down to 0 as the order trades; for an Iceberg it is the whole order, not just the visible slice."],
    Price: ["The limit price. A dash means the order has none: Market and Stop orders trade at what the book offers."],
    Group: ["The OCO or Combo id that links this order to others. A fill or cancel of one linked order can cancel the rest."],
    Status: ["Where the order is in its life: PENDING, NEW, PARTIAL, FILLED, CANCELLED, REJECTED or EXPIRED. See Help → Order Status."],
    Updated: ["When the order last changed."],
    "Order ID": ["The engine's identifier for the order. Click it to see the whole lifecycle: every acknowledgement, fill and cancel."],
  },
  market: {
    Symbol: ["The instrument. Click a row to open it in the workspace."],
    Bid: ["The best price a buyer is currently offering, and the quantity at it."],
    Ask: ["The best price a seller is currently asking, and the quantity at it. The gap to the bid is the spread."],
    Last: ["The price of the most recent trade."],
    "Chg %": ["Change of the last price against the day's opening price, in percent. Blank until the symbol has an opening price."],
    Volume: ["The quantity traded in this symbol today."],
    Status: ["Whether the symbol is trading normally, in an auction call, or halted."],
  },
  positions: {
    Symbol: ["The instrument."],
    Position: ["What you hold. Positive is long (you own it), negative is short (you owe it)."],
    VWAP: ["Volume-weighted average cost of the open position: the average price you paid, each trade weighted by its size."],
    "Last Traded": ["The latest trade price in this symbol on the venue."],
    "Market Value": ["Position × last traded price: what the open position is worth at the latest market price."],
    "Unrealized P&L": ["Gain or loss if the position were closed at the latest price: position × (last − VWAP). It changes with every trade until you close. Fees are not included and it assumes the whole size can be closed at that price."],
    "Session P&L": ["Gain or loss locked in by closing trades in today's session. It comes from the clearing ledger, so it survives a gateway restart."],
    "MTD P&L": ["Realized gain or loss in this symbol since the first of the month, including today."],
    "YTD P&L": ["Realized gain or loss in this symbol since the first of January, including today."],
    Action: ["Flatten closes the position with a Market order on the opposite side."],
  },
  trades: {
    Time: ["When the fill happened."],
    Symbol: ["The instrument traded."],
    Side: ["Whether this fill bought or sold for you."],
    "Fill Qty": ["The quantity traded in this fill. One order can have several fills."],
    "Fill Price": ["The price this fill traded at. The trade prints at the resting order's price, which can be better than your limit."],
    Remaining: ["What was still open on the order after this fill. 0 means this fill completed it."],
    "Trade ID": ["The identifier of the trade, shared with the counterparty's fill."],
    "Order ID": ["The order this fill belongs to."],
  },
  "admin-gateways": {
    "Gateway ID": ["The identifier a participant connects with. It appears on every order and fill."],
    Role: ["What the gateway may do: TRADER sends orders, MARKET_MAKER also quotes, ADMIN may operate the venue."],
    Description: ["The description from the configuration."],
    Connected: ["Whether the gateway is connected to the engine right now."],
    Action: ["Kick disconnects the gateway; the engine cancels its resting orders and quotes. It can reconnect."],
  },
  "admin-risk": {
    Level: ["The name of a risk profile, or of a circuit breaker level in a symbol's ladder."],
    "Static Band": ["The maximum distance of an order price from the reference price, in percent."],
    "Dynamic Band": ["The maximum distance of an order price from the last trade price, in percent."],
    Symbol: ["The instrument."],
    Profile: ["Where the symbol's bands come from: its own override, its risk level, or the default."],
    "Tick Dec.": ["Decimals in the tick size: the smallest price step. 2 means prices move in 0.01 steps. Prices that are not a multiple of the tick are rejected."],
    "CB Levels": ["Circuit breaker levels configured for the symbol: price moves that halt trading."],
    "Last Bid": ["The best bid in the latest book snapshot."],
    "Last Ask": ["The best ask in the latest book snapshot."],
    "Price Shift": ["How far the price must move, in percent, to trip this level and halt the symbol."],
    "Halt Duration": ["How long trading stays halted at this level before the reopening auction."],
  },
  "admin-circuit": {
    Symbol: ["The halted instrument."],
    Level: ["The circuit breaker level that tripped. Deeper levels trip on larger price moves and halt for longer."],
    "Trigger Price": ["The price that tripped the breaker."],
    "Reference Price": ["The price the move was measured against."],
    "Est. Resume": ["When trading is expected to reopen. Every halt reopens with a call auction, so it resumes on the uncross."],
    Source: ["What halted trading: the automatic ladder or an administrator."],
    Action: ["Resume ends the halt by hand."],
  },
  "admin-monitor": {
    Time: ["When the event was published."],
    Seq: ["A running number: gaps mean missed events."],
    Type: ["The kind of event, such as an acknowledgement, fill, cancel or session change."],
    "Order / Gateway": ["The order or gateway the event is about."],
    Symbol: ["The instrument the event is about."],
    Details: ["The event's own fields."],
  },
};

export function columnHelp(table: HelpTable, heading: string): string[] | undefined {
  return COLUMN_HELP[table][heading];
}
