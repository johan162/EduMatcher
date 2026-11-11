"""What each check proves, in one or two sentences, for the report."""

from __future__ import annotations

INTRO = """\
A finished simulation leaves the same facts in many places: the audit log of \
every command and every message the engine published, the trade stores of \
stats and clearing, the order-event log, the persisted books, the monitor's \
counters and the daily stores. These checks read those records **after the \
run** and test them against each other and against the rules of the market. \
Nothing here talks to a running system.

Each check is an *oracle* of one kind:

- **conservation**: what went in comes out; nothing is lost, repeated or left \
over (counters, sequence numbers, ids).
- **cross-store**: two stores that record the same fact agree on it.
- **lifecycle**: every order, quote, OCO and combo follows its allowed states.
- **book-state**: the order book obeys the matching rules (price-time \
priority, no crossed book, no trade-through, auction prices, collars).
- **replay**: a fresh engine fed the audit's commands reproduces what the live \
engine did, also under changes that must make no difference.
- **statistical**: not a verdict. These list outliers and coverage to look at \
(status INFO).

PASS means the records are consistent on this check. FAIL means a rule was \
broken, or two records disagree: the sections below give the count and \
examples. SKIPPED means a needed store is absent or the check is slow and \
`--slow` was not given. A check can only find what the run exercised: see \
H5 for what it covered.
"""

EXPLAIN: dict[str, str] = {
    "A1": "Every trade is in both the stats trade log and the clearing trade events, and nothing is in only one.",
    "A2": "Within one engine start the trade counter runs 1, 2, 3, ... with no gap or repeat, so no trade was lost on the way to a store.",
    "A3": "A trade stored by stats and by clearing is the same trade: price, quantity, parties and the engine's timestamp match.",
    "A4": "Trade timestamps rise with the trade counter, and fall in a matching phase; a trade outside one is a time-travel error.",
    "A5": "Each audit topic's sequence number runs without gap or repeat per engine start, so the audit log itself is complete.",
    "B1": "Each side of a trade is named by exactly one FILL of that order, and no FILL names a trade that did not happen.",
    "B2": "For each order the sum of its FILL quantities equals the quantity it traded.",
    "B3": "The stored gateway positions equal an average-cost replay of the clearing trade events.",
    "B4": "The gateway daily summary equals the same replay per trade date, gateway and symbol.",
    "B5": "Positions net to zero per symbol (every buy has a sell), and each position's P&L equals its cash flow.",
    "B8": "Each FILL's quantity and price are the total and the volume-weighted average price of the trades it names.",
    "B6": "The daily counters pm-monitor shows equal the rows in the stores they count.",
    "B7": "The loss, error and feed-gap counters stayed at zero: no message was dropped anywhere in the run.",
    "C1": "Every order's history starts with an ACK or a REJECT and the order is accepted at most once.",
    "C2": "Once an order is filled, cancelled, expired or rejected nothing more happens to it.",
    "C3": "Each fill's remaining quantity is the previous remaining minus the fill quantity, and an order is FILLED exactly when none is left.",
    "C4": "The orders still live in the order-event log are exactly the book the engine persisted at the end.",
    "C5": "OCO pairs and combos hold together: an OCO has two legs, none fills after its sibling ended, and a done leg ends its sibling; a combo leg ending unfilled ends the others.",
    "C6": "Cancel reasons are codes from the spec, and the rejects recorded match the engine's own counter.",
    "C7": "A stop order triggers exactly when a trade reaches its (trailing-ratcheted) stop price, not earlier or later.",
    "C8": "A quote never becomes ACTIVE again once ended, and a fill that inactivates one leg ends its sibling.",
    "C9": "IOC, FOK and MARKET orders end in their own dispatch and never rest; a FOK fills completely or not at all.",
    "C10": "A gateway has one quote per symbol: a replacement, a seed or a cancel ends every earlier leg.",
    "C11": "Fills' cumulative quantity and notional add up and match their trades, and the end report of an order states what filled.",
    "C12": "Every refusal was justified by the state and book it was made on, and no accepted command should have been refused.",
    "C13": "A kill switch or a disconnect cancels exactly the live orders it names, with the right reason.",
    "C14": "Orders expire when their time in force ends (DAY, ATO, ATC), a GTC order never does, and none outlives its end.",
    "D1": "The book snapshots the engine published are never crossed (best bid below best ask) in continuous trading.",
    "D2": "After each command in continuous trading no order rests marketable in the replayed book.",
    "D3": "Every fill is at or inside the aggressing order's limit price.",
    "D4": "Every fill is at the resting order's price, the best opposite price: no trade-through.",
    "D5": "Fills follow time priority within a price level, each as large as the aggressor and the shown slice allow.",
    "D6": "Each auction uncross prints the one volume-maximising price that auction.result states, and fills in priority order.",
    "D7": "No continuous trade is a self-trade of two orders under self-match prevention.",
    "D8": "Trade prices lie on the tick grid, and every priced order entered inside its price collar.",
    "D9": "The book rebuilt from the audit equals every snapshot the engine published and every fill's remaining quantity.",
    "D10": "Each indicative uncross price the engine publishes during a call phase is the one the replayed book gives.",
    "D11": "No continuous trade happens in a halted symbol.",
    "D12": "Each circuit-breaker halt, extension and reopening follows from the trades and the configuration.",
    "E1": "Every state change the engine published answers a command found in the audit: nothing happens on its own.",
    "E2": "A fresh engine fed the audit's commands, in order, publishes what the live engine published. This is the main replay check: a difference means the engine is not deterministic, or the audit lacks an input.",
    "E4": "The final resting book of the re-run equals the book the engine persisted.",
    "E5": "Re-running each symbol alone gives what it gave in the whole re-run, so symbols do not influence each other.",
    "E6": "An engine restored from a checkpoint carries on exactly as the uninterrupted one, so a restart loses no state.",
    "E7": "Metamorphic: renaming gateways and ids, and shifting every price by a fixed number of ticks, changes nothing but the names and prices themselves.",
    "F1": "The daily OHLCV, turnover and VWAP are recomputed from the trade log and match the daily stats.",
    "F2": "The price snapshots and the daily open/close bid and ask are the engine's own book messages.",
    "F3": "The book messages' last price, last quantity, side prices and recent trades follow from the trades.",
    "F4": "book_stats.json holds each symbol's last trade prices.",
    "F6": "The depth figures (depth, imbalance, microprice, cost to move) follow from the book messages they are computed from.",
    "G1": "gtc_orders.json and gtc_combos.json hold only live, well-formed entries.",
    "G2": "Trade ids carry the run sequence of the engine start that made them.",
    "G3": "Each day's archived closing book is the close's checkpoint and the next day's starting book.",
    "H1": "Statistical: ops events (thresholds, process status, disconnects, log warnings) near other findings, to help read them.",
    "H2": "Statistical: outliers in gateway P&L, fill, reject and cancel rates, price jumps without news, and spreads.",
    "H3": "Statistical: engine p99 latency against load, book size, garbage, GC and CPU.",
    "H4": "Statistical: how far and how fast prices follow the value model's jumps.",
    "H5": "Statistical: coverage of the run (orders by entry, type, TIF, SMP, phase and outcome; feature messages), which says what the other checks could have found.",
}
