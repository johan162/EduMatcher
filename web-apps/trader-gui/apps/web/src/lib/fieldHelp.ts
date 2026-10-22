/**
 * What each form field means (WP-UI02), by form and the label as shown. The
 * ticket's own fields carry their help inline; this covers the other forms.
 * `<FieldHelp>` looks a field up here.
 */
export type HelpForm = "oco" | "combo" | "quote" | "amend" | "replace" | "kill-switch" | "halt";

const TIF = [
  "How long the order lives.",
  "DAY: until the end of the trading day. GTC: until it trades or you cancel it.",
];
const SIDE = ["BUY: you want to buy. SELL: you want to sell."];
const QTY_DONE = ["Quantity that has already traded. It cannot be taken back; only the rest can change."];

export const FIELD_HELP: Record<HelpForm, Record<string, string[]>> = {
  oco: {
    "OCO ID": ["Required. Your label for the pair, shown in the blotter's Group column on both legs.", "If one leg is filled, cancelled or rejected, the engine cancels the other."],
    Symbol: ["Required. Both legs trade this instrument."],
    Quantity: ["Required. A whole number, positive. Both legs share this quantity; they compete, so only one can end up filled."],
    TIF: TIF,
    Side: SIDE.concat("A bracket around a long position is two SELL legs."),
    Type: ["Limit: rests at a price and fills when the market reaches it (a profit target).", "Stop: sleeps until the last trade reaches the stop price, then sells or buys at market (a stop-loss)."],
    Price: ["Required for a Limit leg. The price at which that leg trades or better."],
    "Stop price": ["Required for a Stop leg. The last trade price that triggers it: a SELL stop triggers at or below, a BUY stop at or above."],
  },
  combo: {
    "Combo ID": ["Required. Your label for the combo, shown in the blotter's Group column on every leg."],
    "TIF (all legs)": TIF.concat("One value for every leg."),
    "SMP (all legs)": [
      "Self-match prevention: what happens if a leg would trade against your own resting order.",
      "NONE: allowed. CANCEL_AGGRESSOR: the incoming order is cancelled. CANCEL_RESTING: the resting order is cancelled. CANCEL_BOTH: both.",
    ],
    Symbol: ["Required. The instrument for this leg. Legs may be in different symbols."],
    Side: SIDE,
    Type: ["Limit: trades at its price or better. Market: trades at what the book offers and carries no price."],
    Qty: ["Required. Whole shares for this leg, positive."],
    Price: ["Required for a Limit leg; a Market leg has none."],
  },
  quote: {
    "Quote ID": ["Required. Your label for the quote. A new quote for the same symbol replaces the active one."],
    "Bid price": ["The price you will buy at. Must be lower than the ask price."],
    "Bid qty": ["How many shares you will buy at the bid price. A positive whole number."],
    "Ask price": ["The price you will sell at. Must be higher than the bid price."],
    "Ask qty": ["How many shares you will sell at the ask price. A positive whole number."],
    TIF: TIF,
  },
  amend: {
    Symbol: ["The instrument. It cannot be changed."],
    Side: ["The side. It cannot be changed."],
    Type: ["The order type. It cannot be changed."],
    TIF: ["Time in force. It cannot be changed."],
    "Original Qty": ["The quantity the order was submitted with."],
    Filled: QTY_DONE,
    Price: ["The new limit price. Changing the price sends the order to the back of the queue, so consider Replace."],
    Quantity: ["The new total quantity. Reducing it at the same price keeps your place in the queue; increasing it loses the place."],
  },
  replace: {
    Symbol: ["The instrument. It cannot be changed."],
    Side: ["The side. It cannot be changed."],
    "Type · TIF": ["The order type and time in force. The replacement keeps both."],
    Filled: QTY_DONE,
    Price: ["The new limit price for the replacement order."],
    "Stop price": ["The new stop price for the replacement order."],
    "Replacement quantity": [
      "The quantity of the new order.",
      "The old order is cancelled and the new one submitted, so it joins the back of the queue. If the old order is already gone, nothing is sent.",
    ],
  },
  "kill-switch": {
    "By Symbol": ["Cancels every resting order and quote in this symbol, for all participants. Trading is not halted; participants can submit again."],
    "By Gateway": ["Cancels every resting order and quote of this one gateway, in every symbol. The gateway stays connected."],
  },
  halt: {
    Symbol: ["The instrument to halt. Trading stops; resuming reopens with a call auction."],
    Level: ["Which circuit breaker level to apply: it sets the halt length. Leave empty for the symbol's first level."],
  },
};

export function fieldHelp(form: HelpForm, label: string): string[] | undefined {
  return FIELD_HELP[form][label];
}
